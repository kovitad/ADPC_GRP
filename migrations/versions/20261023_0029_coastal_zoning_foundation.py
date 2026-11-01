"""Add persistent coastal-zoning run foundation (ADR-0070).

Revision ID: 20261023_0029
Revises: 20261005_0028
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261023_0029"
down_revision = "20261005_0028"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "coastal_zoning_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "hub_id", sa.Uuid(), sa.ForeignKey("hub.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("app_user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("site_name", sa.String(200), nullable=False),
        sa.Column("country", sa.String(2)),
        sa.Column("aoi_geojson", JSON_VALUE, nullable=False),
        sa.Column("aoi_source", sa.String(16), nullable=False),
        sa.Column("aoi_sha256", sa.String(64), nullable=False),
        sa.Column("profile", sa.String(16), nullable=False),
        sa.Column("scale", sa.String(16), nullable=False),
        sa.Column("params", JSON_VALUE, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("review_state", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("versions", JSON_VALUE, nullable=False),
        sa.Column("lead", JSON_VALUE),
        sa.Column("error", JSON_VALUE),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("support_ref", sa.String(32), nullable=False),
        sa.Column(
            "cancellation_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'failed', 'succeeded', 'cancelled', 'retired')",
            name="ck_coastal_zoning_run_status",
        ),
        sa.CheckConstraint(
            "aoi_source IN ('place', 'drawn', 'upload')", name="ck_coastal_zoning_aoi_source"
        ),
        sa.CheckConstraint("profile IN ('hazard', 'no_hazard')", name="ck_coastal_zoning_profile"),
        sa.CheckConstraint("scale IN ('local', 'province')", name="ck_coastal_zoning_scale"),
        sa.CheckConstraint(
            "review_state IN ('draft', 'reviewed')", name="ck_coastal_zoning_review_state"
        ),
        sa.CheckConstraint("attempt >= 0", name="ck_coastal_zoning_attempt"),
        sa.UniqueConstraint(
            "owner_id", "hub_id", "idempotency_key", name="uq_coastal_zoning_idempotency"
        ),
        sa.UniqueConstraint("trace_id", name="uq_coastal_zoning_trace_id"),
    )
    op.create_index("ix_coastal_zoning_run_hub_id", "coastal_zoning_run", ["hub_id"])
    op.create_index("ix_coastal_zoning_run_owner_id", "coastal_zoning_run", ["owner_id"])
    op.create_index("ix_coastal_zoning_run_status", "coastal_zoning_run", ["status"])

    op.create_table(
        "coastal_zoning_step",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("coastal_zoning_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer()),
        sa.Column("total", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("summary", sa.String(500)),
        sa.Column("detail", JSON_VALUE, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'skipped')",
            name="ck_coastal_zoning_step_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_coastal_zoning_step_attempts"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_coastal_zoning_step_duration"
        ),
        sa.UniqueConstraint("run_id", "step_key", name="uq_coastal_zoning_step_key"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_coastal_zoning_step_sequence"),
    )
    op.create_index("ix_coastal_zoning_step_run_id", "coastal_zoning_step", ["run_id"])

    op.create_table(
        "coastal_zoning_zone",
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("coastal_zoning_run.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("zone_id", sa.String(16), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("rank", sa.Integer()),
        sa.Column("score", sa.Float()),
        sa.Column("area_km2", sa.Float(), nullable=False),
        sa.Column("geometry", JSON_VALUE, nullable=False),
        sa.Column("facts", JSON_VALUE, nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("pack_id", sa.String(200)),
        sa.Column("receipt_id", sa.String(200)),
        sa.Column("partner_zone", sa.String(16)),
        sa.Column("partner_km", sa.Float()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "kind IN ('coastal', 'inland', 'restoration')",
            name="ck_coastal_zoning_zone_kind",
        ),
        sa.CheckConstraint("rank IS NULL OR rank > 0", name="ck_coastal_zoning_zone_rank"),
        sa.CheckConstraint("area_km2 >= 0", name="ck_coastal_zoning_zone_area"),
    )
    op.create_index("ix_coastal_zoning_zone_receipt_id", "coastal_zoning_zone", ["receipt_id"])

    op.create_table(
        "coastal_zoning_artifact",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("coastal_zoning_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("bytes >= 0", name="ck_coastal_zoning_artifact_bytes"),
        sa.UniqueConstraint("run_id", "kind", name="uq_coastal_zoning_artifact_kind"),
        sa.UniqueConstraint("storage_key", name="uq_coastal_zoning_artifact_storage_key"),
    )
    op.create_index("ix_coastal_zoning_artifact_run_id", "coastal_zoning_artifact", ["run_id"])

    op.create_table(
        "coastal_zoning_review_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("coastal_zoning_run.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            sa.Uuid(),
            sa.ForeignKey("app_user.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reviewer_role", sa.String(32), nullable=False),
        sa.Column("field", sa.String(100), nullable=False),
        sa.Column("old_value", JSON_VALUE),
        sa.Column("new_value", JSON_VALUE),
        sa.Column("support_ref", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_coastal_zoning_review_log_run_id", "coastal_zoning_review_log", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_coastal_zoning_review_log_run_id", table_name="coastal_zoning_review_log")
    op.drop_table("coastal_zoning_review_log")
    op.drop_index("ix_coastal_zoning_artifact_run_id", table_name="coastal_zoning_artifact")
    op.drop_table("coastal_zoning_artifact")
    op.drop_index("ix_coastal_zoning_zone_receipt_id", table_name="coastal_zoning_zone")
    op.drop_table("coastal_zoning_zone")
    op.drop_index("ix_coastal_zoning_step_run_id", table_name="coastal_zoning_step")
    op.drop_table("coastal_zoning_step")
    op.drop_index("ix_coastal_zoning_run_status", table_name="coastal_zoning_run")
    op.drop_index("ix_coastal_zoning_run_owner_id", table_name="coastal_zoning_run")
    op.drop_index("ix_coastal_zoning_run_hub_id", table_name="coastal_zoning_run")
    op.drop_table("coastal_zoning_run")
