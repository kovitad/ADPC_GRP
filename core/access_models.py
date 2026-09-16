from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base

JSON_VALUE = JSON().with_variant(JSONB(), "postgresql")


def uuid7() -> UUID:
    """Generate an RFC 9562 UUIDv7 using millisecond time and secure randomness."""

    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return UUID(int=value)


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class HubStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class MembershipRole(StrEnum):
    PLANNER = "planner"
    ADMIN = "admin"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class AuditResult(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


class Hub(Base):
    __tablename__ = "hub"
    __table_args__ = (CheckConstraint("status IN ('active', 'closed')", name="ck_hub_status"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=HubStatus.ACTIVE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_app_user_email_lower"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_app_user_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=UserStatus.ACTIVE, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sessions_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class ExternalIdentity(Base):
    __tablename__ = "external_identity"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_email: Mapped[str] = mapped_column(String(320), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    last_sign_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON_VALUE, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class HubMembership(Base):
    __tablename__ = "hub_membership"
    __table_args__ = (
        UniqueConstraint("hub_id", "user_id", name="uq_hub_membership_hub_user"),
        CheckConstraint("role IN ('planner', 'admin')", name="ck_hub_membership_role"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_hub_membership_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    hub_id: Mapped[UUID] = mapped_column(
        ForeignKey("hub.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=MembershipStatus.ACTIVE, nullable=False)
    changed_by: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('person', 'sig_service', 'system')",
            name="ck_audit_event_actor_kind",
        ),
        CheckConstraint("result IN ('success', 'denied', 'failed')", name="ck_audit_event_result"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="RESTRICT")
    )
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    hub_id: Mapped[UUID | None] = mapped_column(ForeignKey("hub.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(500))
    old_value: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    new_value: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    support_ref: Mapped[str | None] = mapped_column(String(200))
    trace_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


# Register the AI usage tables on the shared metadata (imported last to avoid a cycle).
from core import ai_models as _ai_models  # noqa: E402, F401
from core import assessment_models as _assessment_models  # noqa: E402, F401
