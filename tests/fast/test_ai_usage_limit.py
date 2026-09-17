"""GRP-ARC-001 Section 10: AI usage limit rules, gateway and Langfuse export."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from api.ai_gateway import ProviderError, run_ai_call
from api.errors import GrpError
from api.langfuse import AiCallRecord, build_batch, person_reference, send_ai_call
from api.settings import Settings
from core.access_models import AppUser, AuditEvent, Base
from core.ai_allowance import (
    AiBlocked,
    next_reset,
    period_month,
    release_stale_reservations,
    reserve,
    reset_person_usage,
    settle,
    update_setting,
    usage_view,
)
from core.ai_models import AiAllowance, LlmUsage


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _person(session: Session, email: str = "planner@example.test", admin: bool = False):
    user = AppUser(email=email, status="active", is_platform_admin=admin)
    session.add(user)
    session.flush()
    return user


def _enable(session: Session, actor, limit: int = 10_000) -> None:
    update_setting(session, actor_user_id=actor.id, token_limit_per_person=limit, ai_enabled=True)
    session.flush()


def _settings(**overrides) -> Settings:
    values = {"ai_feature_enabled": True, "ai_model": "test-model", "ai_max_output_tokens": 100}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_bangkok_month_and_reset_boundary() -> None:
    # 23:30 UTC on 31 Jan is already 1 Feb in Bangkok (AI-05).
    moment = datetime(2026, 1, 31, 23, 30, tzinfo=UTC)
    assert period_month(moment) == date(2026, 2, 1)
    assert next_reset(moment).isoformat() == "2026-03-01T00:00:00+07:00"
    assert next_reset(datetime(2026, 12, 15, tzinfo=UTC)).isoformat() == (
        "2027-01-01T00:00:00+07:00"
    )


def test_ai_is_off_until_platform_admin_sets_a_limit(session) -> None:
    person = _person(session)
    with pytest.raises(AiBlocked) as blocked:
        reserve(session, person.id, request_id="r1", estimate=10, feature_enabled=True)
    assert blocked.value.code == "AI_OFF"
    assert usage_view(session, person.id, feature_enabled=True).status == "ai_off"


def test_build_switch_off_blocks_even_with_setting_on(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin)
    with pytest.raises(AiBlocked) as blocked:
        reserve(session, admin.id, request_id="r1", estimate=10, feature_enabled=False)
    assert blocked.value.code == "AI_OFF"


def test_limit_range_is_enforced(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    for bad in (999, 100_000_001):
        with pytest.raises(ValueError):
            update_setting(
                session, actor_user_id=admin.id, token_limit_per_person=bad, ai_enabled=True
            )


def test_two_requests_at_once_cannot_both_pass_when_only_one_fits(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin, limit=1_000)
    person = _person(session)

    reserve(session, person.id, request_id="first", estimate=1_000, feature_enabled=True)
    with pytest.raises(AiBlocked) as blocked:
        reserve(session, person.id, request_id="second", estimate=10, feature_enabled=True)

    assert blocked.value.code == "AI_LIMIT_REACHED"


def test_estimated_call_must_fit_remaining_allowance_before_it_starts(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin, limit=1_000)
    person = _person(session)
    month = reserve(session, person.id, request_id="first", estimate=900, feature_enabled=True)
    settle(
        session, person.id, month=month, request_id="first", hub_id=None, channel="web",
        provider="openai", model="test-model", prompt_version="v1", input_tokens=900,
        output_tokens=0, outcome="completed",
    )

    with pytest.raises(AiBlocked) as blocked:
        reserve(session, person.id, request_id="too-large", estimate=101, feature_enabled=True)

    assert blocked.value.code == "AI_LIMIT_REACHED"
    assert reserve(
        session, person.id, request_id="fits", estimate=100, feature_enabled=True
    ) == month


def test_settle_counts_real_tokens_and_remaining_never_below_zero(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin, limit=1_000)
    person = _person(session)
    month = reserve(session, person.id, request_id="r1", estimate=900, feature_enabled=True)

    # AI-09: an answer that already started may finish and is fully counted.
    settle(
        session, person.id, month=month, request_id="r1", hub_id=None, channel="web",
        provider="openai", model="m", prompt_version="v1", input_tokens=700,
        output_tokens=600, outcome="completed",
    )
    view = usage_view(session, person.id, feature_enabled=True)

    assert view.tokens_used == 1_300
    assert view.tokens_remaining == 0
    assert view.status == "limit_reached"
    assert session.scalar(select(func.count()).select_from(LlmUsage)) == 1


def test_usage_counts_across_hubs_for_the_same_person(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin)
    person = _person(session)
    for request_id in ("hub-a", "hub-b"):
        month = reserve(session, person.id, request_id=request_id, estimate=50,
                        feature_enabled=True)
        settle(session, person.id, month=month, request_id=request_id, hub_id=None,
               channel="web", provider="openai", model="m", prompt_version="v1",
               input_tokens=40, output_tokens=10, outcome="completed")

    assert usage_view(session, person.id, feature_enabled=True).tokens_used == 100


def test_stale_reservations_are_released(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin)
    person = _person(session)
    old = datetime.now(UTC) - timedelta(minutes=11)
    reserve(session, person.id, request_id="stuck", estimate=500, feature_enabled=True, now=old)

    assert release_stale_reservations(session) == 1
    row = session.scalar(select(AiAllowance))
    assert row.tokens_reserved == 0 and row.reservations == []


def test_manual_reset_zeroes_this_month_keeps_history_and_is_logged(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin, limit=1_000)
    person = _person(session)
    month = reserve(session, person.id, request_id="r1", estimate=100, feature_enabled=True)
    settle(session, person.id, month=month, request_id="r1", hub_id=None, channel="web",
           provider="openai", model="m", prompt_version="v1", input_tokens=900,
           output_tokens=200, outcome="completed")

    before = reset_person_usage(session, actor_user_id=admin.id, user_id=person.id)

    assert before == 1_100
    assert usage_view(session, person.id, feature_enabled=True).status == "active"
    assert session.scalar(select(func.count()).select_from(LlmUsage)) == 1
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "ai_allowance_reset"))
    assert event.old_value["tokens_used"] == 1_100 and event.actor_user_id == admin.id


def test_setting_changes_are_logged(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin)
    actions = set(session.scalars(select(AuditEvent.action)))
    assert {"ai_setting_changed", "ai_enabled_changed"} <= actions


def test_gateway_success_records_usage_and_exports_safe_record(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin)
    session.commit()
    exported: list[AiCallRecord] = []

    async def provider(settings, *, instructions, prompt, hub_code):
        return "It works.", "test-model", 20, 5

    answer = asyncio.run(
        run_ai_call(session, _settings(), user_id=admin.id, hub_id=None, hub_code=None,
                    instructions="check", prompt="hello", prompt_version="v1",
                    provider_call=provider, export=exported.append)
    )

    assert answer.text == "It works."
    view = usage_view(session, admin.id, feature_enabled=True)
    assert view.tokens_used == 25 and view.tokens_reserved == 0
    assert exported[0].outcome == "completed" and exported[0].input_tokens == 20


def test_gateway_provider_failure_releases_reservation_and_counts_billed_tokens(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin)
    session.commit()

    async def provider(settings, *, instructions, prompt, hub_code):
        raise ProviderError(input_tokens=12, output_tokens=0)

    with pytest.raises(GrpError) as error:
        asyncio.run(
            run_ai_call(session, _settings(), user_id=admin.id, hub_id=None, hub_code=None,
                        instructions="check", prompt="hello", prompt_version="v1",
                        provider_call=provider)
        )

    assert error.value.code == "AI_USAGE_UNAVAILABLE"
    view = usage_view(session, admin.id, feature_enabled=True)
    assert view.tokens_used == 12 and view.tokens_reserved == 0
    assert session.scalar(select(LlmUsage.outcome)) == "provider_error"


def test_gateway_limit_message_names_the_reset_date(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin, limit=1_000)
    month = reserve(session, admin.id, request_id="r0", estimate=1, feature_enabled=True)
    settle(session, admin.id, month=month, request_id="r0", hub_id=None, channel="web",
           provider="openai", model="m", prompt_version="v1", input_tokens=1_000,
           output_tokens=0, outcome="completed")
    session.commit()

    with pytest.raises(GrpError) as error:
        asyncio.run(
            run_ai_call(session, _settings(), user_id=admin.id, hub_id=None, hub_code=None,
                        instructions="x", prompt="y", prompt_version="v1")
        )

    assert error.value.code == "AI_LIMIT_REACHED" and error.value.status_code == 429
    assert "It resets on" in error.value.message
    assert "Maps, analysis and downloads still work." in error.value.message


def test_gateway_does_not_call_provider_when_estimate_exceeds_balance(session) -> None:
    admin = _person(session, "owner@example.test", admin=True)
    _enable(session, admin, limit=1_000)
    month = reserve(session, admin.id, request_id="r0", estimate=1, feature_enabled=True)
    settle(
        session, admin.id, month=month, request_id="r0", hub_id=None, channel="web",
        provider="openai", model="m", prompt_version="v1", input_tokens=950,
        output_tokens=0, outcome="completed",
    )
    session.commit()
    called = False

    async def provider(settings, *, instructions, prompt, hub_code):
        nonlocal called
        called = True
        return "unexpected", "test-model", 1, 1

    with pytest.raises(GrpError) as error:
        asyncio.run(
            run_ai_call(
                session, _settings(), user_id=admin.id, hub_id=None, hub_code=None,
                instructions="check", prompt="hello", prompt_version="v1",
                provider_call=provider,
            )
        )

    assert error.value.code == "AI_LIMIT_REACHED"
    assert called is False
    assert usage_view(session, admin.id, feature_enabled=True).tokens_used == 950


def test_langfuse_batch_contains_no_private_text() -> None:
    now = datetime.now(UTC)
    record = AiCallRecord("req-1", "user-uuid", "adpc", "web", "gpt", "v1", 10, 3,
                          "completed", now, now)
    batch = build_batch(Settings(_env_file=None), record)
    body = json.dumps(batch)

    assert "user-uuid" not in body
    assert person_reference("user-uuid") in body
    generation = batch["batch"][1]["body"]
    assert generation["usage"]["total"] == 13 and generation["model"] == "gpt"


def test_langfuse_sends_with_basic_auth_when_configured(tmp_path) -> None:
    secret = tmp_path / "langfuse_secret"
    secret.write_text("sk-lf-test", encoding="utf-8")
    settings = Settings(
        _env_file=None, LANGFUSE_HOST="https://cloud.langfuse.test",
        langfuse_public_key="pk-lf-test", langfuse_secret_key_file=secret,
    )
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(207, json={"successes": [], "errors": []})

    now = datetime.now(UTC)
    record = AiCallRecord("req-1", "u", None, "web", "gpt", "v1", 1, 1, "completed", now, now)

    async def run() -> bool:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await send_ai_call(settings, record, client=client)

    assert asyncio.run(run()) is True
    assert seen[0].url.path == "/api/public/ingestion"
    assert seen[0].headers["authorization"].startswith("Basic ")


def test_langfuse_is_skipped_without_configuration() -> None:
    now = datetime.now(UTC)
    record = AiCallRecord("req-1", "u", None, "web", "gpt", "v1", 1, 1, "completed", now, now)
    assert asyncio.run(send_ai_call(Settings(_env_file=None), record)) is False
