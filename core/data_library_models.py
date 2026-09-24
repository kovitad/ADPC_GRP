"""Versioned data-library import records (ADR-0008).

Imports are jobs, not web-request GIS work. Files remain quarantined until a worker validates the
whole manifest and atomically promotes one immutable dataset version.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.access_models import JSON_VALUE, utc_now, uuid7
from core.db import Base


class DataImportJob(Base):
    __tablename__ = "data_import_job"
    __table_args__ = (
        CheckConstraint(
            "category IN ('boundary', 'evacuation_centers', 'hazard', "
            "'volunteer_centers', 'early_warning_resources', 'village_locations', "
            "'vulnerability_child', 'vulnerability_elderly', 'vulnerability_disability')",
            name="ck_data_import_category",
        ),
        CheckConstraint(
            "source_mode IN ('source_folder', 'browser_upload')",
            name="ck_data_import_source_mode",
        ),
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_data_import_state",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_data_import_progress"),
        UniqueConstraint("requested_by", "idempotency_key", name="uq_data_import_idempotency"),
        Index("ix_data_import_claim", "state", "lease_until", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    hub_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hub.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    source_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manifest: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    report: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    dataset_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    support_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetFile(Base):
    __tablename__ = "dataset_file"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "role", "storage_key", name="uq_dataset_file_role"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    original_name: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    file_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON_VALUE, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class HubDatasetSelection(Base):
    """Reserved by design and not yet used by any code path.

    The approved data-library design keeps a per-Hub override of which version a category resolves
    to (see docs/adr/0019-reuse-approved-shelter-uploads.md and
    docs/data-library-solution-review.md). MVP 1 activates one release for every Hub through
    is_current and is_supported in core/baseline_activation.py, so nothing reads or writes this
    table yet. Do not add a second activation mechanism beside it, and do not drop it without a new
    ADR: the approved design and its diagrams depend on it.
    """


    __tablename__ = "hub_dataset_selection"
    __table_args__ = (
        UniqueConstraint("hub_id", "category", "scenario_key", name="uq_hub_dataset_selection"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    hub_id: Mapped[UUID] = mapped_column(
        ForeignKey("hub.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    scenario_key: Mapped[str] = mapped_column(
        String(100), default="default", server_default="default", nullable=False
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    selected_by: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class AreaPopulationSummary(Base):
    """Village-derived population counts for one area, computed once at import time.

    A web request must never aggregate 80,397 village points, so one row per area per village
    dataset version is written by the importer and read by a single indexed lookup. The source
    columns are the delivery's undocumented `oct_side*` fields; see
    docs/vulnerable-people-data-proof.md for the evidence that they are male, female, total and
    households, and ADR-0027 for the labelling this obliges. These are registered village
    population counts and are not a vulnerability measure.
    """

    __tablename__ = "area_population_summary"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id",
            "admin_code",
            "admin_level",
            name="uq_area_population_summary_area",
        ),
        CheckConstraint(
            "admin_level IN ('district', 'subdistrict')",
            name="ck_area_population_summary_level",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    admin_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    admin_level: Mapped[str] = mapped_column(String(32), nullable=False)
    village_count: Mapped[int] = mapped_column(Integer, nullable=False)
    counted_village_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_village_count: Mapped[int] = mapped_column(Integer, nullable=False)
    male: Mapped[int] = mapped_column(Integer, nullable=False)
    female: Mapped[int] = mapped_column(Integer, nullable=False)
    total_population: Mapped[int] = mapped_column(Integer, nullable=False)
    households: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
