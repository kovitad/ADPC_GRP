"""Store each sensitivity indicator's source value at each evacuation centre (ADR-0030).

Revision ID: 20260925_0020
Revises: 20260925_0019
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0020"
down_revision = "20260925_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "centre_indicator_value",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "feature_id", sa.Uuid(), sa.ForeignKey("feature.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "centers_version_id", sa.Uuid(),
            sa.ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "vulnerability_version_id", sa.Uuid(),
            sa.ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("value", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint(
            "feature_id", "vulnerability_version_id", name="uq_centre_indicator_value"
        ),
    )
    op.create_index(
        "ix_centre_indicator_value_feature_id", "centre_indicator_value", ["feature_id"]
    )
    op.create_index(
        "ix_centre_indicator_value_centers_version_id",
        "centre_indicator_value",
        ["centers_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_centre_indicator_value_centers_version_id", table_name="centre_indicator_value"
    )
    op.drop_index("ix_centre_indicator_value_feature_id", table_name="centre_indicator_value")
    op.drop_table("centre_indicator_value")
