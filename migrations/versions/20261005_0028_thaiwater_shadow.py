"""Store versioned ThaiWater stations and shadow observations (ADR-0065).

Revision ID: 20261005_0028
Revises: 20261003_0027
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261005_0028"
down_revision = "20261003_0027"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "hydro_station_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("provider_station_id", sa.String(180), nullable=False),
        sa.Column("identity_basis", sa.String(24), nullable=False),
        sa.Column("station_code", sa.String(120)),
        sa.Column("station_name", sa.Text(), nullable=False),
        sa.Column("station_type", sa.String(80)),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("geometry", JSON_VALUE, nullable=False),
        sa.Column("originating_agency_code", sa.String(80)),
        sa.Column("originating_agency_name", sa.Text()),
        sa.Column("source_admin", JSON_VALUE, nullable=False),
        sa.Column("basin", JSON_VALUE, nullable=False),
        sa.Column("district_codes", JSON_VALUE, nullable=False),
        sa.Column("subdistrict_codes", JSON_VALUE, nullable=False),
        sa.Column("version_hash", sa.String(64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "first_fetch_id", sa.Uuid(),
            sa.ForeignKey("flood_source_fetch.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "last_fetch_id", sa.Uuid(),
            sa.ForeignKey("flood_source_fetch.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.UniqueConstraint(
            "pilot_id", "provider", "product", "provider_station_id", "version_hash",
            name="uq_hydro_station_version",
        ),
    )
    op.create_index(
        "ix_hydro_station_provider_identity", "hydro_station_version",
        ["pilot_id", "provider", "provider_station_id"],
    )

    op.create_table(
        "hydro_observation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column(
            "station_version_id", sa.Uuid(),
            sa.ForeignKey("hydro_station_version.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("variable", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("datum", sa.String(32)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_flag", sa.String(32)),
        sa.Column("quality_control_level", sa.String(32)),
        sa.Column("quality", JSON_VALUE, nullable=False),
        sa.Column("clock_status", sa.String(16), nullable=False),
        sa.Column("originating_agency_code", sa.String(80)),
        sa.Column("originating_agency_name", sa.Text()),
        sa.Column("delivery_provider", sa.String(32), nullable=False),
        sa.Column(
            "raw_fetch_id", sa.Uuid(),
            sa.ForeignKey("flood_source_fetch.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("adapter_version", sa.String(48), nullable=False),
        sa.UniqueConstraint(
            "pilot_id", "provider", "product", "state_hash",
            name="uq_hydro_observation_state",
        ),
    )
    op.create_index(
        "ix_hydro_observation_station_time", "hydro_observation",
        ["station_version_id", "observed_at"],
    )
    op.create_index(
        "ix_hydro_observation_pilot_time", "hydro_observation", ["pilot_id", "observed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_hydro_observation_pilot_time", table_name="hydro_observation")
    op.drop_index("ix_hydro_observation_station_time", table_name="hydro_observation")
    op.drop_table("hydro_observation")
    op.drop_index("ix_hydro_station_provider_identity", table_name="hydro_station_version")
    op.drop_table("hydro_station_version")
