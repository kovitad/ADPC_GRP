"""Store rain now and the next 30 minutes per scope (ADR-0049).

Revision ID: 20261003_0027
Revises: 20261003_0026
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261003_0027"
down_revision = "20261003_0026"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flood_weather",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column("observed_base_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("radius_km", sa.Float(), nullable=False),
        sa.Column("rain_now", JSON_VALUE),
        sa.Column("forecast", JSON_VALUE),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("error", sa.Text()),
    )
    op.create_index(
        "ix_flood_weather_pilot_base", "flood_weather", ["pilot_id", "observed_base_time"]
    )


def downgrade() -> None:
    op.drop_index("ix_flood_weather_pilot_base", table_name="flood_weather")
    op.drop_table("flood_weather")
