"""Add validation profiles to source-data inspections.

Revision ID: 20260921_0011
Revises: 20260920_0010
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0011"
down_revision: str | None = "20260920_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_inspection",
        sa.Column(
            "profile",
            sa.String(length=32),
            server_default="grp_baseline",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_dataset_inspection_profile",
        "dataset_inspection",
        "profile IN ('general', 'grp_baseline', 'flood_depth', 'points_boundaries')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_dataset_inspection_profile", "dataset_inspection", type_="check"
    )
    op.drop_column("dataset_inspection", "profile")
