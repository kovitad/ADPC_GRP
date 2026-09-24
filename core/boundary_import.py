"""Validated worker import for the accepted Thailand district-boundary collection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.assessment_models import Boundary
from core.data_import_jobs import (
    DatasetDefinition,
    ImportClaim,
    promote_import_version,
    renew_import_lease,
    version_id_for_import,
)
from core.data_library_models import DataImportJob
from core.dataset_readiness import DatasetReadiness
from core.dataset_scan import read_vector_explicit
from core.import_staging import (
    SourceFile,
    cleanup_import_staging,
    promote_staged_import,
    stage_import_files,
)
from core.storage import Storage

BOUNDARY_SOURCE_REF = "administrative_boundary/district_boundary"
# This importer reads one Thai delivery. The country is recorded on each row rather than assumed
# by consumers, so another Hub's delivery cannot inherit it.
COUNTRY_NAME = "Thailand"
BOUNDARY_STEM = "Thailand_District_Boundaries"
REQUIRED_SUFFIXES = (".shp", ".shx", ".dbf", ".prj")
OPTIONAL_SUFFIXES = (".cpg", ".qmd")
REQUIRED_FIELDS = (
    "ADMIN_ID2",
    "NAME1",
    "NAME_ENG1",
    "NAME2",
    "NAME_ENG2",
    "VERSION",
)
IMPORTER_VERSION = "grp-boundary/1"
PLATFORM_BOUNDARY_DATASET_ID = uuid5(
    NAMESPACE_URL, "grp:platform-dataset:thailand-district-boundaries"
)
SIMPLIFY_TOLERANCE = 0.0005


class BoundaryImportError(ValueError):
    """The known boundary delivery failed a safe technical validation."""


@dataclass(frozen=True)
class BoundaryRecord:
    admin_code: str
    name: str
    name_th: str
    province_name: str
    province_name_th: str
    edition: str
    geometry: dict[str, object]
    simplified_geometry: dict[str, object]
    geometry_sha256: str


@dataclass(frozen=True)
class ValidatedBoundaryCollection:
    records: tuple[BoundaryRecord, ...]
    edition: str
    source_files: tuple[SourceFile, ...]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _source_files(root: Path) -> tuple[SourceFile, ...]:
    folder = root / BOUNDARY_SOURCE_REF
    missing = [
        suffix
        for suffix in REQUIRED_SUFFIXES
        if not (folder / f"{BOUNDARY_STEM}{suffix}").is_file()
    ]
    if missing:
        raise BoundaryImportError("District boundary delivery is missing required sidecar files")
    files: list[SourceFile] = []
    for suffix in (*REQUIRED_SUFFIXES, *OPTIONAL_SUFFIXES):
        path = folder / f"{BOUNDARY_STEM}{suffix}"
        if not path.is_file():
            continue
        extension = suffix.removeprefix(".")
        files.append(
            SourceFile(
                role=f"source_{extension}",
                path=path,
                storage_name=f"boundary{suffix}",
                metadata={"component": extension},
            )
        )
    return tuple(files)


def validate_boundary_collection(root: Path) -> ValidatedBoundaryCollection:
    """Read all 928 delivered features and reject ambiguous or invalid geometry."""

    from shapely import from_wkb, to_wkb
    from shapely.geometry import MultiPolygon, Polygon, mapping

    source_files = _source_files(root)
    shp = root / BOUNDARY_SOURCE_REF / f"{BOUNDARY_STEM}.shp"
    try:
        result, _, _, _ = read_vector_explicit(shp, read_geometry=True)
        meta, _, geometries, fields = result
    except Exception as exc:  # noqa: BLE001 - converted into a safe import finding
        raise BoundaryImportError("District boundary shapefile could not be read") from exc
    if str(meta.get("crs") or "").upper() != "EPSG:4326":
        raise BoundaryImportError("District boundaries must declare EPSG:4326")
    field_names = [str(name) for name in meta.get("fields", [])]
    missing_fields = sorted(set(REQUIRED_FIELDS) - set(field_names))
    if missing_fields:
        raise BoundaryImportError("District boundary attributes are incomplete")
    columns = {name: values for name, values in zip(field_names, fields, strict=True)}
    if geometries is None or len(geometries) == 0:
        raise BoundaryImportError("District boundary collection has no features")

    records: list[BoundaryRecord] = []
    seen_codes: set[str] = set()
    editions: set[str] = set()
    for index, raw_geometry in enumerate(geometries):
        code = _text(columns["ADMIN_ID2"][index])
        values = {
            field: _text(columns[field][index])
            for field in ("NAME1", "NAME_ENG1", "NAME2", "NAME_ENG2", "VERSION")
        }
        if not code or any(not value for value in values.values()):
            raise BoundaryImportError("District boundary has blank required attributes")
        if code in seen_codes:
            raise BoundaryImportError("District administrative codes are not unique")
        seen_codes.add(code)
        editions.add(values["VERSION"])
        if raw_geometry is None:
            raise BoundaryImportError("District boundary has missing geometry")
        geometry = from_wkb(raw_geometry)
        if not isinstance(geometry, (Polygon, MultiPolygon)):
            raise BoundaryImportError("District boundary has a non-polygon geometry")
        if geometry.is_empty or not geometry.is_valid:
            raise BoundaryImportError("District boundary has empty or invalid geometry")
        multi = geometry if isinstance(geometry, MultiPolygon) else MultiPolygon([geometry])
        simplified = multi.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
        geometry_json = dict(mapping(multi))
        simplified_json = dict(mapping(simplified))
        geometry_digest = sha256(
            to_wkb(multi, byte_order=1, output_dimension=2, include_srid=False)
        ).hexdigest()
        records.append(
            BoundaryRecord(
                admin_code=code,
                name=values["NAME_ENG2"],
                name_th=values["NAME2"],
                province_name=values["NAME_ENG1"],
                province_name_th=values["NAME1"],
                edition=values["VERSION"],
                geometry=geometry_json,
                simplified_geometry=simplified_json,
                geometry_sha256=geometry_digest,
            )
        )
    if len(editions) != 1:
        raise BoundaryImportError("District boundary collection contains mixed editions")
    return ValidatedBoundaryCollection(tuple(records), editions.pop(), source_files)


def _materialize_boundaries(
    records: tuple[BoundaryRecord, ...],
):
    def materialize(session: Session, version_id: UUID) -> None:
        # IDs include the collection version, so replacement features never alias.
        rows = [
            Boundary(
                id=uuid5(NAMESPACE_URL, f"grp:boundary:{version_id}:{item.admin_code}"),
                admin_code=item.admin_code,
                admin_level="district",
                name=item.name,
                name_th=item.name_th,
                province_name=item.province_name,
                province_name_th=item.province_name_th,
                country_name=COUNTRY_NAME,
                geom=item.geometry,
                source="ADPC Data Science delivery",
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
            parameters = [
                {
                    "id": row.id,
                    "geometry": json.dumps(item.geometry, separators=(",", ":")),
                    "simplified": json.dumps(item.simplified_geometry, separators=(",", ":")),
                }
                for row, item in zip(rows, records, strict=True)
            ]
            session.execute(
                text(
                    "UPDATE boundary SET "
                    "geom_postgis = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)), "
                    "geom_simplified_postgis = "
                    "ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:simplified), 4326)) "
                    "WHERE id = :id"
                ),
                parameters,
            )

    return materialize


def process_boundary_import(
    session: Session,
    storage: Storage,
    source_root: Path,
    claim: ImportClaim,
    *,
    lease_minutes: int,
) -> UUID | None:
    """Stage, validate and atomically publish one district-boundary collection."""

    job = session.scalar(select(DataImportJob).where(DataImportJob.id == claim.import_id))
    if job is None or job.category != "boundary" or job.source_ref != BOUNDARY_SOURCE_REF:
        raise BoundaryImportError("Import job does not reference the accepted boundary source")
    collection = validate_boundary_collection(source_root)
    if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=35):
        return None
    staged = stage_import_files(
        storage,
        claim,
        source_root=source_root,
        files=list(collection.source_files),
    )
    if not renew_import_lease(session, claim, lease_minutes=lease_minutes, progress=70):
        return None
    version_id = version_id_for_import(claim.import_id)
    promoted = promote_staged_import(
        storage,
        staged,
        dataset_id=PLATFORM_BOUNDARY_DATASET_ID,
        version_id=version_id,
    )
    published = promote_import_version(
        session,
        claim,
        dataset=DatasetDefinition(
            id=PLATFORM_BOUNDARY_DATASET_ID,
            hub_id=None,
            type="boundary",
            owner_kind="platform",
            title="Thailand district boundaries",
            provider="ADPC Data Science delivery",
        ),
        promoted=promoted,
        readiness=DatasetReadiness.TECHNICALLY_VALID,
        importer_version=IMPORTER_VERSION,
        version_metadata={
            "admin_level": "district",
            "crs": "EPSG:4326",
            "edition": collection.edition,
            "feature_count": len(collection.records),
            "source_ref": BOUNDARY_SOURCE_REF,
            "supported_count": 0,
        },
        report={
            "message": "District boundary collection validated and imported.",
            "feature_count": len(collection.records),
            "supported_count": 0,
        },
        materialize=_materialize_boundaries(collection.records),
    )
    if published is not None:
        cleanup_import_staging(storage, claim)
    return published
