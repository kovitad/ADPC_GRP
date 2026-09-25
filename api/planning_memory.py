"""The planning assistant's durable memory: reused SIG evidence and the conversation (ADR-0029).

Two rules keep reuse honest:

* A pack answers questions for ``PACK_REUSE_SECONDS``, but a public receipt may only be offered
  for a pack gathered within ``PACK_PUBLISH_MAX_AGE_SECONDS``. Old evidence can still inform a
  planner; it cannot be certified as current.
* Writing memory never costs the planner their answer. A failed write is logged and treated as a
  miss, because the answer it would have saved took minutes to produce.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.planning_memory_models import PlanningChatMessage, PlanningSigPack

logger = logging.getLogger("grp.planning.memory")

# assemble_pack was 149 s of a 200 s answer. An hour covers a planning session about one area.
PACK_REUSE_SECONDS = 60 * 60
# A receipt certifies the evidence as SIG holds it now, so only a recent pack may be published.
PACK_PUBLISH_MAX_AGE_SECONDS = 5 * 60

MESSAGES_KEPT = 60
MESSAGE_MAX_AGE = timedelta(days=30)
# An evidence card larger than this is kept as its text only; the pack stays in planning_sig_pack.
PAYLOAD_MAX_CHARS = 250_000
# Mirrors ChatTurn and PlanningChat.history, so a restored history is always a valid request.
HISTORY_TURNS = 8
HISTORY_TEXT_MAX = 1200

# Belong to one login and one moment; never stored or replayed.
SESSION_BOUND_FIELDS = ("publish_token", "usage", "cached", "cached_at")


def place_key(place: str) -> str:
    return " ".join(place.casefold().split())[:200]


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes from a timezone-aware column; PostgreSQL does not."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def pack_age_seconds(assembled_at: datetime, now: datetime | None = None) -> float:
    return ((now or datetime.now(UTC)) - as_utc(assembled_at)).total_seconds()


def publishable_age(assembled_at: datetime, now: datetime | None = None) -> bool:
    return pack_age_seconds(assembled_at, now) <= PACK_PUBLISH_MAX_AGE_SECONDS


def stored_pack(
    session: Session, *, user_id: UUID, hub_id: UUID, place: str, now: datetime | None = None
) -> tuple[dict[str, Any], datetime] | None:
    now = now or datetime.now(UTC)
    row = session.scalar(
        select(PlanningSigPack).where(
            PlanningSigPack.user_id == user_id,
            PlanningSigPack.hub_id == hub_id,
            PlanningSigPack.place_key == place_key(place),
        )
    )
    if row is None or as_utc(row.expires_at) <= now:
        return None
    return deepcopy(row.pack), as_utc(row.assembled_at)


def store_pack(
    session: Session,
    *,
    user_id: UUID,
    hub_id: UUID,
    place: str,
    pack: dict[str, Any],
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    key = place_key(place)
    try:
        # A savepoint, so two lookups for one place racing to insert cannot poison the session the
        # rest of the answer still needs. The loser's pack is simply not kept.
        with session.begin_nested():
            session.execute(
                delete(PlanningSigPack).where(
                    PlanningSigPack.user_id == user_id, PlanningSigPack.expires_at <= now
                )
            )
            row = session.scalar(
                select(PlanningSigPack).where(
                    PlanningSigPack.user_id == user_id,
                    PlanningSigPack.hub_id == hub_id,
                    PlanningSigPack.place_key == key,
                )
            )
            if row is None:
                row = PlanningSigPack(user_id=user_id, hub_id=hub_id, place_key=key)
                session.add(row)
            row.pack_id = str(pack.get("pack_id", ""))[:200]
            row.pack = deepcopy(pack)
            row.assembled_at = now
            row.expires_at = now + timedelta(seconds=PACK_REUSE_SECONDS)
        session.commit()
    except SQLAlchemyError:
        logger.warning("SIG pack for %r was not kept for reuse", key, exc_info=True)


def forget(session: Session, *, user_id: UUID, hub_id: UUID) -> None:
    """Start over: drop this person's conversation and reusable evidence in one Hub."""

    for model in (PlanningChatMessage, PlanningSigPack):
        session.execute(delete(model).where(model.user_id == user_id, model.hub_id == hub_id))
    session.commit()


