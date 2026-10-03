"""Store flood replays, each in its own namespace (ADR-0044).

Revision ID: 20261003_0026
Revises: 20261003_0025
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261003_0026"
down_revision = "20261003_0025"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flood_replay",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("replay_pilot_id", sa.String(32), nullable=False, unique=True),
        sa.Column("base_pilot_id", sa.String(32), nullable=False),
        sa.Column("hub_id", sa.Uuid(), sa.ForeignKey("hub.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("steps_total", sa.Integer(), nullable=False),
        sa.Column("steps_done", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("injections", JSON_VALUE, nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_flood_replay_base_status", "flood_replay", ["base_pilot_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_flood_replay_base_status", table_name="flood_replay")
    op.drop_table("flood_replay")
