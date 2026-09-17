"""AI usage limit rules AI-01 to AI-13 (GRP-ARC-001 Section 10).

The GRP database is the official record (AD-12). Langfuse is only a helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_models import AppUser, AuditEvent, AuditResult, UserStatus
from core.ai_models import AiAllowance, AiUsageSetting, LlmUsage

# Asia/Bangkok has no daylight saving; a fixed offset avoids a tzdata dependency in containers.
BANGKOK = timezone(timedelta(hours=7), name="Asia/Bangkok")
MIN_TOKEN_LIMIT = 1_000
MAX_TOKEN_LIMIT = 100_000_000
RESERVATION_TTL = timedelta(minutes=10)


class AiBlocked(Exception):
    """AI must not run; `code` is an Appendix D error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class UsageView:
    tokens_used: int
    tokens_reserved: int
    tokens_remaining: int
    token_limit: int | None
    reset_at: datetime
    status: str  # active | limit_reached | ai_off


def period_month(now: datetime) -> date:
    local = now.astimezone(BANGKOK)
    return date(local.year, local.month, 1)


def next_reset(now: datetime) -> datetime:
    local = now.astimezone(BANGKOK)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(year, month, 1, tzinfo=BANGKOK)


def load_setting(session: Session, *, lock: bool = False) -> AiUsageSetting:
    query = select(AiUsageSetting).where(AiUsageSetting.id == 1)
    if lock:
        query = query.with_for_update()
    setting = session.scalar(query)
    if setting is None:
        setting = AiUsageSetting(id=1, ai_enabled=False)
        session.add(setting)
        session.flush()
    return setting


def _allowance(session: Session, user_id: UUID, month: date, *, lock: bool) -> AiAllowance:
    query = select(AiAllowance).where(
        AiAllowance.user_id == user_id, AiAllowance.period_month == month
    )
    if lock:
        query = query.with_for_update()
    row = session.scalar(query)
    if row is None:
        row = AiAllowance(
            user_id=user_id, period_month=month, tokens_used=0, tokens_reserved=0, reservations=[]
        )
        session.add(row)
        session.flush()
    return row


def usage_view(
    session: Session, user_id: UUID, *, feature_enabled: bool, now: datetime | None = None
) -> UsageView:
    now = now or datetime.now(UTC)
    setting = load_setting(session)
    row = session.scalar(
        select(AiAllowance).where(
            AiAllowance.user_id == user_id, AiAllowance.period_month == period_month(now)
        )
    )
    used = row.tokens_used if row else 0
    reserved = row.tokens_reserved if row else 0
    limit = setting.token_limit_per_person
    remaining = max(0, (limit or 0) - used - reserved)
    if not feature_enabled or not setting.ai_enabled or limit is None:
        status = "ai_off"
    elif remaining == 0:
        status = "limit_reached"
    else:
        status = "active"
    return UsageView(used, reserved, remaining, limit, next_reset(now), status)


def reserve(
    session: Session,
    user_id: UUID,
    *,
    request_id: str,
    estimate: int,
    feature_enabled: bool,
    now: datetime | None = None,
) -> date:
    """Steps 2 to 5 of Section 10.4. Caller commits on success."""

    now = now or datetime.now(UTC)
    setting = load_setting(session)
    if not feature_enabled or not setting.ai_enabled or setting.token_limit_per_person is None:
        raise AiBlocked("AI_OFF")
    month = period_month(now)
    row = _allowance(session, user_id, month, lock=True)
    limit = setting.token_limit_per_person
    remaining = limit - row.tokens_used - row.tokens_reserved
    # Do not start a call whose estimated maximum already exceeds the balance.
    # Actual provider usage may still exceed the estimate and is fully counted (AI-09).
    amount = max(1, estimate)
    if amount > remaining:
        raise AiBlocked("AI_LIMIT_REACHED")
    row.tokens_reserved += amount
    row.reservations = [
        *row.reservations,
        {"request_id": request_id, "amount": amount, "created_at": now.isoformat()},
    ]
    return month