def _stored_payload(response: dict[str, Any]) -> dict[str, Any] | None:
    payload = {k: v for k, v in response.items() if k not in SESSION_BOUND_FIELDS}
    try:
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
    if len(encoded) > PAYLOAD_MAX_CHARS:
        return None
    return json.loads(encoded)


def record_exchange(
    session: Session,
    *,
    user_id: UUID,
    hub_id: UUID,
    question: str | None,
    response: dict[str, Any],
    now: datetime | None = None,
) -> None:
    """Append what the person asked and what they were shown. ``question`` is None for a publish,
    which the person confirmed with a button rather than typed."""

    now = now or datetime.now(UTC)
    answer = str(response.get("answer") or "")
    is_evidence = response.get("mode") == "sig_evidence" and isinstance(
        response.get("evidence"), dict
    )
    payload = _stored_payload(response) if is_evidence else None
    try:
        with session.begin_nested():
            if question:
                session.add(PlanningChatMessage(
                    user_id=user_id, hub_id=hub_id, role="user", kind="message",
                    text=question[:1000], created_at=now,
                ))
            session.add(PlanningChatMessage(
                user_id=user_id,
                hub_id=hub_id,
                role="assistant",
                kind="evidence" if payload is not None else "message",
                text=answer,
                label=str(response.get("label") or "")[:500] or None,
                question=(question or str(response.get("question") or ""))[:1000] or None,
                payload=payload,
                # A microsecond after the question, so the pair can never sort the wrong way.
                created_at=now + timedelta(microseconds=1),
            ))
            session.flush()
            _prune(session, user_id=user_id, hub_id=hub_id, now=now)
        session.commit()
    except SQLAlchemyError:
        logger.warning("planning conversation turn was not kept", exc_info=True)


def _prune(session: Session, *, user_id: UUID, hub_id: UUID, now: datetime) -> None:
    owner = (PlanningChatMessage.user_id == user_id, PlanningChatMessage.hub_id == hub_id)
    session.execute(
        delete(PlanningChatMessage).where(
            *owner, PlanningChatMessage.created_at < now - MESSAGE_MAX_AGE
        )
    )
    beyond = session.scalars(
        select(PlanningChatMessage.id)
        .where(*owner)
        .order_by(PlanningChatMessage.created_at.desc())
        .offset(MESSAGES_KEPT)
    ).all()
    if beyond:
        session.execute(delete(PlanningChatMessage).where(PlanningChatMessage.id.in_(beyond)))


def conversation(session: Session, *, user_id: UUID, hub_id: UUID) -> dict[str, Any]:
    rows = session.scalars(
        select(PlanningChatMessage)
        .where(PlanningChatMessage.user_id == user_id, PlanningChatMessage.hub_id == hub_id)
        .order_by(PlanningChatMessage.created_at)
    ).all()
    messages: list[dict[str, Any]] = []
    history: list[dict[str, str]] = []
    for row in rows:
        entry: dict[str, Any] = {
            "role": row.role,
            "kind": row.kind,
            "text": row.text,
            "label": row.label,
            "question": row.question,
            "created_at": as_utc(row.created_at).isoformat(),
        }
        if row.kind == "evidence" and row.payload is not None:
            entry["payload"] = row.payload
        messages.append(entry)
        # The same rule the browser applies when it builds history (web/planning.js): empty
        # answers are skipped and long ones cut, so a restored history always validates.
        if row.text.strip():
            history.append({"role": row.role, "text": row.text[:HISTORY_TEXT_MAX]})
    return {"messages": messages, "history": history[-HISTORY_TURNS:]}
