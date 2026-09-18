"""Cached data-inspection reports (ADR-0006).

An inspection reads unapproved source files and describes them. It is never an assessment and
its numbers are never a result: nothing here may reach a planner, a brief or SIG. The cache is
keyed by a fingerprint of every file in scope, so a report can only be shown while the files it
describes are unchanged.
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.access_models import JSON_VALUE, utc_now, uuid7
from core.db import Base


class DatasetInspection(Base):
    __tablename__ = "dataset_inspection"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_dataset_inspection_state",
        ),
        Index("ix_dataset_inspection_cache", "folder", "fingerprint", "state"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    # An inspection describes files on the server, not Hub data, so a Platform Admin with no
    # Hub may run one. It is recorded against a Hub only when the person acts for one.
    hub_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hub.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    # Folder relative to the configured source root; the empty string is the root itself.
    folder: Mapped[str] = mapped_column(String(400), nullable=False)
    # Fingerprint of every file in scope: the cache key (see core/data_folder.py).
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    error_code: Mapped[str | None] = mapped_column(String(64))
    support_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
