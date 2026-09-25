"""What the planning assistant remembers between questions, visits and restarts (ADR-0029).

Both tables are per person and per Hub. Neither is shared: a colleague asking about the same
district gathers their own evidence under their own SIG identity.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.access_models import JSON_VALUE, utc_now, uuid7
from core.db import Base


class PlanningSigPack(Base):
    """One assembled SIG evidence pack per person, Hub and place.

    ``assemble_pack`` was measured at 149 s of a 200 s answer, so a pack is reused for any question
    about the same place until ``expires_at``. Reuse is for reading only: a receipt still needs a
    pack gathered within the publish window, which the chat route checks against ``assembled_at``.
    """

    __tablename__ = "planning_sig_pack"
    __table_args__ = (
        UniqueConstraint("user_id", "hub_id", "place_key", name="uq_planning_sig_pack_place"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    hub_id: Mapped[UUID] = mapped_column(ForeignKey("hub.id", ondelete="CASCADE"), nullable=False)
    place_key: Mapped[str] = mapped_column(String(200), nullable=False)
    pack_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    pack: Mapped[dict[str, object]] = mapped_column(JSON_VALUE, nullable=False)
    assembled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlanningChatMessage(Base):
    """One line of a person's planning conversation in one Hub.

    ``payload`` holds an evidence answer so the card can be drawn again after the tab closes. It is
    stored without the publish token and the usage figures, which belong to the moment and the
    login that produced them.
    """

    __tablename__ = "planning_chat_message"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_planning_chat_message_role"),
        CheckConstraint("kind IN ('message', 'evidence')", name="ck_planning_chat_message_kind"),
        Index("ix_planning_chat_message_owner", "user_id", "hub_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    hub_id: Mapped[UUID] = mapped_column(ForeignKey("hub.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="message")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    label: Mapped[str | None] = mapped_column(String(500))
    question: Mapped[str | None] = mapped_column(String(1000))
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON_VALUE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
