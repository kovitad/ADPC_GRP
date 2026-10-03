"""Store officer reviews of flood incidents and facility access (ADR-0042).

Revision ID: 20261003_0025
Revises: 20261003_0024
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261003_0025"
down_revision = "20261003_0024"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "flood_review",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pilot_id", sa.String(32), nullable=False),
        sa.Column("hub_id", sa.Uuid(), sa.ForeignKey("hub.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("camera_id", sa.String(120)),
        sa.Column("note", sa.Text()),
        sa.Column("road_keys", JSON_VALUE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_flood_review_target",
        "flood_review",
        ["pilot_id", "target_kind", "target_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_flood_review_target", table_name="flood_review")
    op.drop_table("flood_review")
