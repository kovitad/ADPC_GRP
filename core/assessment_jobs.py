"""Assessment submission rules and background processing (Sections 7.3, 8.1 to 8.5)."""

from __future__ import annotations

import logging
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from core.access_models import (
    AppUser,
    AuditEvent,
    AuditResult,
    Hub,
    HubMembership,
    HubStatus,
    MembershipStatus,
    UserStatus,
)
from core.assessment_models import (
    RETURN_PERIODS,
    Assessment,
    AssessmentFeature,
    Boundary,
    Dataset,
    DatasetVersion,
    Feature,
    Method,
)
from core.data_library_models import DatasetFile
from core.models import AssessmentState
from core.result_rules import count_results, validate_center_results
from core.storage import LocalStorage
from core.validation import canonical_sha256, centers_sha256

logger = logging.getLogger("grp.worker.assessment")
MAX_ATTEMPTS = 3


class SubmitError(Exception):
    """Validation failure before a job exists; `code` is an Appendix D code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SubmitRequest:
    hub_id: UUID
    boundary_id: UUID
    return_period_years: int
    hazard_version_id: UUID
    centers_version_id: UUID
    vulnerability_version_id: UUID | None
    method_key: str
    method_version: str


def features_sha256(session: Session, version_id: UUID) -> str:
    rows = session.scalars(select(Feature).where(Feature.dataset_version_id == version_id)).all()
    return centers_sha256([{"name": f.name, "lon": f.lon, "lat": f.lat} for f in rows])


def boundary_sha256(geometry: dict[str, Any], expected: str) -> str:
    """Reproduce either the synthetic JSON or imported WKB boundary fingerprint."""

    json_digest = canonical_sha256(geometry)
    if json_digest == expected:
        return json_digest
    from shapely import to_wkb
    from shapely.geometry import shape

    return sha256(
        to_wkb(shape(geometry), byte_order=1, output_dimension=2, include_srid=False)
    ).hexdigest()


def _usable_version(
    session: Session, version_id: UUID, expected_type: str, hub_id: UUID
) -> tuple[DatasetVersion, Dataset]:
    row = session.execute(
        select(DatasetVersion, Dataset)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(DatasetVersion.id == version_id)
    ).first()
    if row is None:
        raise SubmitError("INPUT_VERSION_MISSING")
    version, dataset = row
    if dataset.type != expected_type or (dataset.hub_id not in (None, hub_id)):
        raise SubmitError("INPUT_VERSION_MISSING")
    return version, dataset


def pin_inputs(session: Session, request: SubmitRequest, *, allow_draft_methods: bool) -> dict:
    """Section 8.2 steps 3 to 5, in order. Raises SubmitError; creates nothing."""

    boundary = session.get(Boundary, request.boundary_id)
    if boundary is None or not boundary.is_supported:
        raise SubmitError("UNSUPPORTED_AREA")
    if request.return_period_years not in RETURN_PERIODS:
        raise SubmitError("UNSUPPORTED_SCENARIO")
    hazard, hazard_dataset = _usable_version(
        session, request.hazard_version_id, "hazard", request.hub_id
    )
    if hazard.return_period_years != request.return_period_years or not hazard.is_current:
        raise SubmitError("UNSUPPORTED_SCENARIO")
    centers, centers_dataset = _usable_version(
        session, request.centers_version_id, "evacuation_centers", request.hub_id
    )
    if request.vulnerability_version_id is not None:
        raise SubmitError("VALIDATION_FAILED", "Vulnerability is not available until method 2.")
    method = session.scalar(
        select(Method).where(
            Method.key == request.method_key, Method.version == request.method_version
        )
    )
    if method is None or method.status == "retired":
        raise SubmitError("VALIDATION_FAILED", "The method is not available.")
    if method.status != "approved" and not allow_draft_methods:
        raise SubmitError("VALIDATION_FAILED", "The method is not approved.")
    hazard_files = session.scalars(
        select(DatasetFile)
        .where(
            DatasetFile.dataset_version_id == hazard.id,
            DatasetFile.role.like("working_cog_%"),
        )
        .order_by(DatasetFile.role)
    ).all()
    return {
        "boundary": {
            "id": str(boundary.id),
            "name": boundary.name,
            "admin_code": boundary.admin_code,
            "admin_level": boundary.admin_level,
            "source": boundary.source,
            "edition": boundary.edition,
            "geometry_sha256": boundary.geometry_sha256,
        },
        "scenario": {"hazard": "flood", "return_period_years": request.return_period_years},
        "hazard": {
            "version_id": str(hazard.id),
            "sha256": hazard.sha256,
            "provider": hazard_dataset.provider,
            "title": hazard_dataset.title,
            "edition": hazard.meta.get("edition"),
            "files": [
                {
                    "role": item.role,
                    "storage_key": item.storage_key,
                    "sha256": item.sha256,
                }
                for item in hazard_files
            ],
        },
        "evacuation_centers": {
            "version_id": str(centers.id),
            "sha256": centers.sha256,
            "provider": centers_dataset.provider,
            "title": centers_dataset.title,
            "owner_kind": centers_dataset.owner_kind,
            "features_sha256": features_sha256(session, centers.id),
        },
        "vulnerability": None,
        "method": {
            "id": str(method.id),
            "key": method.key,
            "version": method.version,
            "status": method.status,
        },
    }


def _audit(session: Session, assessment: Assessment, action: str, result: str,
           value: dict | None = None, actor_user_id: UUID | None = None) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            actor_kind="person" if actor_user_id else "system",
            hub_id=assessment.hub_id,
            action=action,
            target_type="assessment",
            target_id=str(assessment.id),
            new_value=value,
            result=result,
            support_ref=assessment.support_ref,
        )
    )


def claim_next_job(session: Session, *, lease_minutes: int, now: datetime | None = None):
    """Claim one queued job (or a running job whose lease expired) with SKIP LOCKED."""

    now = now or datetime.now(UTC)
    assessment = session.scalar(
        select(Assessment)
        .where(
            or_(
                Assessment.state == AssessmentState.QUEUED,
                (Assessment.state == AssessmentState.RUNNING) & (Assessment.lease_until < now),
            )
        )
        .order_by(Assessment.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if assessment is None:
        return None
    assessment.state = AssessmentState.RUNNING
    assessment.lease_until = now + timedelta(minutes=lease_minutes)
    assessment.attempt += 1
    assessment.started_at = assessment.started_at or now
    session.commit()
    return assessment.id


def _fail(session: Session, assessment: Assessment, code: str, detail: str) -> None:
    assessment.state = AssessmentState.FAILED
    assessment.error_code = code
    assessment.lease_until = None
    assessment.completed_at = datetime.now(UTC)
    _audit(session, assessment, "assessment_failed", AuditResult.FAILED,
           {"error_code": code, "detail": detail})
    session.commit()
    logger.warning("Assessment %s failed: %s (%s)", assessment.id, code, assessment.support_ref)


def _submitter_still_allowed(session: Session, assessment: Assessment) -> bool:
    user = session.get(AppUser, assessment.submitted_by)
    if user is None or user.status != UserStatus.ACTIVE:
        return False
    return session.scalar(
        select(HubMembership.id)
        .join(Hub, Hub.id == HubMembership.hub_id)
        .where(
            HubMembership.user_id == user.id,
            HubMembership.hub_id == assessment.hub_id,
            HubMembership.status == MembershipStatus.ACTIVE,
            Hub.status == HubStatus.ACTIVE,
        )
    ) is not None


def process_job(session: Session, storage: LocalStorage, assessment_id: UUID) -> str:
    """Run one claimed job to a final state. Returns the resulting state."""

    # GIS libraries load only in the worker; the API never imports them (AD-03).
    from core.gis import (
        CenterInput,
        MethodInputError,
        run_center_flood_overlay,
        run_center_flood_overlay_tiles,
    )

    assessment = session.get(Assessment, assessment_id)
    if assessment is None or assessment.state != AssessmentState.RUNNING:
        return assessment.state if assessment else "missing"
    pins: dict[str, Any] = assessment.inputs

    if not _submitter_still_allowed(session, assessment):
        assessment.state = AssessmentState.CANCELLED
        assessment.error_code = "ACCESS_NOT_AUTHORIZED"
        assessment.lease_until = None
        assessment.completed_at = datetime.now(UTC)
        _audit(session, assessment, "assessment_cancelled", AuditResult.DENIED,
               {"reason": "access_removed"})
        session.commit()
        return assessment.state

    try:
        boundary = session.get(Boundary, UUID(pins["boundary"]["id"]))
        hazard = session.get(DatasetVersion, UUID(pins["hazard"]["version_id"]))
        centers_version = session.get(
            DatasetVersion, UUID(pins["evacuation_centers"]["version_id"])
        )
        method = session.get(Method, UUID(pins["method"]["id"]))
        if None in (boundary, hazard, centers_version, method) or not hazard.storage_key:
            _fail(session, assessment, "INPUT_VERSION_MISSING", "pinned input no longer exists")
            return assessment.state
        if not storage.exists(hazard.storage_key):
            _fail(session, assessment, "INPUT_VERSION_MISSING", "hazard file missing")
            return assessment.state
        pinned_hazard_files = pins["hazard"].get("files", [])
        checks = {
            "boundary": boundary_sha256(
                boundary.geom, pins["boundary"]["geometry_sha256"]
            )
            == pins["boundary"]["geometry_sha256"],
            "hazard_record": hazard.sha256 == pins["hazard"]["sha256"],
            "centers": features_sha256(session, centers_version.id)
            == pins["evacuation_centers"].get(
                "features_sha256", pins["evacuation_centers"]["sha256"]
            ),
        }
        if not pinned_hazard_files:
            checks["hazard_file"] = (
                storage.sha256(hazard.storage_key) == pins["hazard"]["sha256"]
            )
        for item in pinned_hazard_files:
            key = str(item["storage_key"])
            checks[f"hazard_tile_{item['role']}"] = (
                storage.exists(key) and storage.sha256(key) == item["sha256"]
            )
        if not all(checks.values()):
            failed = sorted(name for name, ok in checks.items() if not ok)
            _fail(session, assessment, "INPUT_FINGERPRINT_MISMATCH", ",".join(failed))
            return assessment.state

        features = session.scalars(
            select(Feature).where(Feature.dataset_version_id == centers_version.id)
        ).all()
        centers = [CenterInput(f.id, f.name, f.lon, f.lat) for f in features]
        if pinned_hazard_files:
            with ExitStack() as stack:
                rasters = [
                    stack.enter_context(storage.open_window(str(item["storage_key"])))
                    for item in pinned_hazard_files
                ]
                in_scope, results = run_center_flood_overlay_tiles(
                    boundary.geom, centers, rasters
                )
        else:
            with storage.open_window(hazard.storage_key) as raster:
                in_scope, results = run_center_flood_overlay(boundary.geom, centers, raster)
    except MethodInputError as error:
        _fail(session, assessment, "RESULT_RULE_FAILED", str(error))
        return assessment.state
    except (OperationalError, OSError) as error:
        session.rollback()
        return _retry_or_fail(session, assessment_id, error)

    rows = [(r.feature_id, str(r.status), r.reason_code, r.flood_depth_m) for r in results]
    errors = validate_center_results([c.feature_id for c in in_scope], rows, method.reason_codes)
    if errors:
        _fail(session, assessment, "RESULT_RULE_FAILED", ",".join(errors))
        return assessment.state

    counts = count_results(len(in_scope), (row[1] for row in rows))
    # Re-read under lock: a cancel that landed while GIS ran wins (best effort, Section 8.1).
    locked = session.scalar(
        select(Assessment).where(Assessment.id == assessment_id).with_for_update()
    )
    session.refresh(locked)
    if locked.state != AssessmentState.RUNNING:
        session.rollback()
        return locked.state
    session.add_all(
        AssessmentFeature(
            assessment_id=assessment_id,
            feature_id=feature_id,
            status=status,
            reason_code=reason,
            flood_depth_m=depth,
        )
        for feature_id, status, reason, depth in rows
    )
    locked.summary = {
        "in_scope": counts.in_scope,
        "potentially_exposed": counts.potentially_exposed,
        "not_exposed_under_scenario": counts.not_exposed_under_scenario,
        "unable_to_assess": counts.unable_to_assess,
        "excluded_outside_boundary": len(centers) - len(in_scope),
    }
    locked.state = AssessmentState.SUCCEEDED
    locked.lease_until = None
    locked.completed_at = datetime.now(UTC)
    _audit(session, locked, "assessment_succeeded", AuditResult.SUCCESS, locked.summary)
    session.commit()
    return locked.state


def _retry_or_fail(session: Session, assessment_id: UUID, error: Exception) -> str:
    assessment = session.get(Assessment, assessment_id)
    if assessment.attempt >= MAX_ATTEMPTS:
        _fail(session, assessment, "RESULT_RULE_FAILED", f"temporary error: {type(error).__name__}")
        return assessment.state
    assessment.state = AssessmentState.QUEUED
    assessment.lease_until = None
    session.commit()
    logger.warning("Assessment %s re-queued after %s", assessment_id, type(error).__name__)
    return assessment.state


def cancel_queued_jobs_for_member(session: Session, *, user_id: UUID, hub_id: UUID) -> int:
    """Section 9.5: turning access off cancels that person's queued jobs in that Hub."""

    jobs = session.scalars(
        select(Assessment).where(
            Assessment.submitted_by == user_id,
            Assessment.hub_id == hub_id,
            Assessment.state == AssessmentState.QUEUED,
        )
    ).all()
    for job in jobs:
        job.state = AssessmentState.CANCELLED
        job.error_code = "ACCESS_NOT_AUTHORIZED"
        job.completed_at = datetime.now(UTC)
        _audit(session, job, "assessment_cancelled", AuditResult.SUCCESS,
               {"reason": "access_turned_off"})
    return len(jobs)
