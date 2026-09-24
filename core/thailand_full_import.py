"""Worker importers for the complete, display-first Thailand Hub baseline.

The roles in this module are deliberately separate.  Only evacuation centres are assessment
inputs; villages, volunteer centres, warning resources and vulnerability rasters are supporting
map evidence.  Contact/address columns are never copied from the delivered point sources.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.boundary_import import PLATFORM_BOUNDARY_DATASET_ID
from core.data_import_jobs import (
    DatasetDefinition,
    ImportClaim,
    promote_import_version,
    renew_import_lease,
    version_id_for_import,
)
from core.data_library_models import AreaPopulationSummary, DataImportJob
from core.dataset_readiness import DatasetReadiness
from core.dataset_scan import read_vector_explicit
from core.import_staging import (
    SourceFile,
    cleanup_import_staging,
    promote_staged_import,
    stage_import_files,
)
from core.storage import Storage

HIERARCHY_SOURCE_REF = "administrative_boundary"
HIERARCHY_IMPORTER_VERSION = "grp-thailand-hierarchy/1"
EXPECTED_LEVEL_COUNTS = {"province": 77, "district": 928, "subdistrict": 7436}

POINT_PROFILES: dict[str, dict[str, Any]] = {
    "volunteer_centers": {
        "source_ref": "evacuation_centers/volunteer_center",
        "stem": "ddpm_civil_defense_volunteer_center",
        "dataset_id": uuid5(NAMESPACE_URL, "grp:platform-dataset:thailand-volunteer-centres"),
        "dataset_type": "volunteer_centers",
        "title": "DDPM civil-defence volunteer centres",
        "title_th": "ศูนย์ อปพร. ของ ปภ.",
        "name": "NAME",
        "district_code": "AMPHUR_ID",
        "subdistrict_code": "DISTRICT_I",
        "safe_fields": ("CENTER_ID", "TYPE", "TYPE_DESC"),
    },
    "early_warning_resources": {
        "source_ref": "evacuation_centers/earlywarning_resources",
        "stem": "ddpm_earlywarning_resources",
        "dataset_id": uuid5(NAMESPACE_URL, "grp:platform-dataset:thailand-early-warning-resources"),
        "dataset_type": "early_warning_resources",
        "title": "DDPM early-warning resources",
        "title_th": "ทรัพยากรเตือนภัยล่วงหน้าของ ปภ.",
        "name": "Location",
        "district_code": None,
        "subdistrict_code": None,
        "safe_fields": ("Equipment", "Code", "Subdistric", "District", "Province"),
    },
    "village_locations": {
        "source_ref": "administrative_boundary/village",
        "stem": "village",
        "dataset_id": uuid5(NAMESPACE_URL, "grp:platform-dataset:thailand-village-locations"),
        "dataset_type": "village_locations",
        "title": "Thailand village locations",
        "title_th": "จุดที่ตั้งหมู่บ้านของประเทศไทย",
        "name": "mname",
        "district_code": "acode",
        "subdistrict_code": "tcode",
        "safe_fields": ("pcode", "pname", "tname", "acode", "aname", "tcode", "mcode"),
        # The delivery's undocumented spreadsheet columns. docs/vulnerable-people-data-proof.md
        # holds the evidence for each mapping: male + female == total on 99.52% of rows, and a
        # district reconciles against its real registered population. ADR-0027 records that these
        # remain unconfirmed by the data owner and must never be labelled as vulnerability.
        "population_fields": {
            "male": "oct_side_9",
            "female": "oct_side10",
            "total_population": "oct_side11",
            "households": "oct_side12",
        },
        "importer_version": "grp-village-population/1",
    },
}
POINT_IMPORTER_VERSION = "grp-supporting-points/1"
# A village whose recorded total exceeds this is a misplaced spreadsheet cell, not a village.
MAX_PLAUSIBLE_VILLAGE_POPULATION = 100_000

VULNERABILITY_PROFILES: dict[str, dict[str, Any]] = {
    "vulnerability_child": {
        "filename": "childSensitivity_01.tif",
        "dataset_id": uuid5(NAMESPACE_URL, "grp:platform-dataset:thailand-child-sensitivity"),
        "title": "Child sensitivity",
        "title_th": "ความเปราะบางของเด็ก",
        "key": "child_sensitivity",
    },
    "vulnerability_elderly": {
        "filename": "elderlySensitivity_01.tif",
        "dataset_id": uuid5(NAMESPACE_URL, "grp:platform-dataset:thailand-elderly-sensitivity"),
        "title": "Older-person sensitivity",
        "title_th": "ความเปราะบางของผู้สูงอายุ",
        "key": "elderly_sensitivity",
    },
    "vulnerability_disability": {
        "filename": "disability_total.tif",
        "dataset_id": uuid5(NAMESPACE_URL, "grp:platform-dataset:thailand-disability-support"),
        "title": "Disability support indicator",
        "title_th": "ตัวชี้วัดการสนับสนุนคนพิการ",
        "key": "disability_support",
    },
}
VULNERABILITY_SOURCE_REF = "vulnerable_people"
VULNERABILITY_IMPORTER_VERSION = "grp-vulnerability-display/1"
# Recorded on every boundary row this Thailand delivery creates; see core/boundary_import.py.
COUNTRY_NAME = "Thailand"


class ThailandFullImportError(ValueError):
    """A full-baseline collection did not pass safe technical validation."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sidecars(folder: Path, stem: str, prefix: str) -> tuple[SourceFile, ...]:
    required = (".shp", ".shx", ".dbf", ".prj")
    missing = [suffix for suffix in required if not (folder / f"{stem}{suffix}").is_file()]
    if missing:
        raise ThailandFullImportError(f"{folder.name} is missing required Shapefile components")
    files = []
    for path in sorted(folder.glob(f"{stem}.*")):
        suffix = path.name[len(stem) :].lstrip(".").replace(".", "_")
        storage_name = f"{prefix}-{path.name}".lower()
        files.append(SourceFile(f"source_{prefix}_{suffix}", path, storage_name, {}))
    return tuple(files)


