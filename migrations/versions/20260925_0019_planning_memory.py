"""Keep the planning assistant's SIG evidence and conversation in the database (ADR-0029).

Revision ID: 20260925_0019
Revises: 20260924_0018
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260925_0019"
down_revision = "20260924_0018"
branch_labels = None
depends_on = None

JSON_VALUE = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "planning_sig_pack",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("hub_id", sa.Uuid(), sa.ForeignKey("hub.id", ondelete="CASCADE"), nullable=False),
        sa.Column("place_key", sa.String(length=200), nullable=False),
        sa.Column("pack_id", sa.String(length=200), nullable=False),
        sa.Column("pack", JSON_VALUE, nullable=False),
        sa.Column("assembled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "hub_id", "place_key", name="uq_planning_sig_pack_place"),
    )
    op.create_table(
        "planning_chat_message",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("hub_id", sa.Uuid(), sa.ForeignKey("hub.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=500)),
        sa.Column("question", sa.String(length=1000)),
        sa.Column("payload", JSON_VALUE),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_planning_chat_message_role"),
        sa.CheckConstraint("kind IN ('message', 'evidence')", name="ck_planning_chat_message_kind"),
    )
    op.create_index(
        "ix_planning_chat_message_owner",
        "planning_chat_message",
        ["user_id", "hub_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_planning_chat_message_owner", table_name="planning_chat_message")
    op.drop_table("planning_chat_message")
    op.drop_table("planning_sig_pack")
