"""ADR-0004 planner chat box and map: gateway accounting, SIG sequence, area check, receipts."""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

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
from api.planning_cache import planning_answer_cache
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from api.sig_evidence import check_area, embed_url, verified_hazard_embed
from api.token_store import session_token_store
from core.access_models import AppUser, AuditEvent, Base
from core.ai_allowance import update_setting
from core.ai_models import LlmUsage
from core.assessment_models import Boundary, Dataset, DatasetVersion
from core.data_library_models import AreaPopulationSummary
from core.identity import IdentityLinkResult
from core.risk_recipe import RiskRecipe
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub

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


def test_real_boundary_match_includes_the_province_name() -> None:
    boundary = SimpleNamespace(name="MUEANG NAN", province_name="NAN")

    assert (
        api.planning._match_boundary(
            [boundary], "Mueang Nan District, Nan, Thailand"
        )
        is boundary
    )


def test_canonical_sig_place_includes_level_province_and_country() -> None:
    boundary = SimpleNamespace(
        name="KANTHARAROM",
        province_name="SI SA KET",
        admin_level="district",
        country_name="Thailand",
    )

    assert (
        api.planning._canonical_sig_place(boundary)
        == "KANTHARAROM District, SI SA KET, Thailand"
    )


def test_canonical_sig_place_uses_the_recorded_country_not_a_constant() -> None:
    boundary = SimpleNamespace(
        name="Chittagong",
        province_name="Chattogram",
        admin_level="district",
        country_name="Bangladesh",
    )

    assert (
        api.planning._canonical_sig_place(boundary)
        == "Chittagong District, Chattogram, Bangladesh"
    )


def test_canonical_sig_place_declines_a_boundary_with_no_recorded_country() -> None:
    boundary = SimpleNamespace(
        name="Synthetic Test District",
        province_name=None,
        admin_level="district",
        country_name=None,
    )

    assert api.planning._canonical_sig_place(boundary) is None


def test_sig_context_boundary_keeps_the_subdistrict_when_no_parent_district_is_loaded() -> None:
    subdistrict = SimpleNamespace(admin_level="subdistrict", admin_code="330301")

    assert api.planning._sig_context_boundary(subdistrict, []) is subdistrict


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
            {"type": "text", "text": '<iframe src="https://sig.example/account">'},
            {"type": "text", "text": '<iframe src="https://sig.example/embed/hazard_map/r1">'},
        ],
        structured_content={},
        is_error=False,
    )
    assert embed_url(result, "sig.example") == "https://sig.example/embed/hazard_map/r1"
    assert embed_url(result, "other.example") is None


def test_embed_url_rejects_non_hazard_component_on_sig_host() -> None:
    result = McpToolResult(
        content=[
            {"type": "text", "text": '<iframe src="https://sig.example/embed/provenance_graph/r1">'},
        ],
        structured_content={},
        is_error=False,
    )

    assert embed_url(result, "sig.example") is None


@pytest.mark.parametrize("layer", ["hazard_flood", "flood_rp10", "flood_rp100.tif"])
def test_verified_hazard_embed_accepts_declared_flood_layer(layer: str) -> None:
    result = McpToolResult(
        content=[
            {"type": "text", "text": '<iframe src="https://sig.example/embed/hazard_map/r1">'},
        ],
        structured_content={"displayed_layer": layer},
        is_error=False,
    )

    checked = verified_hazard_embed(result, "sig.example")

    assert checked.verified
    assert checked.url == "https://sig.example/embed/hazard_map/r1"
    assert checked.displayed_layer == layer


@pytest.mark.parametrize(
    "structured",
    [
        {},
        {"displayed_layer": "risk_flood_l2"},
        {"displayed_layer": "flood_unknown"},
        {"displayed_layer": ["hazard_flood", "flood_rp100"]},
    ],
    ids=["missing", "risk", "unknown", "multiple"],
)
def test_verified_hazard_embed_stops_on_missing_or_risk_layer(structured: dict) -> None:
    result = McpToolResult(
        content=[
            {"type": "text", "text": '<iframe src="https://sig.example/embed/hazard_map/r1">'},
        ],
        structured_content=structured,
        is_error=False,
    )

    checked = verified_hazard_embed(result, "sig.example")

    assert not checked.verified
    assert checked.url is None


