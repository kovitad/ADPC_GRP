"""Reference data and assessment tables (GRP-ARC-001 Section 12, Appendix C).

Geometry is stored as GeoJSON with a SHA-256 fingerprint so the same code runs on SQLite
tests and PostgreSQL. Moving to PostGIS geometry columns is a follow-up (see handover).
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.access_models import JSON_VALUE, utc_now, uuid7
from core.db import Base

RETURN_PERIODS = (10, 20, 50, 75, 100, 200, 500)


class DatasetType(StrEnum):
    HAZARD = "hazard"
    EVACUATION_CENTERS = "evacuation_centers"
    VULNERABILITY = "vulnerability"


class SharingState(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    SIG_UNAVAILABLE = "sig_unavailable"
    RECEIPT_ISSUED = "receipt_issued"
    UNSHARED = "unshared"


def _created() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class Boundary(Base):
    __tablename__ = "boundary"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    admin_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    admin_level: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    geom: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    edition: Mapped[str] = mapped_column(String(100), nullable=False)
    geometry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_supported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _created()


class Dataset(Base):
    __tablename__ = "dataset"
    __table_args__ = (
        CheckConstraint(
            "type IN ('hazard', 'evacuation_centers', 'vulnerability')", name="ck_dataset_type"
        ),
        CheckConstraint("owner_kind IN ('platform', 'hub_local')", name="ck_dataset_owner"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    hub_id: Mapped[UUID | None] = mapped_column(ForeignKey("hub.id", ondelete="RESTRICT"))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created()


class DatasetVersion(Base):
    """Locked copy of a dataset. Never updated; a replacement moves is_current."""

    __tablename__ = "dataset_version"
    __table_args__ = (
        CheckConstraint(
            "return_period_years IS NULL OR return_period_years IN (10, 20, 50, 75, 100, 200, 500)",
            name="ck_dataset_version_return_period",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    storage_key: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    return_period_years: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON_VALUE, default=dict, nullable=False
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    accepted_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = _created()


class Feature(Base):
    __tablename__ = "feature"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    attributes: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, default=dict, nullable=False)


class Method(Base):
    __tablename__ = "method"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_method_key_version"),
        CheckConstraint("status IN ('draft', 'approved', 'retired')", name="ck_method_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = _created()


class Assessment(Base):
    __tablename__ = "assessment"
    __table_args__ = (
        UniqueConstraint(
            "submitted_by", "hub_id", "idempotency_key", name="uq_assessment_idempotency"
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_assessment_state",
        ),
        CheckConstraint(
            "sharing_state IN ('private', 'shared', 'sig_unavailable', 'receipt_issued', "
            "'unshared')",
            name="ck_assessment_sharing_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    hub_id: Mapped[UUID] = mapped_column(
        ForeignKey("hub.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    submitted_by: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    boundary_id: Mapped[UUID] = mapped_column(
        ForeignKey("boundary.id", ondelete="RESTRICT"), nullable=False
    )
    method_id: Mapped[UUID] = mapped_column(
        ForeignKey("method.id", ondelete="RESTRICT"), nullable=False
    )
    inputs: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    error_code: Mapped[str | None] = mapped_column(String(64))
    sharing_state: Mapped[str] = mapped_column(
        String(24), default=SharingState.PRIVATE, nullable=False
    )
    shared_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="RESTRICT"))
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sig_pack_id: Mapped[str | None] = mapped_column(String(200))
    sig_report_id: Mapped[str | None] = mapped_column(String(200))
    sig_receipt_id: Mapped[str | None] = mapped_column(String(200))
    draft_sha256: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    support_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class AssessmentFeature(Base):
    """One locked row per in-scope center (AD-04). Written once, never updated."""

    __tablename__ = "assessment_feature"
    __table_args__ = (
        CheckConstraint(
            "status IN ('potentially_exposed', 'not_exposed_under_scenario', 'unable_to_assess')",
            name="ck_assessment_feature_status",
        ),
        CheckConstraint(
            "vulnerability_value IS NULL OR "
            "(vulnerability_value >= 0 AND vulnerability_value <= 1)",
            name="ck_assessment_feature_vulnerability",
        ),
    )

    assessment_id: Mapped[UUID] = mapped_column(
        ForeignKey("assessment.id", ondelete="RESTRICT"), primary_key=True
    )
    feature_id: Mapped[UUID] = mapped_column(
        ForeignKey("feature.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    flood_depth_m: Mapped[float | None] = mapped_column(Float)
    vulnerability_value: Mapped[float | None] = mapped_column(Float)
