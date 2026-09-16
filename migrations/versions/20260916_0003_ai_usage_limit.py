"""Add the AI usage limit tables (GRP-ARC-001 Section 10, Appendix C).

Revision ID: 20260916_0003
Revises: 20260916_0002
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260916_0003"
down_revision: str | None = "20260916_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_setting",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_limit_per_person", sa.BigInteger()),
        sa.Column("ai_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("changed_by", sa.Uuid()),
        sa.Column("changed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1", name="ck_ai_usage_setting_single_row"),
        sa.CheckConstraint(
            "token_limit_per_person IS NULL OR "
            "(token_limit_per_person >= 1000 AND token_limit_per_person <= 100000000)",
            name="ck_ai_usage_setting_limit_range",
        ),
        sa.ForeignKeyConstraint(["changed_by"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ai_allowance",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("tokens_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("tokens_reserved", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "reservations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("tokens_used >= 0", name="ck_ai_allowance_used"),
        sa.CheckConstraint("tokens_reserved >= 0", name="ck_ai_allowance_reserved"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "period_month"),
    )
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("hub_id", sa.Uuid()),
        sa.Column("assessment_id", sa.Uuid()),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("channel IN ('web', 'mcp')", name="ck_llm_usage_channel"),
        sa.CheckConstraint(
            "outcome IN ('completed', 'provider_error', 'blocked')", name="ck_llm_usage_outcome"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hub_id"], ["hub.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_llm_usage_user_id", "llm_usage", ["user_id"])
    op.create_index("ix_llm_usage_period_month", "llm_usage", ["period_month"])
    op.execute("INSERT INTO ai_usage_setting (id, ai_enabled) VALUES (1, false)")


def downgrade() -> None:
    raise RuntimeError("GRP migrations are forward-only; restore a coordinated backup instead")
