"""Replace the generic Planner role with explicit Hub planning roles.

Revision ID: 20260917_0005
Revises: 20260916_0004
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0005"
down_revision: str | None = "20260916_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_hub_membership_role", "hub_membership", type_="check")
    # Existing planning members retain their access under the new canonical role.
    op.execute(sa.text("UPDATE hub_membership SET role = 'hub_expert' WHERE role = 'planner'"))
    op.create_check_constraint(
        "ck_hub_membership_role",
        "hub_membership",
        "role IN ('ndmo_planner', 'hub_expert', 'planner', 'admin')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_hub_membership_role", "hub_membership", type_="check")
    op.execute(
        sa.text(
            "UPDATE hub_membership SET role = 'planner' "
            "WHERE role IN ('ndmo_planner', 'hub_expert')"
        )
    )
    op.create_check_constraint(
        "ck_hub_membership_role", "hub_membership", "role IN ('planner', 'admin')"
    )
