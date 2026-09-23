"""Add persistent progress steps for asynchronous assessments.

Revision ID: 20260923_0013
Revises: 20260922_0012
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0013"
down_revision: str | None = "20260922_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assessment_run_step",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'failed')",
            name="ck_assessment_run_step_state",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_id"], ["assessment.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assessment_id", "sequence", name="uq_assessment_run_step_sequence"
        ),
        sa.UniqueConstraint(
            "assessment_id", "step_key", name="uq_assessment_run_step_key"
        ),
    )
    op.create_index(
        op.f("ix_assessment_run_step_assessment_id"),
        "assessment_run_step",
        ["assessment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_assessment_run_step_assessment_id"),
        table_name="assessment_run_step",
    )
    op.drop_table("assessment_run_step")