def settle(
    session: Session,
    user_id: UUID,
    *,
    month: date,
    request_id: str,
    hub_id: UUID | None,
    channel: str,
    provider: str,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    outcome: str,
) -> None:
    """Step 7 and 8 of Section 10.4: swap the reservation for real tokens. Caller commits."""

    row = _allowance(session, user_id, month, lock=True)
    remaining: list[dict[str, object]] = []
    for item in row.reservations:
        if item.get("request_id") == request_id:
            row.tokens_reserved = max(0, row.tokens_reserved - int(item.get("amount", 0)))
        else:
            remaining.append(item)
    row.reservations = remaining
    total = max(0, input_tokens) + max(0, output_tokens)
    row.tokens_used += total
    session.add(
        LlmUsage(
            user_id=user_id,
            hub_id=hub_id,
            channel=channel,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            input_tokens=max(0, input_tokens),
            output_tokens=max(0, output_tokens),
            total_tokens=total,
            outcome=outcome,
            period_month=month,
            request_id=request_id,
        )
    )


def release_stale_reservations(session: Session, now: datetime | None = None) -> int:
    """Worker task: drop reservations older than 10 minutes. Caller commits."""

    now = now or datetime.now(UTC)
    released = 0
    rows = session.scalars(
        select(AiAllowance).where(AiAllowance.tokens_reserved > 0).with_for_update()
    ).all()
    for row in rows:
        keep: list[dict[str, object]] = []
        for item in row.reservations:
            created = datetime.fromisoformat(str(item.get("created_at")))
            if now - created > RESERVATION_TTL:
                row.tokens_reserved = max(0, row.tokens_reserved - int(item.get("amount", 0)))
                released += 1
            else:
                keep.append(item)
        row.reservations = keep
    return released


def update_setting(
    session: Session,
    *,
    actor_user_id: UUID,
    token_limit_per_person: int,
    ai_enabled: bool,
    now: datetime | None = None,
) -> AiUsageSetting:
    if not MIN_TOKEN_LIMIT <= token_limit_per_person <= MAX_TOKEN_LIMIT:
        raise ValueError("Token limit must be a whole number from 1,000 to 100,000,000")
    now = now or datetime.now(UTC)
    setting = load_setting(session, lock=True)
    old = {
        "token_limit_per_person": setting.token_limit_per_person,
        "ai_enabled": setting.ai_enabled,
    }
    setting.token_limit_per_person = token_limit_per_person
    setting.ai_enabled = ai_enabled
    setting.changed_by = actor_user_id
    setting.changed_at = now
    new = {"token_limit_per_person": token_limit_per_person, "ai_enabled": ai_enabled}
    if old["ai_enabled"] != ai_enabled:
        _audit(session, actor_user_id, "ai_enabled_changed", "ai_usage_setting", "1", old, new)
    if old["token_limit_per_person"] != token_limit_per_person:
        _audit(session, actor_user_id, "ai_setting_changed", "ai_usage_setting", "1", old, new)
    return setting


def reset_person_usage(
    session: Session,
    *,
    actor_user_id: UUID,
    user_id: UUID,
    now: datetime | None = None,
) -> int:
    """Manual reset of the current month (ADR-0003). Keeps llm_usage history. Caller commits."""

    now = now or datetime.now(UTC)
    person = session.get(AppUser, user_id)
    if person is None:
        raise LookupError("Person not found")
    row = _allowance(session, user_id, period_month(now), lock=True)
    old_used = row.tokens_used
    row.tokens_used = 0
    _audit(
        session,
        actor_user_id,
        "ai_allowance_reset",
        "app_user",
        str(user_id),
        {"tokens_used": old_used, "period_month": row.period_month.isoformat()},
        {"tokens_used": 0, "period_month": row.period_month.isoformat()},
    )
    return old_used


def people_usage(
    session: Session, *, feature_enabled: bool, now: datetime | None = None
) -> list[dict[str, object]]:
    now = now or datetime.now(UTC)
    people = session.scalars(
        select(AppUser).where(AppUser.status == UserStatus.ACTIVE).order_by(AppUser.email)
    ).all()
    rows = []
    for person in people:
        view = usage_view(session, person.id, feature_enabled=feature_enabled, now=now)
        rows.append(
            {
                "user_id": str(person.id),
                "email": person.email,
                "display_name": person.display_name,
                "tokens_used": view.tokens_used,
                "tokens_remaining": view.tokens_remaining,
                "token_limit": view.token_limit,
                "reset_at": view.reset_at.isoformat(),
                "status": view.status,
            }
        )
    return rows


def _audit(
    session: Session,
    actor_user_id: UUID,
    action: str,
    target_type: str,
    target_id: str,
    old: dict[str, object] | None,
    new: dict[str, object] | None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            actor_kind="person",
            action=action,
            target_type=target_type,
            target_id=target_id,
            old_value=old,
            new_value=new,
            result=AuditResult.SUCCESS,
        )
    )
