"""Cached data-inspection reports for the Admin data inspector (ADR-0006).

Revision ID: 20260918_0006
Revises: 20260917_0005
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_0006"
down_revision: str | None = "20260917_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_inspection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hub_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("folder", sa.String(length=400), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("support_ref", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_dataset_inspection_state",
        ),
        sa.ForeignKeyConstraint(["hub_id"], ["hub.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_inspection_hub_id", "dataset_inspection", ["hub_id"])
    op.create_index("ix_dataset_inspection_state", "dataset_inspection", ["state"])
    # The cache lookup: this folder, these exact files, a usable state.
    op.create_index(
        "ix_dataset_inspection_cache",
        "dataset_inspection",
        ["folder", "fingerprint", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_inspection_cache", table_name="dataset_inspection")
    op.drop_index("ix_dataset_inspection_state", table_name="dataset_inspection")
    op.drop_index("ix_dataset_inspection_hub_id", table_name="dataset_inspection")
    op.drop_table("dataset_inspection")