@dataclass(frozen=True)
class HierarchyRecord:
    code: str
    level: str
    name: str
    name_th: str
    province: str | None
    province_th: str | None
    edition: str
    geometry: dict[str, object]
    geometry_sha256: str


def _read_polygon_level(path: Path, level: str) -> list[HierarchyRecord]:
    from shapely import from_wkb, to_wkb
    from shapely.geometry import MultiPolygon, Polygon, mapping

    result, _, _, _ = read_vector_explicit(path, read_geometry=True)
    meta, _, geometries, fields = result
    if str(meta.get("crs") or "").upper() != "EPSG:4326" or geometries is None:
        raise ThailandFullImportError(f"{level} boundaries must be polygon data in EPSG:4326")
    names = [str(value) for value in meta.get("fields", [])]
    columns = {name: values for name, values in zip(names, fields, strict=True)}
    mapping_fields = {
        "province": ("ADMIN_ID1", "NAME_ENG1", "NAME1"),
        "district": ("ADMIN_ID2", "NAME_ENG2", "NAME2"),
        "subdistrict": ("ADMIN_ID3", "NAME_ENG3", "NAME3"),
    }
    code_field, english_field, thai_field = mapping_fields[level]
    required = {code_field, english_field, thai_field, "VERSION", "NAME_ENG1", "NAME1"}
    if not required.issubset(columns):
        raise ThailandFullImportError(f"{level} boundary attributes are incomplete")
    rows: list[HierarchyRecord] = []
    for index, raw in enumerate(geometries):
        geometry = from_wkb(raw) if raw is not None else None
        if (
            not isinstance(geometry, (Polygon, MultiPolygon))
            or geometry.is_empty
            or not geometry.is_valid
        ):
            raise ThailandFullImportError(f"{level} boundaries contain invalid geometry")
        multi = geometry if isinstance(geometry, MultiPolygon) else MultiPolygon([geometry])
        code = _text(columns[code_field][index])
        name = _text(columns[english_field][index])
        name_th = _text(columns[thai_field][index])
        if not code or not name or not name_th:
            raise ThailandFullImportError(f"{level} boundaries contain blank identifiers")
        rows.append(
            HierarchyRecord(
                code,
                level,
                name,
                name_th,
                None if level == "province" else _text(columns["NAME_ENG1"][index]),
                None if level == "province" else _text(columns["NAME1"][index]),
                _text(columns["VERSION"][index]),
                dict(mapping(multi)),
                sha256(to_wkb(multi, byte_order=1, output_dimension=2)).hexdigest(),
            )
        )
    expected = EXPECTED_LEVEL_COUNTS[level]
    if len(rows) != expected or len({row.code for row in rows}) != expected:
        raise ThailandFullImportError(f"Expected {expected} unique {level} boundaries")
    return rows


