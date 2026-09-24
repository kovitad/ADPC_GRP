"""Validated worker import for the accepted DDPM evacuation-centre baseline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.assessment_models import Boundary, Dataset, DatasetVersion, Feature
from core.data_import_jobs import (
    DatasetDefinition,
    ImportClaim,
    promote_import_version,
    renew_import_lease,
    version_id_for_import,
)
from core.data_library_models import DataImportJob
from core.dataset_readiness import DatasetReadiness
from core.dataset_scan import pick_district_field, read_vector_explicit
from core.facility_types import classify_facility
from core.import_staging import (
    SourceFile,
    cleanup_import_staging,
    promote_staged_import,
    stage_import_files,
)
from core.shelter_labels import ShelterLabelInput, compose_labels
from core.storage import Storage

SHELTER_SOURCE_REF = "evacuation_centers/shelters"
SHELTER_STEM = "ddpm_shelters"
REQUIRED_SUFFIXES = (".shp", ".shx", ".dbf", ".prj")
OPTIONAL_SUFFIXES = (".cpg", ".sbn", ".sbx", ".shp.xml")
SHELTER_PROVINCE = "จัง"
# The real delivery and the previously proven v4 import confirm these truncated columns
# (ADR-0024): `สถา` is the facility, `สถ_1` is the responsible/supporting unit, and
# `รอง` is the number of people it can take.
SHELTER_NAME = "สถา"
SHELTER_SUPPORTING_UNIT = "สถ_1"
SHELTER_CAPACITY = "รอง"
REQUIRED_FIELDS = (SHELTER_PROVINCE, SHELTER_NAME)
# Optional context used only to tell two centres of the same name apart. A delivery without
# them still imports; the labels just fall back to a number, which the report counts.
VILLAGE_FIELD_HINTS = ("หมู", "หม_", "village", "moo")
SUBDISTRICT_FIELD_HINTS = ("ตำบ", "ตำ_", "tambon", "subdistrict")
SUPPORTING_UNIT_FIELD_HINTS = ("หน่ว", "สังก", "responsible", "agency")
IMPORTER_VERSION = "grp-shelters/6"
PLATFORM_SHELTER_DATASET_ID = uuid5(
    NAMESPACE_URL, "grp:platform-dataset:thailand-ddpm-evacuation-centres"
)
MAX_MISMATCH_EXAMPLES = 10


class ShelterImportError(ValueError):
    """The known shelter delivery failed a safe technical validation."""


@dataclass(frozen=True)
class ShelterSourceRecord:
    source_index: int
    name: str
    claimed_district: str
    claimed_province: str
    lon: float
    lat: float
    point: object
    capacity: int | None = None
    village: str = ""
    subdistrict: str = ""
    supporting_unit: str = ""


@dataclass(frozen=True)
class ValidatedShelterCollection:
    records: tuple[ShelterSourceRecord, ...]
    source_files: tuple[SourceFile, ...]
    district_field: str


@dataclass(frozen=True)
class AssignedShelter:
    source: ShelterSourceRecord
    boundary_id: UUID
    admin_code: str
    actual_district: str
    actual_province: str
    name_mismatch: bool


def _text(value: Any) -> str:
    return str(value or "").strip()


def _source_files(
    root: Path, source_ref: str = SHELTER_SOURCE_REF
) -> tuple[SourceFile, ...]:
    folder = root / source_ref
    missing = [
        suffix
        for suffix in REQUIRED_SUFFIXES
        if not (folder / f"{SHELTER_STEM}{suffix}").is_file()
    ]
    if missing:
        raise ShelterImportError("Evacuation-centre delivery is missing required sidecar files")
    files: list[SourceFile] = []
    for suffix in (*REQUIRED_SUFFIXES, *OPTIONAL_SUFFIXES):
        path = folder / f"{SHELTER_STEM}{suffix}"
        if not path.is_file():
            continue
        role_suffix = suffix.removeprefix(".").replace(".", "_")
        files.append(
            SourceFile(
                role=f"source_{role_suffix}",
                path=path,
                storage_name=f"shelters{suffix}",
                metadata={"component": suffix.removeprefix(".")},
            )
        )
    return tuple(files)


def validate_shelter_collection(
    root: Path, source_ref: str = SHELTER_SOURCE_REF
) -> ValidatedShelterCollection:
    """Read the complete point layer without exposing fields whose meaning is unconfirmed."""

    from shapely import from_wkb
    from shapely.geometry import Point

    source_files = _source_files(root, source_ref)
    shp = root / source_ref / f"{SHELTER_STEM}.shp"
    try:
        result, _, _, _ = read_vector_explicit(shp, read_geometry=True)
        meta, _, geometries, fields = result
    except Exception as exc:  # noqa: BLE001 - converted to a safe import finding
        raise ShelterImportError("Evacuation-centre shapefile could not be read") from exc
    if str(meta.get("crs") or "").upper() != "EPSG:4326":
        raise ShelterImportError("Evacuation centres must declare EPSG:4326")
    field_names = [str(name) for name in meta.get("fields", [])]
    district_field = pick_district_field(field_names)
    if not set(REQUIRED_FIELDS).issubset(field_names) or district_field is None:
        raise ShelterImportError("Evacuation-centre attributes are incomplete")
    if geometries is None or len(geometries) == 0:
        raise ShelterImportError("Evacuation-centre collection has no features")
    columns = {name: values for name, values in zip(field_names, fields, strict=True)}
    village_field = _pick_optional_field(field_names, VILLAGE_FIELD_HINTS)
    subdistrict_field = _pick_optional_field(field_names, SUBDISTRICT_FIELD_HINTS)
    unit_field = (
        SHELTER_SUPPORTING_UNIT
        if SHELTER_SUPPORTING_UNIT in field_names
        else _pick_optional_field(field_names, SUPPORTING_UNIT_FIELD_HINTS)
    )
    records: list[ShelterSourceRecord] = []
    for index, raw_geometry in enumerate(geometries):
        if raw_geometry is None:
            raise ShelterImportError("Evacuation centre has missing geometry")
        point = from_wkb(raw_geometry)
        if not isinstance(point, Point) or point.is_empty or not point.is_valid:
            raise ShelterImportError("Evacuation-centre collection contains invalid point geometry")
        records.append(
            ShelterSourceRecord(
                source_index=index,
                name=_text(columns[SHELTER_NAME][index]),
                claimed_district=_text(columns[district_field][index]),
                claimed_province=_text(columns[SHELTER_PROVINCE][index]),
                lon=float(point.x),
                lat=float(point.y),
                point=point,
                capacity=(
                    _capacity(columns[SHELTER_CAPACITY][index])
                    if SHELTER_CAPACITY in columns
                    else None
                ),
                village=_text(columns[village_field][index]) if village_field else "",
                subdistrict=_text(columns[subdistrict_field][index]) if subdistrict_field else "",
                supporting_unit=_text(columns[unit_field][index]) if unit_field else "",
            )
        )
    return ValidatedShelterCollection(tuple(records), source_files, district_field)


def _pick_optional_field(field_names: list[str], hints: tuple[str, ...]) -> str | None:
    for candidate in field_names:
        if any(hint in candidate.lower() for hint in hints):
            return candidate
    return None


def _capacity(value: object) -> int | None:
    """A capacity is people, so only a positive whole number is kept; anything else is absent."""

    text = _text(value)
    if not text:
        return None
    try:
        number = int(float(text))
    except ValueError:
        return None
    return number if number > 0 else None


def _name_disagrees(claimed: str, actual: str) -> bool:
    return bool(claimed and actual and claimed not in actual and actual not in claimed)


def _boundary_collection(session: Session) -> tuple[DatasetVersion, list[Boundary]]:
    version = session.scalar(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Dataset.type == "boundary", Dataset.owner_kind == "platform")
        .order_by(DatasetVersion.created_at.desc())
        .limit(1)
    )
    if version is None:
        raise ShelterImportError(
            "Import the platform district boundaries before evacuation centres"
        )
    boundaries = session.scalars(
        select(Boundary).where(
            Boundary.collection_version_id == version.id,
            Boundary.admin_level == "district",
        )
    ).all()
    if not boundaries:
        raise ShelterImportError("The platform district-boundary version has no materialized areas")
    return version, list(boundaries)


def _assign_districts(
    records: tuple[ShelterSourceRecord, ...], boundaries: list[Boundary]
) -> tuple[list[AssignedShelter], int, list[dict[str, str]]]:
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    polygons = [shape(boundary.geom) for boundary in boundaries]
    tree = STRtree(polygons)
    assigned: list[AssignedShelter] = []
    outside = 0
    examples: list[dict[str, str]] = []
    for item in records:
        holder: int | None = None
        for candidate in tree.query(item.point):
            position = int(candidate)
            if polygons[position].covers(item.point):
                holder = position
                break
        if holder is None:
            outside += 1
            continue
        boundary = boundaries[holder]
        actual_district = boundary.name_th or boundary.name
        actual_province = boundary.province_name_th or boundary.province_name or ""
        mismatch = _name_disagrees(item.claimed_district, actual_district)
        if mismatch and len(examples) < MAX_MISMATCH_EXAMPLES:
            examples.append(
                {
                    "name": item.name,
                    "claims": item.claimed_district,
                    "sits_in": actual_district,
                }
            )
        assigned.append(
            AssignedShelter(
                source=item,
                boundary_id=boundary.id,
                admin_code=boundary.admin_code,
                actual_district=actual_district,
                actual_province=actual_province,
                name_mismatch=mismatch,
            )
        )
    return assigned, outside, examples


def shelter_labels(records: list[AssignedShelter]):
    """Label every centre uniquely inside the district its geometry actually falls in.

    The claimed district is not used here: a centre that claims one district and sits in
    another is still labelled where a planner will look for it.
    """

    return compose_labels(
        [
            ShelterLabelInput(
                source_index=item.source.source_index,
                facility_name=item.source.name,
                supporting_unit=item.source.supporting_unit,
                village=item.source.village,
                district_key=item.admin_code,
            )
            for item in records
        ]
    )


def _materialize_shelters(records: list[AssignedShelter]):
    labels, _ = shelter_labels(records)

    def materialize(session: Session, version_id: UUID) -> None:
        rows = [
            Feature(
                id=uuid5(
                    NAMESPACE_URL,
                    f"grp:shelter:{version_id}:{item.source.source_index}",
                ),
                dataset_version_id=version_id,
                boundary_id=item.boundary_id,
                name=labels[item.source.source_index],
                lon=item.source.lon,
                lat=item.source.lat,
                # From the delivered name, not the composed label: the label may carry a village
                # qualifier or fall back to a number, neither of which names the kind of place.
                facility_type=classify_facility(item.source.name),
                attributes={
                    "admin_code": item.admin_code,
                    "source_name": item.source.name,
                    "capacity": item.source.capacity,
                    "supporting_unit": item.source.supporting_unit,
                    "subdistrict": item.source.subdistrict,
                    "village": item.source.village,
                    "claimed_district": item.source.claimed_district,
                    "claimed_province": item.source.claimed_province,
                    "district_name_mismatch": item.name_mismatch,
                },
            )
            for item in records
        ]
        session.add_all(rows)
        session.flush()
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text(
                    "UPDATE feature SET geom_postgis = "
                    "ST_SetSRID(ST_MakePoint(lon, lat), 4326) "
                    "WHERE dataset_version_id = :version_id"
                ),
                {"version_id": version_id},
            )

    return materialize


def process_shelter_import(
    session: Session,
    storage: Storage,
    source_root: Path,
    claim: ImportClaim,
    *,
    lease_minutes: int,
) -> UUID | None:
    """Assign points by geometry, report name conflicts and atomically publish one version."""

    job = session.scalar(select(DataImportJob).where(DataImportJob.id == claim.import_id))
    if job is None or job.category != "evacuation_centers":
        raise ShelterImportError("Import job does not reference the accepted shelter source")
    if job.source_mode == "source_folder":
        if job.source_ref != SHELTER_SOURCE_REF:
            raise ShelterImportError("Import job does not reference the accepted shelter source")
    elif job.source_mode == "browser_upload":
        expected = (
            f"quarantine/browser-uploads/{job.id}/source/"
            f"{SHELTER_SOURCE_REF}"
        )
        if job.source_ref != expected or job.hub_id is not None:
            raise ShelterImportError("Browser upload does not reference its own quarantine area")
    else:
        raise ShelterImportError("Import source mode is not supported")
    collection = validate_shelter_collection(source_root, job.source_ref)
    boundary_version, boundaries = _boundary_collection(session)
    assigned, outside, examples = _assign_districts(collection.records, boundaries)
    _, label_report = shelter_labels(assigned)
    mismatch_count = sum(item.name_mismatch for item in assigned)
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
        dataset_id=PLATFORM_SHELTER_DATASET_ID,
        version_id=version_id,
    )
    published = promote_import_version(
        session,
        claim,
        dataset=DatasetDefinition(
            id=PLATFORM_SHELTER_DATASET_ID,
            hub_id=None,
            type="evacuation_centers",
            owner_kind="platform",
            title="DDPM evacuation centres",
            provider="DDPM via ADPC Data Science delivery",
        ),
        promoted=promoted,
        readiness=DatasetReadiness.TECHNICALLY_VALID,
        importer_version=IMPORTER_VERSION,
        version_metadata={
            "crs": "EPSG:4326",
            "feature_count": len(assigned),
            "source_feature_count": len(collection.records),
            "outside_boundary_count": outside,
            "district_name_mismatch_count": mismatch_count,
            "boundary_version_id": str(boundary_version.id),
            "source_ref": SHELTER_SOURCE_REF,
            "source_mode": job.source_mode,
            "original_filename": job.manifest.get("original_filename"),
            "map_preview": True,
            "shelter_names_confirmed": True,
            "district_field": collection.district_field,
        },
        report={
            "message": (
                "Evacuation centres validated, assigned to districts by geometry and imported."
            ),
            "feature_count": len(assigned),
            "outside_boundary_count": outside,
            "district_name_mismatch_count": mismatch_count,
            "mismatch_examples": examples,
            "district_field": collection.district_field,
            "confirmed_fields": {
                "name": SHELTER_NAME,
                "capacity": SHELTER_CAPACITY,
                "supporting_unit": SHELTER_SUPPORTING_UNIT,
            },
            "labels": {
                "from_source_name": label_report.from_facility_name,
                "from_supporting_unit": label_report.from_supporting_unit,
                "numbered_because_unnamed": label_report.numbered,
                "qualified_by_village": label_report.qualified_by_village,
                "numbered_to_stay_distinct": label_report.unresolved,
            },
            "capacity_missing_count": sum(
                1 for item in assigned if item.source.capacity is None
            ),
        },
        materialize=_materialize_shelters(assigned),
    )
    if published is not None:
        cleanup_import_staging(storage, claim)
    return published
