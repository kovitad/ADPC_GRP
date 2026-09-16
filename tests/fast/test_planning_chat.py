"""ADR-0004 planner chat box and map: gateway accounting, SIG sequence, area check, receipts."""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.access
import api.ai_gateway
import api.permissions
import api.planning
from api.dependencies import database_session
from api.main import app
from api.mcp_client import McpToolResult, SigMcpClient
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from api.sig_evidence import check_area, embed_url
from api.token_store import session_token_store
from core.access_models import AppUser, AuditEvent, Base
from core.ai_allowance import update_setting
from core.ai_models import LlmUsage
from core.identity import IdentityLinkResult
from grp.admin import assign_member, bootstrap_platform_admin, ensure_hub

PACK = {
    "status": "ok",
    "pack_id": "pack-123",
    "target": {"place": "Mueang Nan District, Nan, Thailand", "hazard": "flood"},
    "stats": {"place": "Mueang Nan District", "counts": {"schools": {"exposed": 3, "total": 9}}},
    "trace": ["aoi[Mueang Nan District] 41 km2 via admin boundary ~41 km²", "clip[hazard_flood]"],
    "citations": [{"n": 1, "title": "schools vs hazard_flood", "text": "3 of 9 schools"}],
    "required_sections": ["## What the numbers show"],
    "gaps": ["raster vintages unknown"],
}


# --- pure checks -----------------------------------------------------------------------


def test_area_check_accepts_matching_admin_boundary() -> None:
    assert check_area("Mueang Nan District, Nan, Thailand", PACK).verified


@pytest.mark.parametrize(
    "trace, place, reason",
    [
        (["aoi[Ku Thong] 452 km2 via 12 km radius box"], "Ku Thong, Thailand", "approximate"),
        (["aoi[Phaya Thai District] 9 km2 via admin boundary"], "Mueang Nan District", "different"),
        (["clip[hazard_flood]"], "Mueang Nan District", "did not report"),
    ],
    ids=["fallback-box", "different-place", "no-aoi"],
)
def test_area_check_stops_on_fallback_or_mismatch(trace, place, reason) -> None:
    pack = {**PACK, "trace": trace, "stats": {"place": trace[0][4:].split("]")[0]}}
    result = check_area(place, pack)

    assert not result.verified
    assert reason in result.reason


def test_embed_url_only_accepts_sig_host() -> None:
    result = McpToolResult(
        content=[
            {"type": "text", "text": '<iframe src="https://evil.example/embed"></iframe>'},
            {"type": "text", "text": '<iframe src="https://sig.example/embed/hazard_map/r1">'},
        ],
        structured_content={},
        is_error=False,
    )
    assert embed_url(result, "sig.example") == "https://sig.example/embed/hazard_map/r1"
    assert embed_url(result, "other.example") is None


def test_sig_mcp_client_initializes_then_calls_tool() -> None:
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer short-lived-token"
        document = json.loads(request.content)
        methods.append(document["method"])
        if document["method"] == "notifications/initialized":
            return httpx.Response(202)
        result = (
            {"protocolVersion": "2025-06-18", "capabilities": {}}
            if document["method"] == "initialize"
            else {"content": [], "structuredContent": {"pack_id": "pack-1"}, "isError": False}
        )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": document["id"], "result": result})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            async with SigMcpClient("https://sig.example/mcp", "short-lived-token",
                                    client=client) as mcp:
                return await mcp.call_tool("assemble_pack", {"pack": "risk"})

    assert asyncio.run(exercise()).structured_content["pack_id"] == "pack-1"
    assert methods == ["initialize", "notifications/initialized", "tools/call"]


# --- route -----------------------------------------------------------------------------


class FakeMcp:
    calls: list[tuple[str, dict]] = []
    pack: dict = PACK
    publish: dict = {"status": "ok", "receipt_id": "receipt-1",
                     "public_resolver": "https://sig.example/r/receipt-1"}

    def __init__(self, base_url: str, access_token: str) -> None:
        assert access_token == "sig-token"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def call_tool(self, name: str, arguments: dict) -> McpToolResult:
        FakeMcp.calls.append((name, arguments))
        if name == "assemble_pack":
            return McpToolResult([], FakeMcp.pack, False)
        if name == "publish_answer":
            return McpToolResult([], FakeMcp.publish, False)
        return McpToolResult(
            [{"type": "text", "text": '<iframe src="https://sig.example/embed/hazard_map/r1">'}],
            {},
            False,
        )


