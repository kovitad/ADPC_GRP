"""Add spatial district membership for imported evacuation centres.

Revision ID: 20260920_0010
Revises: 20260920_0009
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0010"
down_revision: str | None = "20260920_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "feature",
        sa.Column(
            "boundary_id",
            sa.Uuid(),
            sa.ForeignKey("boundary.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_feature_boundary_id", "feature", ["boundary_id"], unique=False)
    op.execute("ALTER TABLE feature ADD COLUMN geom_postgis geometry(Point, 4326)")
    op.create_index(
        "ix_feature_geom_postgis",
        "feature",
        ["geom_postgis"],
        unique=False,
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_feature_geom_postgis", table_name="feature")
    op.drop_column("feature", "geom_postgis")
    op.drop_index("ix_feature_boundary_id", table_name="feature")
    op.drop_column("feature", "boundary_id")
