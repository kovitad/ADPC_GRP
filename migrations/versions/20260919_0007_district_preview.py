"""District previews share the inspection job table (backlog Epic P).

A preview is keyed by the district asked for as well as the files, so an "All source data"
report and a district preview of the same files can never be handed out for each other.

Revision ID: 20260919_0007
Revises: 20260918_0006
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0007"
down_revision: str | None = "20260918_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_inspection",
        sa.Column("district", sa.String(length=200), nullable=False, server_default=""),
    )
    op.drop_index("ix_dataset_inspection_cache", table_name="dataset_inspection")
    op.create_index(
        "ix_dataset_inspection_cache",
        "dataset_inspection",
        ["folder", "district", "fingerprint", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_inspection_cache", table_name="dataset_inspection")
    op.create_index(
        "ix_dataset_inspection_cache",
        "dataset_inspection",
        ["folder", "fingerprint", "state"],
    )
    op.drop_column("dataset_inspection", "district")
