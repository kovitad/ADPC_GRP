"""Keep a durable record of each contribution sent to Global Risk (ADR-0032).

Revision ID: 20260928_0021
Revises: 20260925_0020
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260928_0021"
down_revision = "20260925_0020"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "sig_contribution",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("hub_id", sa.Uuid(), sa.ForeignKey("hub.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("manifest", JSON_VALUE, nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("contribution_id", sa.String(64)),
        sa.Column("problems", JSON_VALUE),
        sa.Column("response", JSON_VALUE),
        sa.Column("file_sha256", sa.String(64)),
        sa.Column("feature_count", sa.Integer()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index(
        "ix_sig_contribution_hub_created", "sig_contribution", ["hub_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_sig_contribution_hub_created", table_name="sig_contribution")
    op.drop_table("sig_contribution")
