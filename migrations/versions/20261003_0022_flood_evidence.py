"""Store flood-pilot source fetches and distinct observed states (ADR-0038).

Revision ID: 20261003_0022
Revises: 20260928_0021
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261003_0022"
down_revision = "20260928_0021"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flood_source_fetch",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("byte_count", sa.Integer()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("storage_key", sa.String(400)),
        sa.Column("record_count", sa.Integer()),
        sa.Column("new_states", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index(
        "ix_flood_source_fetch_source_time",
        "flood_source_fetch",
        ["pilot_id", "source_id", "retrieved_at"],
    )
    op.create_table(
        "flood_observation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("record_key", sa.String(64), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "first_fetch_id",
            sa.Uuid(),
            sa.ForeignKey("flood_source_fetch.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "last_fetch_id",
            sa.Uuid(),
            sa.ForeignKey("flood_source_fetch.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("geometry", JSON_VALUE, nullable=False),
        sa.Column("depth_cm", sa.Float()),
        sa.Column("state", JSON_VALUE, nullable=False),
        sa.Column("underlying_sources", JSON_VALUE, nullable=False),
        sa.Column("evidence_class", sa.String(24), nullable=False),
        sa.Column("provider_judgement", JSON_VALUE, nullable=False),
        sa.Column("text_sha256", sa.String(64)),
        sa.Column("rule_version", sa.String(48), nullable=False),
        sa.UniqueConstraint(
            "pilot_id", "source_id", "record_key", "state_hash", name="uq_flood_observation_state"
        ),
    )
    op.create_index("ix_flood_observation_last_fetch", "flood_observation", ["last_fetch_id"])
    op.create_index(
        "ix_flood_observation_source_observed",
        "flood_observation",
        ["pilot_id", "source_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_flood_observation_source_observed", table_name="flood_observation")
    op.drop_index("ix_flood_observation_last_fetch", table_name="flood_observation")
    op.drop_table("flood_observation")
    op.drop_index("ix_flood_source_fetch_source_time", table_name="flood_source_fetch")
    op.drop_table("flood_source_fetch")
