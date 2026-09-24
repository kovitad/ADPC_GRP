"""Idempotent orchestration helpers for the supported Thailand baseline slice.

The GIS work remains in the worker.  This module inventories the read-only delivery, derives a
stable identity from its bytes, queues one dependency-aware import at a time and reports the
release state used by both the CLI and Data Library.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_models import AppUser, Hub
from core.assessment_models import DatasetVersion
from core.boundary_import import PLATFORM_BOUNDARY_DATASET_ID
from core.data_import_jobs import ImportRequest, request_import
from core.data_library_models import DataImportJob
from core.hazard_import import (
    EXPECTED_TILE_COUNT,
    HAZARD_SOURCE_REF,
    PLATFORM_HAZARD_DATASET_ID,
)
from core.hazard_import import (
    IMPORTER_VERSION as HAZARD_IMPORTER_VERSION,
)
from core.models import AssessmentState
from core.shelter_import import (
    IMPORTER_VERSION as SHELTER_IMPORTER_VERSION,
)
from core.shelter_import import (
    OPTIONAL_SUFFIXES as SHELTER_OPTIONAL_SUFFIXES,
)
from core.shelter_import import (
    PLATFORM_SHELTER_DATASET_ID,
    SHELTER_SOURCE_REF,
    SHELTER_STEM,
)
from core.shelter_import import (
    REQUIRED_SUFFIXES as SHELTER_REQUIRED_SUFFIXES,
)
from core.thailand_full_import import (
    HIERARCHY_IMPORTER_VERSION,
    HIERARCHY_SOURCE_REF,
    POINT_IMPORTER_VERSION,
    POINT_PROFILES,
    VULNERABILITY_IMPORTER_VERSION,
    VULNERABILITY_PROFILES,
    VULNERABILITY_SOURCE_REF,
    full_dataset_ids,
)
from core.validation import canonical_sha256, sha256_file

BOOTSTRAP_RELEASE = "thailand-mvp1-complete-v2"
TERMINAL_STATES = frozenset(
    {AssessmentState.SUCCEEDED, AssessmentState.FAILED, AssessmentState.CANCELLED}
)


class ThailandBootstrapError(ValueError):
    """The source bundle, actor or an import result is not safe to activate."""


@dataclass(frozen=True)
class BootstrapSource:
    category: str
    source_ref: str
    dataset_id: UUID
    importer_version: str
    files: tuple[Path, ...]


@dataclass(frozen=True)
class PreparedBootstrapSource:
    source: BootstrapSource
    fingerprint: str
    total_bytes: int
    manifest: dict[str, object]


def _shapefile_paths(
    root: Path,
    source_ref: str,
    stem: str,
    required: tuple[str, ...],
    optional: tuple[str, ...],
) -> tuple[Path, ...]:
    folder = root / source_ref
    missing = [suffix for suffix in required if not (folder / f"{stem}{suffix}").is_file()]
    if missing:
        joined = ", ".join(f"{stem}{suffix}" for suffix in missing)
        raise ThailandBootstrapError(f"{source_ref} is missing: {joined}")
    return tuple(
        folder / f"{stem}{suffix}"
        for suffix in (*required, *optional)
        if (folder / f"{stem}{suffix}").is_file()
    )


def discover_supported_sources(root: Path) -> tuple[BootstrapSource, ...]:
    """Locate every collection in the approved Thailand Hub baseline."""

    root = root.resolve()
    hierarchy_root = root / HIERARCHY_SOURCE_REF
    boundary_files = tuple(
        sorted(
            (
                path
                for path in hierarchy_root.rglob("*")
                if path.is_file() and "village" not in path.relative_to(hierarchy_root).parts
            ),
            key=lambda path: path.as_posix(),
        )
    )
    if not boundary_files:
        raise ThailandBootstrapError("administrative_boundary is missing")
    shelter_files = _shapefile_paths(
        root,
        SHELTER_SOURCE_REF,
        SHELTER_STEM,
        SHELTER_REQUIRED_SUFFIXES,
        SHELTER_OPTIONAL_SUFFIXES,
    )
    hazard_folder = root / HAZARD_SOURCE_REF
    hazard_files = tuple(sorted(hazard_folder.glob("*.tif"), key=lambda item: item.name))
    if len(hazard_files) != EXPECTED_TILE_COUNT:
        raise ThailandBootstrapError(
            f"{HAZARD_SOURCE_REF} must contain exactly {EXPECTED_TILE_COUNT} GeoTIFF files"
        )
    supporting = tuple(
        BootstrapSource(
            category,
            str(profile["source_ref"]),
            profile["dataset_id"],
            POINT_IMPORTER_VERSION,
            _shapefile_paths(
                root,
                str(profile["source_ref"]),
                str(profile["stem"]),
                (".shp", ".shx", ".dbf", ".prj"),
                (".cpg", ".sbn", ".sbx", ".shp.xml"),
            ),
        )
        for category, profile in POINT_PROFILES.items()
    )
    vulnerability = tuple(
        BootstrapSource(
            category,
            VULNERABILITY_SOURCE_REF,
            profile["dataset_id"],
            VULNERABILITY_IMPORTER_VERSION,
            (root / VULNERABILITY_SOURCE_REF / str(profile["filename"]),),
        )
        for category, profile in VULNERABILITY_PROFILES.items()
    )
    missing_rasters = [str(item.files[0]) for item in vulnerability if not item.files[0].is_file()]
    if missing_rasters:
        raise ThailandBootstrapError("Vulnerability delivery is incomplete")
    return (
        BootstrapSource(
            "boundary",
            HIERARCHY_SOURCE_REF,
            PLATFORM_BOUNDARY_DATASET_ID,
            HIERARCHY_IMPORTER_VERSION,
            boundary_files,
        ),
        BootstrapSource(
            "evacuation_centers",
            SHELTER_SOURCE_REF,
            PLATFORM_SHELTER_DATASET_ID,
            SHELTER_IMPORTER_VERSION,
            shelter_files,
        ),
        *supporting,
        BootstrapSource(
            "hazard",
            HAZARD_SOURCE_REF,
            PLATFORM_HAZARD_DATASET_ID,
            HAZARD_IMPORTER_VERSION,
            hazard_files,
        ),
        *vulnerability,
    )


def prepare_source(root: Path, source: BootstrapSource) -> PreparedBootstrapSource:
    """Hash one approved source collection and return its secret-free runtime manifest."""

    entries: list[dict[str, object]] = []
    total_bytes = 0
    for path in source.files:
        stat = path.stat()
        total_bytes += stat.st_size
        entries.append(
            {
                "path": path.resolve().relative_to(root.resolve()).as_posix(),
                "size_bytes": stat.st_size,
                "sha256": sha256_file(path),
            }
        )
    fingerprint = canonical_sha256(entries)
    manifest: dict[str, object] = {
        "bootstrap_release": BOOTSTRAP_RELEASE,
        "category": source.category,
        "source_ref": source.source_ref,
        "source_sha256": fingerprint,
        "importer_version": source.importer_version,
        "files": entries,
        "total_bytes": total_bytes,
    }
    return PreparedBootstrapSource(source, fingerprint, total_bytes, manifest)


def queue_prepared_source(
    session: Session,
    *,
    actor_user_id: UUID,
    prepared: PreparedBootstrapSource,
) -> ImportRequest:
    """Queue exactly once for this actor, category, importer and source bytes."""

    prior_jobs = session.scalars(
        select(DataImportJob)
        .where(DataImportJob.category == prepared.source.category)
        .order_by(DataImportJob.created_at.desc())
    ).all()
    for job in prior_jobs:
        if (
            job.manifest.get("source_sha256") == prepared.fingerprint
            and job.manifest.get("importer_version") == prepared.source.importer_version
        ):
            return ImportRequest(job.id, job.state, True)

    key = (
        f"th-bootstrap-{prepared.source.category}-"
        f"{prepared.source.importer_version}-{prepared.fingerprint[:24]}"
    )
    return request_import(
        session,
        hub_id=None,
        requested_by=actor_user_id,
        idempotency_key=key,
        category=prepared.source.category,
        source_ref=prepared.source.source_ref,
        support_ref=f"TH-{prepared.fingerprint[:12].upper()}",
        manifest=prepared.manifest,
    )


def require_bootstrap_context(session: Session, *, actor_email: str, hub_code: str) -> AppUser:
    """Require an active Platform Admin and the target active Hub before any work is queued."""

    normalized_email = actor_email.strip().lower()
    actor = session.scalar(select(AppUser).where(AppUser.email == normalized_email))
    if actor is None or not actor.is_platform_admin or actor.status != "active":
        raise ThailandBootstrapError("The bootstrap actor must be an active Platform Admin")
    hub = session.scalar(select(Hub).where(Hub.code == hub_code.strip().lower()))
    if hub is None or hub.status != "active":
        raise ThailandBootstrapError("Create the active target Hub before installing its data")
    return actor


def import_result(session: Session, import_id: UUID) -> DataImportJob:
    job = session.get(DataImportJob, import_id)
    if job is None:
        raise ThailandBootstrapError("A queued Thailand import no longer exists")
    return job


def bootstrap_library_status(session: Session, root: Path) -> dict[str, object]:
    """Return a cheap, non-hashing status for the Admin Data Library."""

    categories: dict[str, dict[str, object]] = {}
    supplemental_ids = full_dataset_ids()
    specs = (
        ("boundary", HIERARCHY_SOURCE_REF, PLATFORM_BOUNDARY_DATASET_ID),
        ("evacuation_centers", SHELTER_SOURCE_REF, PLATFORM_SHELTER_DATASET_ID),
        *(
            (category, str(profile["source_ref"]), supplemental_ids[category])
            for category, profile in POINT_PROFILES.items()
        ),
        ("hazard", HAZARD_SOURCE_REF, PLATFORM_HAZARD_DATASET_ID),
        *(
            (category, VULNERABILITY_SOURCE_REF, supplemental_ids[category])
            for category in VULNERABILITY_PROFILES
        ),
    )
    for category, source_ref, dataset_id in specs:
        current = session.scalar(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetVersion.is_current.is_(True),
            )
        )
        categories[category] = {
            "source_present": (root / source_ref).is_dir(),
            "active": bool(current),
            "version_id": str(current.id) if current else None,
        }
    return {
        "release": BOOTSTRAP_RELEASE,
        "ready": all(bool(item["active"]) for item in categories.values()),
        "categories": categories,
        "scope_note": (
            "This release activates the administrative hierarchy, DDPM shelters, volunteer and "
            "warning resources, village locations, RP100, and three separate display-only "
            "vulnerability indicators."
        ),
    }
