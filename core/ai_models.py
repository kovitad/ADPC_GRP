from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.access_models import JSON_VALUE, utc_now, uuid7
from core.db import Base


class AiUsageSetting(Base):
    """Single platform-wide AI setting row (Section 10.2); id is always 1."""

    __tablename__ = "ai_usage_setting"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_ai_usage_setting_single_row"),
        CheckConstraint(
            "token_limit_per_person IS NULL OR "
            "(token_limit_per_person >= 1000 AND token_limit_per_person <= 100000000)",
            name="ck_ai_usage_setting_limit_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    token_limit_per_person: Mapped[int | None] = mapped_column(BigInteger)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    changed_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="RESTRICT"))
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiAllowance(Base):
    """Per person, per Bangkok month usage counter (Section 10.3)."""

    __tablename__ = "ai_allowance"
    __table_args__ = (
        CheckConstraint("tokens_used >= 0", name="ck_ai_allowance_used"),
        CheckConstraint("tokens_reserved >= 0", name="ck_ai_allowance_reserved"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), primary_key=True
    )
    period_month: Mapped[date] = mapped_column(Date, primary_key=True)
    tokens_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tokens_reserved: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reservations: Mapped[list[dict[str, object]]] = mapped_column(
        JSON_VALUE, default=list, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class LlmUsage(Base):
    """One row per AI call made by the GRP server; the official usage record (AD-12)."""

    __tablename__ = "llm_usage"
    __table_args__ = (
        CheckConstraint("channel IN ('web', 'mcp')", name="ck_llm_usage_channel"),
        CheckConstraint(
            "outcome IN ('completed', 'provider_error', 'blocked')", name="ck_llm_usage_outcome"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    hub_id: Mapped[UUID | None] = mapped_column(ForeignKey("hub.id", ondelete="RESTRICT"))
    assessment_id: Mapped[UUID | None] = mapped_column()
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