def test_verified_embed_accepts_declared_risk_layer_only_after_recipe_approval() -> None:
    result = McpToolResult(
        content=[
            {"type": "text", "text": '<iframe src="https://sig.example/embed/hazard_map/r1">'},
        ],
        structured_content={"displayed_layer": "risk_flood_l2"},
        is_error=False,
    )

    checked = verified_hazard_embed(result, "sig.example", allow_risk=True)

    assert checked.verified
    assert checked.layer_kind == "risk"
    assert checked.url == "https://sig.example/embed/hazard_map/r1"


def test_mvp1_screen_hides_risk_sources_and_stats_without_an_approved_recipe() -> None:
    pack = {
        **PACK,
        "stats": {
            "counts": {"schools": {"exposed": 3}},
            "population_by_age": {"age_65_plus": 120},
            "risk_levels": {"schools": {"high": 0}},
            "severity": 2,
            "vulnerability_score": 0.72,
        },
        "citations": [
            PACK["citations"][0],
            {
                "n": 5,
                "title": "buildings by risk level (flood)",
                "source": "platform Layer-2 engine (conf/risk_l2.yml)",
                "text": "0 buildings at high risk",
            },
        ],
    }

    screened = api.planning._screen_pack_for_mvp1(pack)

    assert [item["n"] for item in screened["citations"]] == [1]
    assert screened["stats"] == {
        "counts": {"schools": {"exposed": 3}},
        "population_by_age": {"age_65_plus": 120},
    }
    assert "G-16" in api.planning._evidence_contract_warnings(screened)[0]


def test_approved_recipe_preserves_sig_risk_and_demographic_evidence() -> None:
    pack = {
        **PACK,
        "stats": {
            "population_by_age": {"age_65_plus": 120},
            "risk_levels": {"schools": {"high": 2}},
        },
        "citations": [
            *PACK["citations"],
            {"n": 2, "title": "schools by risk level", "text": "2 schools at high risk"},
        ],
    }
    recipe = RiskRecipe(
        key="thailand-flood-risk",
        version="approved-v1",
        weights={"population": 0.4, "building_density": 0.35, "road_distance": 0.25},
        missing_data_policy="unable_to_assess",
        science_owner="Science owner",
        source_ref="SIG recipe receipt",
        change_reason="Approved for test",
        status="approved",
        is_active=True,
        approved_at=datetime.now(UTC),
    )

    screened = api.planning._screen_pack_for_mvp1(pack, recipe)

    assert [item["n"] for item in screened["citations"]] == [1, 2]
    assert screened["stats"]["risk_levels"]["schools"]["high"] == 2
    assert screened["stats"]["population_by_age"]["age_65_plus"] == 120
    assert screened["_grp_risk_recipe"]["version"] == "approved-v1"


def test_draft_preflight_rejects_unapproved_risk_classification() -> None:
    issues = api.planning._draft_issues(
        "## What the numbers show\n0 buildings are at high risk [1]",
        ["## What the numbers show"],
        [{"n": 1}],
    )

    assert any("unapproved vulnerability-weighted risk level" in issue for issue in issues)


def test_deterministic_summary_marks_truncation_and_preserves_cross_references() -> None:
    long_text = "See the registered method [12]. " + "A long evidence sentence. " * 80
    pack = {
        **PACK,
        "citations": [
            {"n": 1, "text": f"{long_text} [1]", "retrieval": "computed-at-pack-time"},
        ],
    }

    answer = api.planning._deterministic_evidence_summary(
        pack, movement_unavailable=False
    )

    assert "[12]" in answer
    assert "… (full text in Evidence) [1]" in answer
    assert len(answer.split("## Key SIG findings\n", 1)[1].split("\n", 1)[0]) < len(long_text)