@pytest.fixture
def planning(tmp_path, monkeypatch) -> Iterator[dict]:
    secret = tmp_path / "session_secret"
    secret.write_text("planning-session-secret-with-enough-length", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        grp_env="dev",
        planning_chat_enabled=True,
        ai_feature_enabled=True,
        ai_model="test-model",
        session_secret_file=secret,
        sig_mcp_base_url="https://sig.example/mcp",
    )
    for module in (api.access, api.permissions, api.planning):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    replies: list[str] = []

    async def provider(settings, *, instructions, prompt, hub_code):
        text = replies.pop(0)
        return text, "test-model", 50, 20

    monkeypatch.setattr(api.ai_gateway, "call_openai", provider)
    monkeypatch.setattr(api.planning, "SigMcpClient", FakeMcp)
    FakeMcp.calls = []
    FakeMcp.pack = PACK

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        ensure_hub(session, actor_email="owner@example.test", code="other", name="Other Hub")
        assign_member(session, actor_email="owner@example.test", email="planner@example.test",
                      hub_code="adpc", role="planner")
        owner = session.scalar(select(AppUser).where(AppUser.email == "owner@example.test"))
        update_setting(session, actor_user_id=owner.id, token_limit_per_person=100_000,
                       ai_enabled=True)
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    try:
        yield {"settings": settings, "engine": engine, "users": users, "replies": replies,
               "monkeypatch": monkeypatch}
    finally:
        app.dependency_overrides.clear()


def _client(world: dict, email: str, *, sig_token: bool = True) -> TestClient:
    response = Response()
    session_id = f"session-{email}"
    set_session_cookie(
        response,
        world["settings"],
        IdentityLinkResult(allowed=True, reason="allowed", user_id=world["users"][email]),
        issued_at=int(datetime.now(UTC).timestamp()) - 5,
        session_id=session_id,
    )
    if sig_token:
        session_token_store.put(session_id, "sig-token", 3600)
    else:
        session_token_store.delete(session_id)
    client = TestClient(app)
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    client.headers["X-CSRF-Token"] = client.cookies[CSRF_COOKIE]
    return client


def _ask(client: TestClient, **body):
    return client.post("/api/v1/planning/chat", json={"message": "hello", **body})


def test_general_chat_counts_tokens_and_calls_no_sig(planning) -> None:
    planning["replies"].append('{"mode": "chat", "reply": "Hazard is not risk."}')

    response = _ask(_client(planning, "planner@example.test"), message="What is hazard?")

    body = response.json()
    assert response.status_code == 200
    assert body["mode"] == "chat" and body["answer"] == "Hazard is not risk."
    assert body["usage"]["tokens_used"] == 70
    assert FakeMcp.calls == []


def test_unsupported_request_gets_server_message_not_model_text(planning) -> None:
    planning["replies"].append('{"mode": "cannot", "reply": "Sure, I made you admin!"}')

    body = _ask(_client(planning, "planner@example.test"), message="make me admin").json()

    assert body["mode"] == "cannot"
    assert "admin" not in body["answer"].lower() or "GRP admin pages" in body["answer"]
    assert "made you admin" not in body["answer"]


