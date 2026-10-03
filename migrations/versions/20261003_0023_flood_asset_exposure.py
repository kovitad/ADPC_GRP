"""Store facility exposure and access states per roads snapshot (ADR-0040).

Revision ID: 20261003_0023
Revises: 20261003_0022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261003_0023"
down_revision = "20261003_0022"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flood_asset_exposure",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column(
            "fetch_id",
            sa.Uuid(),
            sa.ForeignKey("flood_source_fetch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(80), nullable=False),
        sa.Column("exposure_state", sa.String(32), nullable=False),
        sa.Column("access_state", sa.String(32), nullable=False),
        sa.Column("nearest_road_key", sa.String(16)),
        sa.Column("nearest_distance_m", sa.Integer()),
        sa.Column("road_keys", JSON_VALUE, nullable=False),
        sa.Column("reasons", JSON_VALUE, nullable=False),
        sa.Column("rule_version", sa.String(48), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("fetch_id", "asset_id", name="uq_flood_asset_exposure_fetch_asset"),
    )
    op.create_index(
        "ix_flood_asset_exposure_fetch_id", "flood_asset_exposure", ["fetch_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_flood_asset_exposure_fetch_id", table_name="flood_asset_exposure")
    op.drop_table("flood_asset_exposure")
