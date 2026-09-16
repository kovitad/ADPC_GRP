"""Create access-control and audit tables.

Revision ID: 20260916_0001
Revises:
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260916_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "hub",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'closed')", name="ck_hub_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("display_name", sa.String(length=200)),
        sa.Column("is_platform_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_sign_in_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint("email = lower(email)", name="ck_app_user_email_lower"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_app_user_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "external_identity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("provider_kind", sa.String(length=64), nullable=False),
        sa.Column("verified_email", sa.String(length=320), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_sign_in_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identity_issuer_subject"),
    )
    op.create_index("ix_external_identity_user_id", "external_identity", ["user_id"])
    op.create_table(
        "hub_membership",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hub_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("changed_by", sa.Uuid()),
        *_timestamps(),
        sa.CheckConstraint("role IN ('planner', 'admin')", name="ck_hub_membership_role"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_hub_membership_status"),
        sa.ForeignKeyConstraint(["changed_by"], ["app_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hub_id"], ["hub.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hub_id", "user_id", name="uq_hub_membership_hub_user"),
    )
    op.create_index("ix_hub_membership_hub_id", "hub_membership", ["hub_id"])
    op.create_index("ix_hub_membership_user_id", "hub_membership", ["user_id"])
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("hub_id", sa.Uuid()),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.String(length=500)),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("support_ref", sa.String(length=200)),
        sa.Column("trace_id", sa.String(length=100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "actor_kind IN ('person', 'sig_service', 'system')",
            name="ck_audit_event_actor_kind",
        ),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failed')", name="ck_audit_event_result"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["app_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hub_id"], ["hub.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_event_action", "audit_event", ["action"])


def downgrade() -> None:
    raise RuntimeError("GRP migrations are forward-only; restore a coordinated backup instead")
