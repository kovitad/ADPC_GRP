"""Add versioned PostGIS boundary collection support.

Revision ID: 20260920_0009
Revises: 20260919_0008
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0009"
down_revision: str | None = "20260919_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.drop_constraint("ck_dataset_type", "dataset", type_="check")
    op.create_check_constraint(
        "ck_dataset_type",
        "dataset",
        "type IN ('boundary', 'hazard', 'evacuation_centers', 'vulnerability')",
    )
    op.add_column("boundary", sa.Column("name_th", sa.String(length=200), nullable=True))
    op.add_column("boundary", sa.Column("province_name", sa.String(length=200), nullable=True))
    op.add_column("boundary", sa.Column("province_name_th", sa.String(length=200), nullable=True))
    # The JSON geometry remains as the SQLite-compatible representation used by current APIs.
    # PostGIS is the authoritative scalable spatial representation for imported collections.
    op.execute("ALTER TABLE boundary ADD COLUMN geom_postgis geometry(MultiPolygon, 4326)")
    op.execute(
        "ALTER TABLE boundary ADD COLUMN geom_simplified_postgis geometry(MultiPolygon, 4326)"
    )
    op.create_index(
        "ix_boundary_geom_postgis",
        "boundary",
        ["geom_postgis"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "ix_boundary_geom_simplified_postgis",
        "boundary",
        ["geom_simplified_postgis"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_unique_constraint(
        "uq_boundary_collection_admin_code",
        "boundary",
        ["collection_version_id", "admin_code"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_boundary_collection_admin_code", "boundary", type_="unique")
    op.drop_index("ix_boundary_geom_simplified_postgis", table_name="boundary")
    op.drop_index("ix_boundary_geom_postgis", table_name="boundary")
    op.drop_column("boundary", "geom_simplified_postgis")
    op.drop_column("boundary", "geom_postgis")
    op.drop_column("boundary", "province_name_th")
    op.drop_column("boundary", "province_name")
    op.drop_column("boundary", "name_th")
    op.drop_constraint("ck_dataset_type", "dataset", type_="check")
    op.create_check_constraint(
        "ck_dataset_type",
        "dataset",
        "type IN ('hazard', 'evacuation_centers', 'vulnerability')",
    )