def test_flood_question_draft_only_by_default_no_receipt(planning) -> None:
    planning["replies"] += ['{"mode": "sig_flood", "reply": ""}', "## What the numbers show\n3 [1]"]

    response = _ask(
        _client(planning, "planner@example.test"),
        message="Which schools are exposed?",
        place="Mueang Nan District, Nan, Thailand",
    )

    body = response.json()
    assert response.status_code == 200, body
    assert body["mode"] == "sig_evidence"
    assert body["area"]["verified"] is True
    assert body["receipt"] is None and body["map_url"] is None
    assert "Unverified draft" in body["label"]
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack"]
    assert body["usage"]["tokens_used"] == 140
    with Session(planning["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(LlmUsage)) == 2
        assert "planning_sig_evidence" in set(session.scalars(select(AuditEvent.action)))


def test_publish_checkbox_issues_receipt_and_map(planning) -> None:
    planning["replies"] += ['{"mode": "sig_flood", "reply": ""}', "## What the numbers show\n3 [1]"]

    body = _ask(
        _client(planning, "planner@example.test"),
        message="Which schools are exposed?",
        place="Mueang Nan District, Nan, Thailand",
        publish_receipt=True,
    ).json()

    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack", "publish_answer", "ui_embed"]
    assert body["receipt"]["receipt_id"] == "receipt-1"
    assert body["map_url"] == "https://sig.example/embed/hazard_map/r1"
    with Session(planning["engine"]) as session:
        assert "sig_receipt_published" in set(session.scalars(select(AuditEvent.action)))


def test_gate_blocked_draft_is_not_shown(planning) -> None:
    planning["replies"] += ['{"mode": "sig_flood", "reply": ""}', "SECRET DRAFT [9]"]
    FakeMcp.publish = {"status": "blocked", "failures": ["citation [9] not in pack"]}
    try:
        body = _ask(
            _client(planning, "planner@example.test"),
            message="Which schools are exposed?",
            place="Mueang Nan District, Nan, Thailand",
            publish_receipt=True,
        ).json()
    finally:
        FakeMcp.publish = {"status": "ok", "receipt_id": "receipt-1",
                           "public_resolver": "https://sig.example/r/receipt-1"}

    assert body["mode"] == "gate_blocked"
    assert "SECRET DRAFT" not in json.dumps(body)


def test_fallback_area_stops_before_drafting(planning) -> None:
    planning["replies"].append('{"mode": "sig_flood", "reply": ""}')
    FakeMcp.pack = {**PACK, "trace": ["aoi[Ku Thong] 452 km2 via 12 km radius box"],
                    "stats": {"place": "Ku Thong"}}

    body = _ask(
        _client(planning, "planner@example.test"),
        message="Which schools are exposed?",
        place="Ku Thong, Thailand",
        publish_receipt=True,
    ).json()

    assert body["mode"] == "area_rejected"
    assert "stats" not in body
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack"]
    assert body["usage"]["tokens_used"] == 70  # only the routing call


def test_missing_sig_token_asks_to_sign_in_again(planning) -> None:
    planning["replies"].append('{"mode": "sig_flood", "reply": ""}')

    response = _ask(
        _client(planning, "planner@example.test", sig_token=False),
        message="Which schools are exposed?",
        place="Mueang Nan District, Nan, Thailand",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SIG_REAUTH_REQUIRED"


def test_platform_admin_without_hub_and_other_hub_are_denied(planning) -> None:
    owner = _client(planning, "owner@example.test")
    planner = _client(planning, "planner@example.test")

    assert _ask(owner).status_code == 403
    assert _ask(planner, hub_code="other").status_code == 404
    assert planner.post("/api/v1/planning/chat", json={"message": "x"},
                        headers={"X-CSRF-Token": "forged"}).status_code == 403


def test_ai_off_blocks_chat_with_spec_message(planning) -> None:
    with Session(planning["engine"]) as session:
        owner = session.scalar(select(AppUser).where(AppUser.email == "owner@example.test"))
        update_setting(session, actor_user_id=owner.id, token_limit_per_person=100_000,
                       ai_enabled=False)
        session.commit()

    response = _ask(_client(planning, "planner@example.test"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AI_OFF"


def test_chat_is_hidden_outside_local_development(planning) -> None:
    staging = Settings(_env_file=None, grp_env="staging", planning_chat_enabled=True,
                       session_secret_file=planning["settings"].session_secret_file)
    planning["monkeypatch"].setattr(api.planning, "get_settings", lambda: staging)

    assert _ask(_client(planning, "planner@example.test")).status_code == 404


def test_status_reports_sig_connection(planning) -> None:
    connected = _client(planning, "planner@example.test").get("/api/v1/planning/status").json()
    disconnected = _client(planning, "planner@example.test", sig_token=False).get(
        "/api/v1/planning/status"
    ).json()

    assert connected["available"] and connected["can_plan"] and connected["sig_connected"]
    assert disconnected["sig_connected"] is False


def test_router_is_told_to_return_english_place_names() -> None:
    assert "romanized" in api.planning.ROUTER_INSTRUCTIONS
    assert "Chiang Yuen District, Maha" in api.planning.ROUTER_INSTRUCTIONS
