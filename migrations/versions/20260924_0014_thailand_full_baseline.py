"""Enable the complete Thailand Hub baseline dataset roles.

Revision ID: 20260924_0014
Revises: 20260923_0013
"""

from alembic import op

revision = "20260924_0014"
down_revision = "20260923_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_dataset_type", "dataset", type_="check")
    op.create_check_constraint(
        "ck_dataset_type",
        "dataset",
        "type IN ('boundary', 'hazard', 'evacuation_centers', 'volunteer_centers', "
        "'early_warning_resources', 'village_locations', 'vulnerability')",
    )
    op.drop_constraint("ck_data_import_category", "data_import_job", type_="check")
    op.create_check_constraint(
        "ck_data_import_category",
        "data_import_job",
        "category IN ('boundary', 'evacuation_centers', 'hazard', "
        "'volunteer_centers', 'early_warning_resources', 'village_locations', "
        "'vulnerability_child', 'vulnerability_elderly', 'vulnerability_disability')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_data_import_category", "data_import_job", type_="check")
    op.create_check_constraint(
        "ck_data_import_category",
        "data_import_job",
        "category IN ('boundary', 'evacuation_centers', 'hazard', 'vulnerability')",
    )
    op.drop_constraint("ck_dataset_type", "dataset", type_="check")
    op.create_check_constraint(
        "ck_dataset_type",
        "dataset",
        "type IN ('boundary', 'hazard', 'evacuation_centers', 'vulnerability')",
    )
