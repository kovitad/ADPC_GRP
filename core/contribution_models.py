"""Contributions a Hub member sent to Global Risk from GRP (ADR-0032).

A contribution is a public record on Global Risk once it lands, so its GRP row is durable: a
restart must not lose the Global Risk ID, and a timed-out submit is reconciled from this row
rather than sent again.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.access_models import JSON_VALUE, uuid7
from core.db import Base

# GRP's own states. "submitting" is written before the call leaves, so a crash or timeout
# leaves a row that says a submission may have reached Global Risk.
SUBMITTING = "submitting"
CHECKING = "checking"  # the submit may have landed; GRP is matching it in contribute_status
STAGED = "staged"  # accepted, waiting for a Global Risk reviewer
APPROVED = "approved"  # live for every Global Risk user
DECLINED = "declined"  # the gate named problems; nothing was stored on Global Risk
REJECTED = "rejected"  # a Global Risk reviewer turned it down
WITHDRAWN = "withdrawn"
FAILED = "failed"  # GRP stopped before or while sending; see error_code

CONTRIBUTION_STATES = frozenset(
    {SUBMITTING, CHECKING, STAGED, APPROVED, DECLINED, REJECTED, WITHDRAWN, FAILED}
)
OPEN_STATES = frozenset({SUBMITTING, CHECKING, STAGED})


class SigContribution(Base):
    __tablename__ = "sig_contribution"
    __table_args__ = (Index("ix_sig_contribution_hub_created", "hub_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    hub_id: Mapped[UUID] = mapped_column(ForeignKey("hub.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # layer, dataset or hazard: the name Global Risk will know it by, used to match a record.
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Exactly what was sent to contribute_submit.
    manifest: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default=SUBMITTING)
    contribution_id: Mapped[str | None] = mapped_column(String(64))
    problems: Mapped[list[str] | None] = mapped_column(JSON_VALUE)
    # A safe subset of Global Risk's reply: status, decision note, reviewer, how to test.
    response: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    feature_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
