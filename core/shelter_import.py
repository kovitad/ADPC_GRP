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
from core.import_staging import (
    SourceFile,
    cleanup_import_staging,
    promote_staged_import,
    stage_import_files,
)
from core.storage import Storage

SHELTER_SOURCE_REF = "evacuation_centers/shelters"
SHELTER_STEM = "ddpm_shelters"
REQUIRED_SUFFIXES = (".shp", ".shx", ".dbf", ".prj")
OPTIONAL_SUFFIXES = (".cpg", ".sbn", ".sbx", ".shp.xml")
SHELTER_PROVINCE = "จัง"
REQUIRED_FIELDS = (SHELTER_PROVINCE,)
IMPORTER_VERSION = "grp-shelters/2"
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
    records: list[ShelterSourceRecord] = []
    for index, raw_geometry in enumerate(geometries):
        if raw_geometry is None:
            raise ShelterImportError("Evacuation centre has missing geometry")
        point = from_wkb(raw_geometry)
        if not isinstance(point, Point) or point.is_empty or not point.is_valid:
            raise ShelterImportError("Evacuation-centre collection contains invalid point geometry")
        # DEP-06 has not confirmed either truncated `สถ...` field or `รอง`. Do not
        # infer a planner-facing facility name merely from values that look name-like.
        records.append(
            ShelterSourceRecord(
                source_index=index,
                name=f"Evacuation centre {index + 1}",
                claimed_district=_text(columns[district_field][index]),
                claimed_province=_text(columns[SHELTER_PROVINCE][index]),
                lon=float(point.x),
                lat=float(point.y),
                point=point,
            )
        )
    return ValidatedShelterCollection(tuple(records), source_files, district_field)


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
        select(Boundary).where(Boundary.collection_version_id == version.id)
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


def _materialize_shelters(records: list[AssignedShelter]):
    def materialize(session: Session, version_id: UUID) -> None:
        rows = [
            Feature(
                id=uuid5(
                    NAMESPACE_URL,
                    f"grp:shelter:{version_id}:{item.source.source_index}",
                ),
                dataset_version_id=version_id,
                boundary_id=item.boundary_id,
                name=item.source.name,
                lon=item.source.lon,
                lat=item.source.lat,
                attributes={
                    "admin_code": item.admin_code,
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
            "shelter_names_confirmed": False,
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
            "unconfirmed_fields_excluded": ["สถา", "สถ_1", "รอง"],
        },
        materialize=_materialize_shelters(assigned),
    )
    if published is not None:
        cleanup_import_staging(storage, claim)
    return published
