"""Add server-side session revocation for sign-out and access changes.

Revision ID: 20260916_0002
Revises: 20260916_0001
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0002"
down_revision: str | None = "20260916_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("sessions_valid_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_user", "sessions_valid_after")
