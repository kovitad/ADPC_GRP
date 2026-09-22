"""Add the approved MVP 1 SIG risk-recipe registry.

Revision ID: 20260922_0012
Revises: 20260921_0011
Create Date: 2026-09-22
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0012"
down_revision: str | None = "20260921_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = op.create_table(
        "risk_recipe",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("missing_data_policy", sa.String(length=32), nullable=False),
        sa.Column("science_owner", sa.String(length=200), nullable=False),
        sa.Column("source_ref", sa.String(length=300), nullable=False),
        sa.Column("change_reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "missing_data_policy IN ('unable_to_assess')",
            name="ck_risk_recipe_missing_data_policy",
        ),
        sa.CheckConstraint("status IN ('approved', 'retired')", name="ck_risk_recipe_status"),
        sa.ForeignKeyConstraint(["approved_by"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", "version", name="uq_risk_recipe_key_version"),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": 1,
                "key": "thailand-flood-risk",
                "version": "sig-current-2026-09-22",
                "weights": {
                    "population": 0.40,
                    "building_density": 0.35,
                    "road_distance": 0.25,
                },
                "missing_data_policy": "unable_to_assess",
                "science_owner": "SIG Thailand risk method owner",
                "source_ref": "SIG configurable Thailand flood-risk recipe",
                "change_reason": (
                    "Product Owner instructed MVP 1 to presume the supplied recipe is approved."
                ),
                "status": "approved",
                "is_active": True,
                "approved_by": None,
                "approved_at": datetime(2026, 9, 22, tzinfo=UTC),
                "created_at": datetime(2026, 9, 22, tzinfo=UTC),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("risk_recipe")