def _hierarchy_sources(root: Path) -> tuple[SourceFile, ...]:
    specs = (
        ("nation_boundary", "Thailand_Boundaries", "nation"),
        ("province_boundary", "Thailand_Province_Boundaries.dbf", "province"),
        ("district_boundary", "Thailand_District_Boundaries", "district"),
        ("sub-district_boundary", "Thailand_SubDistrict_Boundaries.dbf", "subdistrict"),
    )
    files: list[SourceFile] = []
    for folder, stem, prefix in specs:
        files.extend(_sidecars(root / HIERARCHY_SOURCE_REF / folder, stem, prefix))
    return tuple(files)


def _materialize_hierarchy(records: list[HierarchyRecord]):
    def materialize(session: Session, version_id: UUID) -> None:
        rows = [
            Boundary(
                id=uuid5(NAMESPACE_URL, f"grp:boundary:{version_id}:{item.level}:{item.code}"),
                admin_code=item.code,
                admin_level=item.level,
                name=item.name,
                name_th=item.name_th,
                province_name=item.province,
                province_name_th=item.province_th,
                country_name=COUNTRY_NAME,
                geom=item.geometry,
                source="ADPC Data Science Thailand hierarchy delivery",
                edition=item.edition,
                geometry_sha256=item.geometry_sha256,
                collection_version_id=version_id,
                is_supported=False,
            )
            for item in records
        ]
        session.add_all(rows)
        session.flush()
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text(
                    "UPDATE boundary SET geom_postgis = "
                    "ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)), "
                    "geom_simplified_postgis = ST_Multi(ST_SetSRID("
                    "ST_GeomFromGeoJSON(:geometry), 4326)) WHERE id = :id"
                ),
                [
                    {"id": row.id, "geometry": json.dumps(item.geometry, separators=(",", ":"))}
                    for row, item in zip(rows, records, strict=True)
                ],
            )

    return materialize


