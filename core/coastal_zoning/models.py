"""Persistent coastal-zoning runs, checkpoints, zones, artifacts, and reviews.

Receipt verdicts are deliberately absent. Callers resolve a stored receipt ID at view time.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.access_models import JSON_VALUE, utc_now, uuid7
from core.db import Base


class ZoningRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    RETIRED = "retired"


class ZoningStepState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ZoningProfile(StrEnum):
    HAZARD = "hazard"
    NO_HAZARD = "no_hazard"


class ZoningScale(StrEnum):
    LOCAL = "local"
    PROVINCE = "province"


class ZoningReviewState(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"


def _created() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class CoastalZoningRun(Base):
    __tablename__ = "coastal_zoning_run"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "hub_id", "idempotency_key", name="uq_coastal_zoning_idempotency"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'failed', 'succeeded', 'cancelled', 'retired')",
            name="ck_coastal_zoning_run_status",
        ),
        CheckConstraint(
            "aoi_source IN ('place', 'drawn', 'upload')",
            name="ck_coastal_zoning_aoi_source",
        ),
        CheckConstraint("profile IN ('hazard', 'no_hazard')", name="ck_coastal_zoning_profile"),
        CheckConstraint("scale IN ('local', 'province')", name="ck_coastal_zoning_scale"),
        CheckConstraint(
            "review_state IN ('draft', 'reviewed')", name="ck_coastal_zoning_review_state"
        ),
        CheckConstraint("attempt >= 0", name="ck_coastal_zoning_attempt"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    hub_id: Mapped[UUID] = mapped_column(
        ForeignKey("hub.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    site_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    aoi_geojson: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    aoi_source: Mapped[str] = mapped_column(String(16), nullable=False)
    aoi_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[str] = mapped_column(String(16), nullable=False)
    scale: Mapped[str] = mapped_column(String(16), nullable=False)
    params: Mapped[list[dict[str, object]]] = mapped_column(JSON_VALUE, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    review_state: Mapped[str] = mapped_column(
        String(16), default=ZoningReviewState.DRAFT, nullable=False
    )
    versions: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    lead: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    error: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    support_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    cancellation_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class CoastalZoningStep(Base):
    __tablename__ = "coastal_zoning_step"
    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_coastal_zoning_step_key"),
        UniqueConstraint("run_id", "sequence", name="uq_coastal_zoning_step_sequence"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'skipped')",
            name="ck_coastal_zoning_step_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_coastal_zoning_step_attempts"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_coastal_zoning_step_duration"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("coastal_zoning_run.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    done: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(String(500))
    detail: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class CoastalZoningZone(Base):
    __tablename__ = "coastal_zoning_zone"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('coastal', 'inland', 'restoration')",
            name="ck_coastal_zoning_zone_kind",
        ),
        CheckConstraint("rank IS NULL OR rank > 0", name="ck_coastal_zoning_zone_rank"),
        CheckConstraint("area_km2 >= 0", name="ck_coastal_zoning_zone_area"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("coastal_zoning_run.id", ondelete="RESTRICT"), primary_key=True
    )
    zone_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    facts: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    pack_id: Mapped[str | None] = mapped_column(String(200))
    receipt_id: Mapped[str | None] = mapped_column(String(200), index=True)
    partner_zone: Mapped[str | None] = mapped_column(String(16))
    partner_km: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = _created()


class CoastalZoningArtifact(Base):
    __tablename__ = "coastal_zoning_artifact"
    __table_args__ = (
        UniqueConstraint("run_id", "kind", name="uq_coastal_zoning_artifact_kind"),
        CheckConstraint("bytes >= 0", name="ck_coastal_zoning_artifact_bytes"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("coastal_zoning_run.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()


class CoastalZoningReviewLog(Base):
    __tablename__ = "coastal_zoning_review_log"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("coastal_zoning_run.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reviewer_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_role: Mapped[str] = mapped_column(String(32), nullable=False)
    field: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[object | None] = mapped_column(JSON_VALUE)
    new_value: Mapped[object | None] = mapped_column(JSON_VALUE)
    support_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = _created()
