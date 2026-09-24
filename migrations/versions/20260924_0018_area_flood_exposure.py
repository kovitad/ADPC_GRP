"""Store village-derived flood exposure per area, per hazard scenario.

Revision ID: 20260924_0018
Revises: 20260924_0017
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0018"
down_revision = "20260924_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "area_flood_exposure",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "hazard_version_id",
            sa.Uuid(),
            sa.ForeignKey("dataset_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "village_version_id",
            sa.Uuid(),
            sa.ForeignKey("dataset_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("return_period_years", sa.Integer(), nullable=False),
        sa.Column("admin_code", sa.String(length=64), nullable=False),
        sa.Column("admin_level", sa.String(length=32), nullable=False),
        sa.Column("village_count", sa.Integer(), nullable=False),
        sa.Column("measured_village_count", sa.Integer(), nullable=False),
        sa.Column("no_data_village_count", sa.Integer(), nullable=False),
        sa.Column("villages_in_zone", sa.Integer(), nullable=False),
        sa.Column("people_in_zone", sa.Integer(), nullable=False),
        sa.Column("households_in_zone", sa.Integer(), nullable=False),
        sa.Column("villages_in_zone_without_population", sa.Integer(), nullable=False),
        sa.Column("depth_bands", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint(
            "hazard_version_id",
            "village_version_id",
            "admin_code",
            "admin_level",
            name="uq_area_flood_exposure_area",
        ),
        sa.CheckConstraint(
            "admin_level IN ('district', 'subdistrict')",
            name="ck_area_flood_exposure_level",
        ),
    )
    op.create_index("ix_area_flood_exposure_hazard", "area_flood_exposure", ["hazard_version_id"])
    op.create_index("ix_area_flood_exposure_village", "area_flood_exposure", ["village_version_id"])
    op.create_index("ix_area_flood_exposure_admin_code", "area_flood_exposure", ["admin_code"])


def downgrade() -> None:
    op.drop_index("ix_area_flood_exposure_admin_code", table_name="area_flood_exposure")
    op.drop_index("ix_area_flood_exposure_village", table_name="area_flood_exposure")
    op.drop_index("ix_area_flood_exposure_hazard", table_name="area_flood_exposure")
    op.drop_table("area_flood_exposure")