def process_hierarchy_import(
    session: Session, storage: Storage, root: Path, claim: ImportClaim, *, lease_minutes: int
) -> UUID | None:
    job = session.get(DataImportJob, claim.import_id)
    if job is None or job.category != "boundary" or job.source_ref != HIERARCHY_SOURCE_REF:
        raise ThailandFullImportError("Import does not reference the Thailand hierarchy")
    province_path = (
        root / HIERARCHY_SOURCE_REF / "province_boundary" / "Thailand_Province_Boundaries.dbf.shp"
    )
    district_path = (
        root / HIERARCHY_SOURCE_REF / "district_boundary" / "Thailand_District_Boundaries.shp"
    )
    subdistrict_path = (
        root
        / HIERARCHY_SOURCE_REF
        / "sub-district_boundary"
        / "Thailand_SubDistrict_Boundaries.dbf.shp"
    )
    provinces = _read_polygon_level(province_path, "province")
    districts = _read_polygon_level(district_path, "district")
    subdistricts = _read_polygon_level(subdistrict_path, "subdistrict")
    # The delivered nation file contains one province. Derive the country outline from all 77
    # source-native province polygons instead of publishing that mislabeled feature.
    from shapely import to_wkb
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    country = unary_union([shape(item.geometry) for item in provinces])
    records = (
        [
            HierarchyRecord(
                "TH",
                "country",
                "Thailand",
                "ประเทศไทย",
                None,
                None,
                provinces[0].edition,
                dict(mapping(country)),
                sha256(to_wkb(country, byte_order=1, output_dimension=2)).hexdigest(),
            )
        ]
        + provinces
        + districts
        + subdistricts
    )
    if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=35):
        return None
    staged = stage_import_files(
        storage, claim, source_root=root, files=list(_hierarchy_sources(root))
    )
    if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=70):
        return None
    version_id = version_id_for_import(claim.import_id)
    promoted = promote_staged_import(
        storage, staged, dataset_id=PLATFORM_BOUNDARY_DATASET_ID, version_id=version_id
    )
    counts = {"country": 1, **EXPECTED_LEVEL_COUNTS}
    published = promote_import_version(
        session,
        claim,
        dataset=DatasetDefinition(
            PLATFORM_BOUNDARY_DATASET_ID,
            None,
            "boundary",
            "platform",
            "Thailand district boundaries",
            "ADPC Data Science delivery",
        ),
        promoted=promoted,
        readiness=DatasetReadiness.TECHNICALLY_VALID,
        importer_version=HIERARCHY_IMPORTER_VERSION,
        version_metadata={
            "admin_levels": list(counts),
            "level_counts": counts,
            "edition": provinces[0].edition,
            "feature_count": len(records),
            "source_ref": HIERARCHY_SOURCE_REF,
            "country_geometry_derived_from": "77 province polygons",
        },
        report={"message": "Thailand administrative hierarchy imported.", "level_counts": counts},
        materialize=_materialize_hierarchy(records),
    )
    if published is not None:
        cleanup_import_staging(storage, claim)
    return published


def _current_boundaries(session: Session) -> tuple[dict[str, Boundary], list[Boundary]]:
    version = session.scalar(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "boundary", Dataset.owner_kind == "platform")
        .order_by(DatasetVersion.created_at.desc())
        .limit(1)
    )
    if version is None:
        raise ThailandFullImportError("Import the Thailand hierarchy before supporting points")
    boundaries = session.scalars(
        select(Boundary).where(Boundary.collection_version_id == version.id)
    ).all()
    districts = {item.admin_code: item for item in boundaries if item.admin_level == "district"}
    subdistricts = [item for item in boundaries if item.admin_level == "subdistrict"]
    if len(districts) != 928 or len(subdistricts) != 7436:
        raise ThailandFullImportError("The current boundary version is not the complete hierarchy")
    return districts, subdistricts


