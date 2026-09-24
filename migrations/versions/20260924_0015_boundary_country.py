"""Record the country of a boundary delivery so places are Hub-independent.

Revision ID: 20260924_0015
Revises: 20260924_0014
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0015"
down_revision = "20260924_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("boundary", sa.Column("country_name", sa.String(length=200), nullable=True))
    # Backfill only the two deliveries that are known to be Thai, named exactly. Anything else,
    # including the synthetic test district, stays NULL, which is the signal that no country is
    # recorded and none may be guessed. The column stays nullable for the same reason.
    op.execute(
        sa.text(
            "UPDATE boundary SET country_name = 'Thailand' "
            "WHERE country_name IS NULL AND source IN ("
            "'ADPC Data Science delivery', "
            "'ADPC Data Science Thailand hierarchy delivery')"
        )
    )


def downgrade() -> None:
    op.drop_column("boundary", "country_name")
