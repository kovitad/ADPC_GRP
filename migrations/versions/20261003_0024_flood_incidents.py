"""Store flood incidents, their change events and incident runs (ADR-0041).

Revision ID: 20261003_0024
Revises: 20261003_0023
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261003_0024"
down_revision = "20261003_0023"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flood_incident",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("road_keys", JSON_VALUE, nullable=False),
        sa.Column("bbox", JSON_VALUE, nullable=False),
        sa.Column("summary", JSON_VALUE, nullable=False),
        sa.Column("rule_version", sa.String(48), nullable=False),
    )
    op.create_index("ix_flood_incident_pilot_status", "flood_incident", ["pilot_id", "status"])
    op.create_table(
        "flood_incident_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("flood_incident.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("detail", JSON_VALUE, nullable=False),
    )
    op.create_index(
        "ix_flood_incident_event_incident_id", "flood_incident_event", ["incident_id"]
    )
    op.create_index("ix_flood_incident_event_pilot_at", "flood_incident_event", ["pilot_id", "at"])
    op.create_table(
        "flood_incident_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column(
            "fetch_id",
            sa.Uuid(),
            sa.ForeignKey("flood_source_fetch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_flood_incident_run_pilot_snapshot", "flood_incident_run", ["pilot_id", "snapshot_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_flood_incident_run_pilot_snapshot", table_name="flood_incident_run")
    op.drop_table("flood_incident_run")
    op.drop_index("ix_flood_incident_event_pilot_at", table_name="flood_incident_event")
    op.drop_index("ix_flood_incident_event_incident_id", table_name="flood_incident_event")
    op.drop_table("flood_incident_event")
    op.drop_index("ix_flood_incident_pilot_status", table_name="flood_incident")
    op.drop_table("flood_incident")