def test_deterministic_summary_reports_findings_hidden_by_display_limit() -> None:
    pack = {
        **PACK,
        "citations": [
            {"n": number, "text": f"Computed finding {number}",
             "retrieval": "computed-at-pack-time"}
            for number in range(1, 11)
        ],
    }

    answer = api.planning._deterministic_evidence_summary(
        pack, movement_unavailable=False
    )

    assert "Plus 4 more numbered finding(s) in the Evidence tab" in answer


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
    embed_layer: str | None = "hazard_flood"

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
            {"displayed_layer": FakeMcp.embed_layer} if FakeMcp.embed_layer else {},
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
    FakeMcp.embed_layer = "hazard_flood"

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
        boundary = Boundary(
            admin_code="3303",
            admin_level="district",
            name="KANTHARAROM",
            name_th="กันทรารมย์",
            province_name="SI SA KET",
            province_name_th="ศรีสะเกษ",
            country_name="Thailand",
            geom={
                "type": "Polygon",
                "coordinates": [[[104.5, 15.0], [104.7, 15.0], [104.7, 15.2],
                                 [104.5, 15.2], [104.5, 15.0]]],
            },
            source="Thailand hierarchy delivery",
            edition="2025-10",
            geometry_sha256="c" * 64,
            is_supported=True,
        )
        session.add(boundary)
        update_setting(session, actor_user_id=owner.id, token_limit_per_person=100_000,
                       ai_enabled=True)
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}
        boundary_id = str(boundary.id)

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    planning_answer_cache.clear()
    try:
        yield {"settings": settings, "engine": engine, "users": users, "replies": replies,
               "boundary_id": boundary_id, "monkeypatch": monkeypatch}
    finally:
        planning_answer_cache.clear()
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
    assert "available Thailand district" in body["answer"]


def test_result_explanation_prompt_reports_missing_result_even_if_router_refuses(planning) -> None:
    planning["replies"].append('{"mode": "cannot", "reply": ""}')

    body = _ask(
        _client(planning, "planner@example.test"),
        message="Explain the result: which evacuation centers may be exposed and why?",
    ).json()

    assert body["mode"] == "needs_result"
    assert body["label"] == "No result to explain yet."


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
    assert body["answer_source"] == "ai_draft"
    assert body["area"]["verified"] is True
    assert body["receipt"] is None and body["map_url"] is None
    assert "Unverified draft" in body["label"]
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack"]
    assert body["usage"]["tokens_used"] == 140
    with Session(planning["engine"]) as session:
        assert session.scalar(select(func.count()).select_from(LlmUsage)) == 2
        assert "planning_sig_evidence" in set(session.scalars(select(AuditEvent.action)))


def test_same_sig_question_uses_session_cache_and_refresh_bypasses_it(planning) -> None:
    planning["replies"] += [
        '{"mode": "sig_flood", "reply": ""}',
        "## What the numbers show\n3 [1]",
    ]
    client = _client(planning, "planner@example.test")
    question = "Which schools are exposed?"

    first = _ask(
        client,
        message=question,
        place="Mueang Nan District, Nan, Thailand",
    ).json()
    cached = _ask(client, message=question).json()

    assert first.get("cached") is None
    assert cached["cached"] is True
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack"]

    planning["replies"] += [
        '{"mode": "sig_flood", "reply": ""}',
        "## What the numbers show\n3 [1]",
    ]
    refreshed = _ask(
        client,
        message=question,
        place="Mueang Nan District, Nan, Thailand",
        refresh=True,
    ).json()

    assert refreshed.get("cached") is None
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack", "assemble_pack"]