def process_point_import(
    session: Session, storage: Storage, root: Path, claim: ImportClaim, *, lease_minutes: int
) -> UUID | None:
    from shapely import from_wkb
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    job = session.get(DataImportJob, claim.import_id)
    profile = POINT_PROFILES.get(job.category if job else "")
    if job is None or profile is None or job.source_ref != profile["source_ref"]:
        raise ThailandFullImportError("Import does not reference an enabled supporting-point role")
    folder = root / profile["source_ref"]
    sources = _sidecars(folder, profile["stem"], job.category)
    result, _, _, _ = read_vector_explicit(folder / f"{profile['stem']}.shp", read_geometry=True)
    meta, _, geometries, fields = result
    if str(meta.get("crs") or "").upper() != "EPSG:4326" or geometries is None:
        raise ThailandFullImportError("Supporting points must declare EPSG:4326")
    field_names = [str(value) for value in meta.get("fields", [])]
    columns = {name: values for name, values in zip(field_names, fields, strict=True)}
    required = {profile["name"], *profile["safe_fields"]}
    if not required.issubset(columns):
        raise ThailandFullImportError("Supporting-point attributes are incomplete")
    districts, subdistricts = _current_boundaries(session)
    sub_polygons = [shape(item.geom) for item in subdistricts]
    tree = STRtree(sub_polygons)
    subdistrict_by_code = {item.admin_code: item for item in subdistricts}
    district_by_name = {
        (item.name_th or item.name).replace(" ", "").casefold(): item for item in districts.values()
    }
    rows: list[dict[str, Any]] = []
    outside = 0
    # Aggregated once here so a planner click is a single indexed read, never a GIS scan of
    # 80,397 points in a web request.
    population_by_area: dict[tuple[str, str], dict[str, int]] = {}
    for index, raw in enumerate(geometries):
        point = from_wkb(raw) if raw is not None else None
        if not isinstance(point, Point) or point.is_empty or not point.is_valid:
            raise ThailandFullImportError("Supporting-point geometry is invalid")
        district_code = (
            _text(columns.get(profile["district_code"], [""] * len(geometries))[index])
            if profile["district_code"]
            else ""
        )
        if job.category == "village_locations":
            district_code = district_code[:4]
        district = districts.get(district_code)
        subdistrict = None
        raw_sub_code = (
            _text(columns.get(profile["subdistrict_code"], [""] * len(geometries))[index])
            if profile["subdistrict_code"]
            else ""
        )
        normalized_sub_code = raw_sub_code[:6]
        if normalized_sub_code:
            subdistrict = subdistrict_by_code.get(normalized_sub_code)
        if subdistrict is None:
            for candidate in tree.query(point):
                position = int(candidate)
                if sub_polygons[position].covers(point):
                    subdistrict = subdistricts[position]
                    break
        if district is None and subdistrict is not None:
            district = districts.get(subdistrict.admin_code[:4])
        if district is None and job.category == "early_warning_resources":
            claimed = _text(columns["District"][index]).replace(" ", "").casefold()
            district = district_by_name.get(claimed)
        if district is None:
            outside += 1
        safe_attributes = {
            key: _text(columns[key][index])
            for key in profile["safe_fields"]
            if _text(columns[key][index])
        }
        safe_attributes.update(
            {
                "admin_code": district.admin_code if district else None,
                "subdistrict_code": subdistrict.admin_code if subdistrict else None,
                "role": profile["dataset_type"],
            }
        )
        population = _village_population(columns, profile, index)
        if profile.get("population_fields"):
            for area_level, area in (("district", district), ("subdistrict", subdistrict)):
                if area is None:
                    continue
                bucket = population_by_area.setdefault(
                    (area.admin_code, area_level),
                    {
                        "village_count": 0,
                        "counted_village_count": 0,
                        "male": 0,
                        "female": 0,
                        "total_population": 0,
                        "households": 0,
                    },
                )
                bucket["village_count"] += 1
                if population is not None:
                    bucket["counted_village_count"] += 1
                    for key, value in population.items():
                        bucket[key] += value
        if population is not None:
            safe_attributes.update({key: str(value) for key, value in population.items()})
        rows.append(
            {
                "source_index": index,
                "boundary_id": district.id if district else None,
                "name": _text(columns[profile["name"]][index]) or f"{profile['title']} {index + 1}",
                "lon": float(point.x),
                "lat": float(point.y),
                "attributes": safe_attributes,
            }
        )
    if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=40):
        return None
    staged = stage_import_files(storage, claim, source_root=root, files=list(sources))
    if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=70):
        return None
    version_id = version_id_for_import(claim.import_id)
    promoted = promote_staged_import(
        storage, staged, dataset_id=profile["dataset_id"], version_id=version_id
    )

    def materialize(target_session: Session, target_version_id: UUID) -> None:
        target_session.add_all(
            [
                Feature(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"grp:{job.category}:{target_version_id}:{item['source_index']}",
                    ),
                    dataset_version_id=target_version_id,
                    boundary_id=item["boundary_id"],
                    name=item["name"],
                    lon=item["lon"],
                    lat=item["lat"],
                    attributes=item["attributes"],
                )
                for item in rows
            ]
        )
        target_session.add_all(
            [
                AreaPopulationSummary(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"grp:area-population:{target_version_id}:{level}:{admin_code}",
                    ),
                    dataset_version_id=target_version_id,
                    admin_code=admin_code,
                    admin_level=level,
                    village_count=bucket["village_count"],
                    counted_village_count=bucket["counted_village_count"],
                    excluded_village_count=(
                        bucket["village_count"] - bucket["counted_village_count"]
                    ),
                    male=bucket["male"],
                    female=bucket["female"],
                    total_population=bucket["total_population"],
                    households=bucket["households"],
                )
                for (admin_code, level), bucket in sorted(population_by_area.items())
            ]
        )

    counted_villages = sum(b["counted_village_count"] for (_, lvl), b in population_by_area.items()
                           if lvl == "district")
    district_areas = sum(1 for (_, lvl) in population_by_area if lvl == "district")
    published = promote_import_version(
        session,
        claim,
        dataset=DatasetDefinition(
            profile["dataset_id"],
            None,
            profile["dataset_type"],
            "platform",
            profile["title"],
            "DDPM / ADPC Data Science delivery",
        ),
        promoted=promoted,
        readiness=DatasetReadiness.TECHNICALLY_VALID,
        importer_version=str(profile.get("importer_version", POINT_IMPORTER_VERSION)),
        version_metadata={
            "feature_count": len(rows),
            "outside_district_count": outside,
            "source_ref": profile["source_ref"],
            "title_th": profile["title_th"],
            "map_preview": True,
            "display_only": True,
            **(
                {
                    "population_source": "registered village population, source columns "
                    "unconfirmed by the data owner (ADR-0027)",
                    "population_areas": district_areas,
                    "population_counted_villages": counted_villages,
                    "population_excluded_villages": len(rows) - counted_villages,
                }
                if profile.get("population_fields")
                else {}
            ),
        },
        report={
            "message": f"{profile['title']} imported as supporting map evidence.",
            "feature_count": len(rows),
            "outside_district_count": outside,
            **(
                {
                    "population_counted_villages": counted_villages,
                    "population_excluded_villages": len(rows) - counted_villages,
                    "population_areas": district_areas,
                }
                if profile.get("population_fields")
                else {}
            ),
        },
        materialize=materialize,
    )
    if published is not None:
        cleanup_import_staging(storage, claim)
    return published


