"""Versioned data-library import foundation (ADR-0008).

Revision ID: 20260919_0008
Revises: 20260919_0007
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260919_0008"
down_revision: str | None = "20260919_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "dataset_version",
        sa.Column(
            "readiness", sa.String(length=32), server_default="assessment_ready", nullable=False
        ),
    )
    op.add_column(
        "dataset_version", sa.Column("importer_version", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "dataset_version", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_dataset_version_readiness",
        "dataset_version",
        "readiness IN ('received', 'validating', 'needs_correction', 'technically_valid', "
        "'waiting_for_method', 'ready_for_acceptance', 'assessment_ready', 'retired')",
    )
    op.add_column("boundary", sa.Column("collection_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_boundary_collection_version",
        "boundary",
        "dataset_version",
        ["collection_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_boundary_collection_version_id"),
        "boundary",
        ["collection_version_id"],
        unique=False,
    )

    op.create_table(
        "data_import_job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hub_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("source_mode", sa.String(length=24), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manifest", JSON_VALUE, nullable=False),
        sa.Column("report", JSON_VALUE, nullable=True),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("support_ref", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category IN ('boundary', 'evacuation_centers', 'hazard', 'vulnerability')",
            name="ck_data_import_category",
        ),
        sa.CheckConstraint(
            "source_mode IN ('source_folder', 'browser_upload')",
            name="ck_data_import_source_mode",
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_data_import_state",
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_data_import_progress"),
        sa.ForeignKeyConstraint(["hub_id"], ["hub.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by"], ["app_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requested_by", "idempotency_key", name="uq_data_import_idempotency"),
    )
    op.create_index(
        "ix_data_import_claim", "data_import_job", ["state", "lease_until", "created_at"]
    )
    op.create_index(op.f("ix_data_import_job_hub_id"), "data_import_job", ["hub_id"])
    op.create_index(op.f("ix_data_import_job_state"), "data_import_job", ["state"])

    op.create_table(
        "dataset_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("original_name", sa.String(length=300), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("metadata", JSON_VALUE, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
        sa.UniqueConstraint(
            "dataset_version_id", "role", "storage_key", name="uq_dataset_file_role"
        ),
    )
    op.create_index(
        op.f("ix_dataset_file_dataset_version_id"), "dataset_file", ["dataset_version_id"]
    )

    op.create_table(
        "hub_dataset_selection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hub_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("scenario_key", sa.String(length=100), server_default="default", nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("selected_by", sa.Uuid(), nullable=False),
        sa.Column(
            "selected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["hub_id"], ["hub.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["selected_by"], ["app_user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hub_id", "category", "scenario_key", name="uq_hub_dataset_selection"),
    )
    op.create_index(op.f("ix_hub_dataset_selection_hub_id"), "hub_dataset_selection", ["hub_id"])
    op.create_index(
        op.f("ix_hub_dataset_selection_dataset_version_id"),
        "hub_dataset_selection",
        ["dataset_version_id"],
    )


def downgrade() -> None:
    op.drop_table("hub_dataset_selection")
    op.drop_table("dataset_file")
    op.drop_table("data_import_job")
    op.drop_index(op.f("ix_boundary_collection_version_id"), table_name="boundary")
    op.drop_constraint("fk_boundary_collection_version", "boundary", type_="foreignkey")
    op.drop_column("boundary", "collection_version_id")
    op.drop_constraint("ck_dataset_version_readiness", "dataset_version", type_="check")
    op.drop_column("dataset_version", "accepted_at")
    op.drop_column("dataset_version", "importer_version")
    op.drop_column("dataset_version", "readiness")
