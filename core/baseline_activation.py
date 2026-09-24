"""Activate the imported Thailand MVP 1 baseline after an explicit approval decision."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_models import AuditEvent, AuditResult
from core.assessment_models import Boundary, DatasetVersion, Method
from core.boundary_import import PLATFORM_BOUNDARY_DATASET_ID
from core.dataset_readiness import DatasetReadiness, require_readiness_transition
from core.gis import METHOD_KEY, METHOD_VERSION, REASON_CODES
from core.hazard_import import PLATFORM_HAZARD_DATASET_ID
from core.shelter_import import PLATFORM_SHELTER_DATASET_ID


class BaselineActivationError(ValueError):
    """The approved baseline cannot be activated without all imported inputs."""


def _latest(
    session: Session, dataset_id: UUID, *, version_id: UUID | None = None
) -> DatasetVersion:
    if version_id is not None:
        version = session.scalar(
            select(DatasetVersion)
            .where(
                DatasetVersion.id == version_id,
                DatasetVersion.dataset_id == dataset_id,
            )
            .with_for_update()
        )
        if version is None:
            raise BaselineActivationError("The requested baseline version does not exist")
        return version
    version = session.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if version is None:
        raise BaselineActivationError("Import boundaries, evacuation centres and RP100 first")
    return version


def _advance_to_ready(version: DatasetVersion) -> None:
    if version.readiness == DatasetReadiness.ASSESSMENT_READY:
        return
    if version.readiness in {
        DatasetReadiness.RECEIVED,
        DatasetReadiness.VALIDATING,
        DatasetReadiness.NEEDS_CORRECTION,
        DatasetReadiness.RETIRED,
    }:
        raise BaselineActivationError(
            f"Dataset {version.id} is not technically eligible for acceptance"
        )
    if version.readiness == DatasetReadiness.TECHNICALLY_VALID:
        version.readiness = require_readiness_transition(
            version.readiness, DatasetReadiness.READY_FOR_ACCEPTANCE
        ).value
    if version.readiness in {
        DatasetReadiness.WAITING_FOR_METHOD,
        DatasetReadiness.READY_FOR_ACCEPTANCE,
    }:
        version.readiness = require_readiness_transition(
            version.readiness, DatasetReadiness.ASSESSMENT_READY
        ).value


def activate_mvp1_baseline(
    session: Session,
    *,
    actor_user_id: UUID,
    actor_email: str,
    boundary_version_id: UUID | None = None,
    centers_version_id: UUID | None = None,
    hazard_version_id: UUID | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Activate the latest imported platform baseline and the approved overlay method.

    No file is changed. The transaction only moves explicit readiness/current/support flags and
    records who made the approval decision.
    """

    now = now or datetime.now(UTC)
    boundary_version = _latest(
        session, PLATFORM_BOUNDARY_DATASET_ID, version_id=boundary_version_id
    )
    centers_version = _latest(
        session, PLATFORM_SHELTER_DATASET_ID, version_id=centers_version_id
    )
    hazard_version = _latest(
        session, PLATFORM_HAZARD_DATASET_ID, version_id=hazard_version_id
    )
    if hazard_version.return_period_years != 100:
        raise BaselineActivationError("The approved MVP 1 hazard must be RP100")

    selected = (boundary_version, centers_version, hazard_version)
    for version in selected:
        _advance_to_ready(version)
        session.execute(
            DatasetVersion.__table__.update()
            .where(
                DatasetVersion.dataset_id == version.dataset_id,
                DatasetVersion.id != version.id,
            )
            .values(is_current=False)
        )
        version.is_current = True
        version.accepted_by = actor_user_id
        version.accepted_at = now

    boundaries = session.scalars(
        select(Boundary).where(Boundary.collection_version_id == boundary_version.id)
    ).all()
    if not boundaries:
        raise BaselineActivationError("The approved boundary version contains no districts")
    session.execute(
        Boundary.__table__.update()
        .where(
            Boundary.collection_version_id.is_not(None),
            Boundary.collection_version_id != boundary_version.id,
        )
        .values(is_supported=False)
    )
    for boundary in boundaries:
        boundary.is_supported = True

    method = session.scalar(
        select(Method).where(Method.key == METHOD_KEY, Method.version == METHOD_VERSION)
    )
    if method is None:
        method = Method(
            key=METHOD_KEY,
            version=METHOD_VERSION,
            reason_codes={
                code: {**rule, "status": str(rule["status"])}
                for code, rule in REASON_CODES.items()
            },
            status="approved",
            approved_by=actor_email,
            approved_at=now,
        )
        session.add(method)
    else:
        method.status = "approved"
        method.approved_by = actor_email
        method.approved_at = now

    payload = {
        "boundary_version_id": str(boundary_version.id),
        "evacuation_centers_version_id": str(centers_version.id),
        "hazard_version_id": str(hazard_version.id),
        "method": {"key": METHOD_KEY, "version": METHOD_VERSION},
        "supported_districts": len(boundaries),
        "no_data_policy": "unable_to_assess",
    }
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            actor_kind="person",
            action="mvp1_baseline_activated",
            target_type="dataset_version",
            target_id=str(hazard_version.id),
            new_value=payload,
            result=AuditResult.SUCCESS,
        )
    )
    session.flush()
    return payload