def _render_vulnerability_preview(
    source: Path, destination: Path
) -> tuple[list[list[float]], dict[str, float]]:
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import calculate_default_transform, reproject

    with rasterio.open(source) as dataset:
        if dataset.count != 1 or str(dataset.crs).upper() != "EPSG:32647":
            raise ThailandFullImportError(
                "Vulnerability rasters must be one-band EPSG:32647 GeoTIFFs"
            )
        transform, native_width, native_height = calculate_default_transform(
            dataset.crs,
            "EPSG:4326",
            dataset.width,
            dataset.height,
            *dataset.bounds,
        )
        scale = max(native_width / 1200, native_height / 1200, 1)
        width = max(1, round(native_width / scale))
        height = max(1, round(native_height / scale))
        transform = transform * transform.scale(native_width / width, native_height / height)
        output = np.full((height, width), np.nan, dtype="float32")
        reproject(
            source=rasterio.band(dataset, 1),
            destination=output,
            src_transform=dataset.transform,
            src_crs=dataset.crs,
            src_nodata=dataset.nodata,
            dst_transform=transform,
            dst_crs="EPSG:4326",
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        valid = np.isfinite(output)
        if not valid.any():
            raise ThailandFullImportError("Vulnerability raster has no displayable values")
        low, high = np.nanpercentile(output[valid], [2, 98])
        if high <= low:
            high = low + 1
        scaled = np.clip((output - low) / (high - low), 0, 1)
        rgba = np.zeros((height, width, 4), dtype="uint8")
        rgba[..., 0] = (75 + 85 * scaled).astype("uint8")
        rgba[..., 1] = (35 + 40 * (1 - scaled)).astype("uint8")
        rgba[..., 2] = (120 + 105 * scaled).astype("uint8")
        rgba[..., 3] = np.where(valid, (35 + 145 * scaled).astype("uint8"), 0)
        with rasterio.open(
            destination,
            "w",
            driver="PNG",
            width=width,
            height=height,
            count=4,
            dtype="uint8",
        ) as target:
            target.write(rgba.transpose(2, 0, 1))
        left = transform.c
        top = transform.f
        right = left + transform.a * width
        bottom = top + transform.e * height
        return [[bottom, left], [top, right]], {"min": float(low), "max": float(high)}


def _village_population(columns: dict, profile: dict, index: int) -> dict[str, int] | None:
    """Read one village's counts, or None when the row cannot be trusted.

    A row is only counted when all four values are present whole numbers, male + female equals
    the recorded total, and the total is a plausible village size. Everything else is excluded and
    reported, never silently coerced to zero: 385 rows of the delivery break the identity and
    fifteen record more people than the largest Thai city.
    """

    fields = profile.get("population_fields")
    if not fields:
        return None
    values: dict[str, int] = {}
    for key, column in fields.items():
        raw = columns.get(column, [None] * (index + 1))[index]
        if raw is None:
            return None
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        if number != number or number in (float("inf"), float("-inf")) or number < 0:
            return None
        values[key] = int(round(number))
    if values["male"] + values["female"] != values["total_population"]:
        return None
    if not 0 < values["total_population"] <= MAX_PLAUSIBLE_VILLAGE_POPULATION:
        return None
    return values


def process_vulnerability_import(
    session: Session, storage: Storage, root: Path, claim: ImportClaim, *, lease_minutes: int
) -> UUID | None:
    job = session.get(DataImportJob, claim.import_id)
    profile = VULNERABILITY_PROFILES.get(job.category if job else "")
    if job is None or profile is None or job.source_ref != VULNERABILITY_SOURCE_REF:
        raise ThailandFullImportError("Import does not reference an enabled vulnerability layer")
    source = root / VULNERABILITY_SOURCE_REF / profile["filename"]
    if not source.is_file():
        raise ThailandFullImportError(f"Missing vulnerability raster {profile['filename']}")
    with tempfile.TemporaryDirectory(prefix="grp-vulnerability-") as folder_name:
        preview = Path(folder_name) / f"{profile['key']}.png"
        bounds, display_range = _render_vulnerability_preview(source, preview)
        if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=45):
            return None
        files = [
            SourceFile(
                "source_geotiff",
                source,
                str(profile["filename"]).lower(),
                {"crs": "EPSG:32647"},
            )
        ]
        staged = stage_import_files(storage, claim, source_root=root, files=files)
        if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=75):
            return None
        version_id = version_id_for_import(claim.import_id)
        promoted = promote_staged_import(
            storage, staged, dataset_id=profile["dataset_id"], version_id=version_id
        )
        preview_key = f"datasets/{profile['dataset_id']}/{version_id}/previews/{profile['key']}.png"
        storage.put(preview_key, preview)
        published = promote_import_version(
            session,
            claim,
            dataset=DatasetDefinition(
                profile["dataset_id"],
                None,
                "vulnerability",
                "platform",
                profile["title"],
                "ADPC Data Science delivery",
            ),
            promoted=promoted,
            readiness=DatasetReadiness.TECHNICALLY_VALID,
            importer_version=VULNERABILITY_IMPORTER_VERSION,
            version_metadata={
                "indicator_key": profile["key"],
                "title_th": profile["title_th"],
                "source_ref": VULNERABILITY_SOURCE_REF,
                "map_preview": True,
                "display_only": True,
                "overlay_key": preview_key,
                "overlay_bounds": bounds,
                "display_range": display_range,
                "meaning": (
                    "Source-native supporting indicator; not a GRP risk score and not "
                    "combined with other layers."
                ),
            },
            report={"message": f"{profile['title']} imported as a separate display-only layer."},
        )
    if published is not None:
        cleanup_import_staging(storage, claim)
    return published


def full_dataset_ids() -> dict[str, UUID]:
    return {
        **{key: value["dataset_id"] for key, value in POINT_PROFILES.items()},
        **{key: value["dataset_id"] for key, value in VULNERABILITY_PROFILES.items()},
    }
