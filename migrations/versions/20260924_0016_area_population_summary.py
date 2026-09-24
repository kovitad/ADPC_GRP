"""Store village-derived population counts per area at import time.

Revision ID: 20260924_0016
Revises: 20260924_0015
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0016"
down_revision = "20260924_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "area_population_summary",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.Uuid(),
            sa.ForeignKey("dataset_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_code", sa.String(length=64), nullable=False),
        sa.Column("admin_level", sa.String(length=32), nullable=False),
        sa.Column("village_count", sa.Integer(), nullable=False),
        sa.Column("counted_village_count", sa.Integer(), nullable=False),
        sa.Column("excluded_village_count", sa.Integer(), nullable=False),
        sa.Column("male", sa.Integer(), nullable=False),
        sa.Column("female", sa.Integer(), nullable=False),
        sa.Column("total_population", sa.Integer(), nullable=False),
        sa.Column("households", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "dataset_version_id",
            "admin_code",
            "admin_level",
            name="uq_area_population_summary_area",
        ),
        sa.CheckConstraint(
            "admin_level IN ('district', 'subdistrict')", name="ck_area_population_summary_level"
        ),
    )
    op.create_index(
        op.f("ix_area_population_summary_dataset_version_id"),
        "area_population_summary",
        ["dataset_version_id"],
    )
    op.create_index(
        op.f("ix_area_population_summary_admin_code"), "area_population_summary", ["admin_code"]
    )


def downgrade() -> None:
    op.drop_table("area_population_summary")
