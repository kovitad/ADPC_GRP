"""Record the facility type derived from a delivered evacuation-centre name.

The column is nullable because the type is derived, not delivered: a name the classifier does
not recognise stays NULL and is reported as unclassified (ADR-0028). Existing rows are left NULL
rather than backfilled here, because classifying them belongs to the importer that owns the
delivered name, and a re-import writes a new immutable version anyway.

Revision ID: 20260924_0017
Revises: 20260924_0016
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_0017"
down_revision = "20260924_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feature", sa.Column("facility_type", sa.String(length=32), nullable=True))
    op.create_index("ix_feature_facility_type", "feature", ["facility_type"])


def downgrade() -> None:
    op.drop_index("ix_feature_facility_type", table_name="feature")
    op.drop_column("feature", "facility_type")