def test_confirmed_area_overrides_a_different_model_place(planning) -> None:
    planning["replies"] += [
        '{"mode": "sig_flood", "reply": "", "place": "Phaya Thai District, Bangkok"}',
        "## What the numbers show\n3 [1]",
    ]

    response = _ask(
        _client(planning, "planner@example.test"),
        message="Which schools are exposed in Mueang Nan District?",
        place="Mueang Nan District, Nan, Thailand",
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "sig_evidence"
    assert FakeMcp.calls[0][1]["place"] == "Mueang Nan District, Nan, Thailand"


def test_selected_boundary_enriches_short_confirmed_place_before_sig(planning) -> None:
    planning["replies"] += [
        '{"mode": "sig_flood", "reply": ""}',
        "## What the numbers show\n3 [1]",
    ]
    FakeMcp.pack = {
        **PACK,
        "stats": {"place": "Kanthararom District"},
        "trace": [
            "aoi[Kanthararom District] 664 km2 via admin boundary ~664 km²",
            "clip[hazard_flood]",
        ],
    }

    response = _ask(
        _client(planning, "planner@example.test"),
        message="Show supporting SIG flood information for KANTHARAROM.",
        place="KANTHARAROM",
        boundary_id=planning["boundary_id"],
    )

    assert response.status_code == 200, response.json()
    assert response.json()["mode"] == "sig_evidence"
    assert FakeMcp.calls[0][1]["place"] == "KANTHARAROM District, SI SA KET, Thailand"


def test_model_only_sig_area_needs_confirmation_before_any_sig_call(planning) -> None:
    planning["replies"].append(
        '{"mode": "sig_flood", "reply": "", "place": "Mueang Nan District, Nan, Thailand"}'
    )

    response = _ask(
        _client(planning, "planner@example.test"),
        message="Which schools are exposed in Nan?",
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "needs_area_confirmation"
    assert response.json()["place"] == "Mueang Nan District, Nan, Thailand"
    assert FakeMcp.calls == []


def test_publish_checkbox_issues_receipt_and_map(planning) -> None:
    planning["replies"] += ['{"mode": "sig_flood", "reply": ""}', "## What the numbers show\n3 [1]"]
    client = _client(planning, "planner@example.test")
    draft = _ask(
        client,
        message="Which schools are exposed?",
        place="Mueang Nan District, Nan, Thailand",
    ).json()
    assert draft["publish_token"]
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack"]

    body = _ask(
        client,
        message="Which schools are exposed?",
        publish_receipt=True,
        publish_token=draft["publish_token"],
    ).json()

    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack", "publish_answer", "ui_embed"]
    assert FakeMcp.calls[1][1] == {
        "pack_id": "pack-123",
        "draft": draft["answer"],
        "question": "Which schools are exposed?",
    }
    assert planning["replies"] == []  # publication did not call the model again
    assert body["receipt"]["receipt_id"] == "receipt-1"
    assert body["map_url"] == "https://sig.example/embed/hazard_map/r1"
    assert body["map_kind"] == "flood_hazard_and_asset_exposure"
    assert body["map_note"] == "Displayed flood-hazard layer verified."
    with Session(planning["engine"]) as session:
        assert "sig_receipt_published" in set(session.scalars(select(AuditEvent.action)))


def test_publish_accepts_explicit_risk_layer_under_approved_recipe(planning) -> None:
    planning["replies"] += ['{"mode": "sig_flood", "reply": ""}', "## What the numbers show\n3 [1]"]
    FakeMcp.embed_layer = "risk_flood_l2"
    client = _client(planning, "planner@example.test")
    draft = _ask(
        client,
        message="Which schools are exposed?",
        place="Mueang Nan District, Nan, Thailand",
    ).json()

    body = _ask(
        client,
        message="Which schools are exposed?",
        publish_receipt=True,
        publish_token=draft["publish_token"],
    ).json()

    assert body["receipt"]["receipt_id"] == "receipt-1"
    assert body["map_url"] == "https://sig.example/embed/hazard_map/r1"
    assert body["map_kind"] == "sig_vulnerability_weighted_flood_risk"
    assert "risk layer verified" in body["map_note"]
    assert body["evidence"]["risk_recipe"]["version"] == "sig-current-2026-09-22"
    assert body["trace"][-1]["detail"] == "embedded risk_flood_l2"


def test_gate_blocked_draft_is_not_shown(planning) -> None:
    planning["replies"] += [
        '{"mode": "sig_flood", "reply": ""}',
        "## What the numbers show\nSECRET DRAFT [1]",
    ]
    FakeMcp.publish = {"status": "blocked", "failures": ["citation [9] not in pack"]}
    try:
        client = _client(planning, "planner@example.test")
        draft = _ask(
            client,
            message="Which schools are exposed?",
            place="Mueang Nan District, Nan, Thailand",
        ).json()
        body = _ask(
            client,
            message="Which schools are exposed?",
            publish_receipt=True,
            publish_token=draft["publish_token"],
        ).json()
    finally:
        FakeMcp.publish = {"status": "ok", "receipt_id": "receipt-1",
                           "public_resolver": "https://sig.example/r/receipt-1"}

    assert body["mode"] == "gate_blocked"
    assert "SECRET DRAFT" not in json.dumps(body)
    assert "citation [9] not in pack" in body["answer"]
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack", "publish_answer"]


def test_non_ok_publish_status_never_requests_an_embed(planning) -> None:
    planning["replies"] += [
        '{"mode": "sig_flood", "reply": ""}',
        "## What the numbers show\nDRAFT [1]",
    ]
    FakeMcp.publish = {
        "status": "declined",
        "receipt_id": "must-not-be-used",
        "note": "Publication is unavailable.",
    }
    try:
        client = _client(planning, "planner@example.test")
        draft = _ask(
            client,
            message="Which schools are exposed?",
            place="Mueang Nan District, Nan, Thailand",
        ).json()
        body = _ask(
            client,
            message="Which schools are exposed?",
            publish_receipt=True,
            publish_token=draft["publish_token"],
        ).json()
    finally:
        FakeMcp.publish = {
            "status": "ok",
            "receipt_id": "receipt-1",
            "public_resolver": "https://sig.example/r/receipt-1",
        }

    assert body["mode"] == "gate_blocked"
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack", "publish_answer"]
    assert "Publication is unavailable." in body["answer"]


def test_incomplete_draft_uses_non_publishable_deterministic_summary(planning) -> None:
    planning["replies"] += [
        '{"mode": "sig_flood", "reply": ""}',
        "####\nUNCITED MODEL CLAIM\n####",
    ]

    body = _ask(
        _client(planning, "planner@example.test"),
        message="Which schools are exposed?",
        place="Mueang Nan District, Nan, Thailand",
    ).json()

    assert body["mode"] == "sig_evidence"
    assert body["answer_source"] == "deterministic_fallback"
    assert "3 of 9 schools [1]" in body["answer"]
    assert "UNCITED MODEL CLAIM" not in body["answer"]
    assert "not current flooding" in body["answer"]
    assert body["publish_token"] is None
    assert "Missing required heading" in body["draft_issues"][0]
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack"]


def test_publish_requires_a_valid_reviewed_draft_token(planning) -> None:
    client = _client(planning, "planner@example.test")
    missing = _ask(
        client, message="Which schools are exposed?", publish_receipt=True
    )
    tampered = _ask(
        client,
        message="Which schools are exposed?",
        publish_receipt=True,
        publish_token="invalid-token",
    )

    assert missing.status_code == 422
    assert tampered.status_code == 409
    assert FakeMcp.calls == []
    assert planning["replies"] == []


def test_fallback_area_stops_before_drafting(planning) -> None:
    planning["replies"].append('{"mode": "sig_flood", "reply": ""}')
    FakeMcp.pack = {**PACK, "trace": ["aoi[Ku Thong] 452 km2 via 12 km radius box"],
                    "stats": {"place": "Ku Thong"}}

    body = _ask(
        _client(planning, "planner@example.test"),
        message="Which schools are exposed?",
        place="Ku Thong, Thailand",
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
    # The page shows the time left so a planner can finish before the connection ends.
    assert 3000 < connected["sig_expires_in_seconds"] <= 3600
    assert disconnected["sig_connected"] is False
    assert disconnected["sig_expires_in_seconds"] is None


def test_router_is_told_to_return_english_place_names() -> None:
    assert "romanized" in api.planning.ROUTER_INSTRUCTIONS
    assert "Chiang Yuen District, Maha" in api.planning.ROUTER_INSTRUCTIONS


def test_evidence_bundle_counts_sources_and_keeps_traces() -> None:
    pack = {
        **PACK,
        "citations": [
            {"n": 1, "kind": "exposure", "retrieval": "computed-at-pack-time", "title": "a"},
            {"n": 2, "kind": "feed", "retrieval": "pulled-live", "title": "b"},
            {"n": 3, "kind": "gaps", "title": "c"},
        ],
        "exec": {"assembled_at": "2026-09-17T01:00:00Z", "gather_ms": 1200.5},
    }
    bundle = api.planning.evidence_bundle(
        "Where could people move?", "Pua District, Nan, Thailand", pack,
        {"verified": True}, [{"step": "assemble_pack", "detail": "pack-123"}], None,
    )

    assert bundle["summary"] == {"sources": 3, "pulled_live": 1, "computed": 1,
                                 "declared_gaps": 1}
    assert bundle["sig_trace"][0].startswith("aoi[")
    assert bundle["grp_trace"][0]["step"] == "assemble_pack"
    assert bundle["gather_ms"] == 1200.5
    assert bundle["warnings"] == []


def test_evidence_bundle_flags_conflicting_return_period_metadata() -> None:
    pack = {
        **PACK,
        "citations": [
            {"n": 1, "title": "100-year flood hazard", "text": "Hazard classes 1 to 5"},
        ],
        "gaps": ["no return period: this hazard layer is a single scenario"],
    }

    bundle = api.planning.evidence_bundle(
        "What is exposed?", "Mueang Nan District, Nan, Thailand", pack,
        {"verified": True}, [], None,
    )

    assert len(bundle["warnings"]) == 1
    assert "return period" in bundle["warnings"][0]


def test_where_could_people_move_in_unsupported_area_falls_back_to_sig(planning) -> None:
    planning["replies"] += [
        '{"mode": "run_assessment", "reply": "", "place": "Mueang Nan District, Nan, Thailand",'
        ' "return_period_years": null}',
        '{"mode": "run_assessment", "reply": "", "place": "Mueang Nan District, Nan, Thailand",'
        ' "return_period_years": null}',
        "## What the numbers show\nNo evacuation centers are in the evidence. 3 schools [1]",
    ]

    client = _client(planning, "planner@example.test")
    proposed = _ask(
        client,
        message="where could people move if flood happen in เมืองน่าน",
    ).json()
    assert proposed["mode"] == "needs_area_confirmation"
    assert FakeMcp.calls == []

    body = _ask(
        client,
        message="where could people move if flood happen in เมืองน่าน",
        place=proposed["place"],
    ).json()

    assert body["mode"] == "sig_evidence"
    assert body["note"] is None
    assert body["evidence"]["summary"]["sources"] == 1
    assert [name for name, _ in FakeMcp.calls] == ["assemble_pack"]
    assert FakeMcp.calls[0][1]["place"] == "Mueang Nan District, Nan, Thailand"


def test_display_request_with_bad_draft_still_shows_structured_data(planning) -> None:
    planning["replies"] += [
        '{"mode": "run_assessment", "reply": "", "place": "Mueang Nan District, Nan, Thailand",'
        ' "return_period_years": null}',
        "uncited and malformed draft",
    ]

    body = _ask(
        _client(planning, "planner@example.test"),
        message="Where could people move in Mueang Nan?",
        place="Mueang Nan District, Nan, Thailand",
    ).json()

    assert body["answer_source"] == "deterministic_fallback"
    assert body["answer"].startswith(
        "## Available data\nSIG returned the following cited flood information"
    )
    assert "3 of 9 schools [1]" in body["answer"]
    assert body["publish_token"] is None


def test_publish_token_is_dropped_when_the_pack_is_too_large(planning, monkeypatch) -> None:
    monkeypatch.setattr(api.planning, "PUBLISH_TOKEN_MAX_CHARS", 10)
    planning["replies"] += [
        '{"mode": "sig_flood", "reply": "", "place": "Mueang Nan District, Nan, Thailand",'
        ' "return_period_years": null}',
        "## What the numbers show\n3 of 9 schools are in the flood area [1]",
    ]

    body = _ask(
        _client(planning, "planner@example.test"),
        message="Which schools are exposed?",
        place="Mueang Nan District, Nan, Thailand",
    ).json()

    assert body["mode"] == "sig_evidence"
    assert body["publish_token"] is None
    assert body["draft_issues"] == ["This evidence pack is too large to publish from this screen"]


# --- background lookups (ADR-0025) -----------------------------------------------------


def test_a_lookup_runs_in_the_background_and_returns_the_same_answer(planning) -> None:
    """A slow SIG gather must not be held open by a web request."""

    planning["replies"].append('{"mode": "chat", "reply": "Hazard is not risk."}')
    client = _client(planning, "planner@example.test")

    started = client.post(
        "/api/v1/planning/lookups",
        json={"message": "What is hazard?", "hub_code": "adpc"},
    )
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    assert started.json()["state"] in {"queued", "running"}

    polled = client.get(f"/api/v1/planning/lookups/{job_id}")
    body = polled.json()
    assert polled.status_code == 200
    assert body["state"] == "succeeded"
    assert body["answer"]["answer"] == "Hazard is not risk."
    assert body["elapsed_seconds"] >= 0


def test_a_lookup_belongs_to_the_session_that_started_it(planning) -> None:
    planning["replies"].append('{"mode": "chat", "reply": "Hazard is not risk."}')
    owner = _client(planning, "planner@example.test")
    job_id = owner.post(
        "/api/v1/planning/lookups",
        json={"message": "What is hazard?", "hub_code": "adpc"},
    ).json()["job_id"]

    other = _client(planning, "owner@example.test")

    # Not refused but not found: another session's lookup is not theirs to know exists.
    assert other.get(f"/api/v1/planning/lookups/{job_id}").status_code == 404
    assert owner.get(f"/api/v1/planning/lookups/{job_id}").status_code == 200


def test_an_unknown_lookup_is_not_found(planning) -> None:
    client = _client(planning, "planner@example.test")

    assert client.get(f"/api/v1/planning/lookups/{uuid4()}").status_code == 404


def test_a_lookup_refuses_a_hub_the_person_does_not_plan_for(planning) -> None:
    """The membership check happens in the request, so a refusal is immediate."""

    client = _client(planning, "planner@example.test")

    response = client.post(
        "/api/v1/planning/lookups",
        json={"message": "What is hazard?", "hub_code": "other"},
    )

    assert response.status_code == 404


def test_grp_population_reaches_the_brief_beside_sig_evidence(planning) -> None:
    """ADR-0028 slice 1: the model is given GRP's own rows for the verified area."""

    prompts: list[str] = []
    instruction_log: list[str] = []

    async def capturing(settings, *, instructions, prompt, hub_code):
        prompts.append(prompt)
        instruction_log.append(instructions)
        return planning["replies"].pop(0), "test-model", 50, 20

    planning["monkeypatch"].setattr(api.ai_gateway, "call_openai", capturing)
    FakeMcp.pack = {
        **PACK,
        "target": {"place": "Kanthararom District, Si Sa Ket, Thailand", "hazard": "flood"},
        "trace": ["aoi[Kanthararom District] 41 km2 via admin boundary ~41 km²"],
    }
    with Session(planning["engine"]) as session:
        dataset = Dataset(
            type="village_locations", owner_kind="platform", title="Villages", provider="ADPC"
        )
        session.add(dataset)
        session.flush()
        version = DatasetVersion(dataset_id=dataset.id, sha256="d" * 64, is_current=True)
        session.add(version)
        session.flush()
        session.add(
            AreaPopulationSummary(
                dataset_version_id=version.id,
                admin_code="3303",
                admin_level="district",
                village_count=175,
                counted_village_count=174,
                excluded_village_count=1,
                male=43309,
                female=42259,
                total_population=85568,
                households=23594,
            )
        )
        session.commit()
    planning["replies"] += ['{"mode": "sig_flood", "reply": ""}', "## What the numbers show\n3 [1]"]

    response = _ask(
        _client(planning, "planner@example.test"),
        message="How many people live there?",
        place="Kanthararom District, Si Sa Ket, Thailand",
    )

    body = response.json()
    assert response.status_code == 200, body
    assert body["area"]["verified"] is True
    draft_prompt = prompts[-1]
    # GRP's own figure is in the evidence the model may quote, numbered after SIG's.
    assert "85,568 registered residents" in draft_prompt
    assert '"n": 2' in draft_prompt
    assert "not a count of vulnerable people" in draft_prompt
    # And the model is told whose number it is, so it cannot attribute it to SIG.
    assert "GRP data library" in instruction_log[-1]


def test_a_place_grp_does_not_hold_attaches_no_local_evidence(planning) -> None:
    """An unmatched area must not borrow another district's numbers."""

    prompts: list[str] = []

    async def capturing(settings, *, instructions, prompt, hub_code):
        prompts.append(prompt)
        return planning["replies"].pop(0), "test-model", 50, 20

    planning["monkeypatch"].setattr(api.ai_gateway, "call_openai", capturing)
    planning["replies"] += ['{"mode": "sig_flood", "reply": ""}', "## What the numbers show\n3 [1]"]

    response = _ask(
        _client(planning, "planner@example.test"),
        message="How many people live there?",
        place="Mueang Nan District, Nan, Thailand",
    )

    assert response.status_code == 200, response.json()
    assert "registered residents" not in prompts[-1]
