"""Planning map workspace: layers, flood overlay picture, center points, result explanation."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

pytest.importorskip("rasterio")

from fastapi import Response  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import api.access  # noqa: E402
import api.ai_gateway  # noqa: E402
import api.assessments  # noqa: E402
import api.maps  # noqa: E402
import api.permissions  # noqa: E402
import api.planning  # noqa: E402
from api.dependencies import database_session  # noqa: E402
from api.main import app  # noqa: E402
from api.rate_limits import limiter  # noqa: E402
from api.sessions import CSRF_COOKIE, set_session_cookie  # noqa: E402
from api.settings import Settings  # noqa: E402
from core.access_models import AppUser, Base  # noqa: E402
from core.ai_allowance import update_setting  # noqa: E402
from core.assessment_jobs import claim_next_job, process_job  # noqa: E402
from core.assessment_models import DatasetVersion  # noqa: E402
from core.identity import IdentityLinkResult  # noqa: E402
from core.storage import LocalStorage  # noqa: E402
from grp.admin import assign_member, bootstrap_platform_admin, ensure_hub  # noqa: E402
from grp.seed import seed_synthetic_rp100  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch) -> Iterator[dict]:
    secret = tmp_path / "session_secret"
    secret.write_text("map-session-secret-with-enough-length", encoding="utf-8")
    settings = Settings(
        _env_file=None, session_secret_file=secret, allow_draft_methods=True,
        storage_root=tmp_path / "data", ai_feature_enabled=True, ai_model="test-model",
        grp_env="dev", planning_chat_enabled=True,
    )
    for module in (api.access, api.assessments, api.maps, api.permissions, api.planning):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    storage = LocalStorage(settings.storage_root)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        assign_member(session, actor_email="owner@example.test", email="planner@example.test",
                      hub_code="adpc", role="planner")
        seed = seed_synthetic_rp100(session, storage)
        owner = session.scalar(select(AppUser).where(AppUser.email == "owner@example.test"))
        update_setting(session, actor_user_id=owner.id, token_limit_per_person=50_000,
                       ai_enabled=True)
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    try:
        yield {"settings": settings, "engine": engine, "storage": storage, "seed": seed,
               "users": users, "monkeypatch": monkeypatch}
    finally:
        app.dependency_overrides.clear()


def _client(world: dict, email: str) -> TestClient:
    response = Response()
    set_session_cookie(
        response, world["settings"],
        IdentityLinkResult(allowed=True, reason="allowed", user_id=world["users"][email]),
        issued_at=int(datetime.now(UTC).timestamp()) - 5,
    )
    client = TestClient(app)
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    client.headers["X-CSRF-Token"] = client.cookies[CSRF_COOKIE]
    return client


def test_layers_list_flood_centers_and_vulnerability_placeholder(world) -> None:
    layers = _client(world, "planner@example.test").get("/api/v1/maps/layers").json()

    flood = layers["flood"][0]
    assert flood["return_period_years"] == 100 and flood["available"] is True
    south_west, north_east = flood["bounds"]
    assert south_west == pytest.approx([14.99, 100.0])
    assert north_east == pytest.approx([15.11, 100.12])
    assert len(layers["flood_legend"]["classes"]) == 5
    assert layers["flood_scenarios"] == [
        {
            "return_period_years": 20,
            "label": "RP20",
            "available": False,
            "layer_id": None,
            "message": "Not imported into the managed data library yet.",
        },
        {
            "return_period_years": 50,
            "label": "RP50",
            "available": False,
            "layer_id": None,
            "message": "Not imported into the managed data library yet.",
        },
        {
            "return_period_years": 100,
            "label": "RP100",
            "available": True,
            "layer_id": flood["id"],
            "message": None,
        },
    ]
    assert layers["evacuation_centers"][0]["title"] == "Synthetic evacuation centers"
    assert layers["vulnerability"]["available"] is False
    assert "Increment 6" in layers["vulnerability"]["message"]


def test_overlay_picture_is_a_png_and_does_not_change_the_input_fingerprint(world) -> None:
    client = _client(world, "planner@example.test")
    with Session(world["engine"]) as session:
        version = session.get(DatasetVersion, UUID(world["seed"].hazard_version_id))
        pinned = version.sha256
        key = version.storage_key

    response = client.get(f"/api/v1/maps/hazard/{world['seed'].hazard_version_id}/overlay.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:4] == b"\x89PNG"
    assert world["storage"].sha256(key) == pinned


def test_center_points_are_geojson(world) -> None:
    client = _client(world, "planner@example.test")
    collection = client.get(
        f"/api/v1/maps/datasets/{world['seed'].centers_version_id}/features"
    ).json()

    assert collection["type"] == "FeatureCollection"
    assert len(collection["features"]) == 8
    assert collection["features"][0]["geometry"]["type"] == "Point"


def test_map_layers_need_hub_role_and_hide_unknown_versions(world) -> None:
    owner = _client(world, "owner@example.test")
    planner = _client(world, "planner@example.test")

    assert owner.get("/api/v1/maps/layers").status_code == 403
    assert planner.get(f"/api/v1/maps/hazard/{uuid4()}/overlay.png").status_code == 404
    # A center dataset is not a flood picture.
    assert planner.get(
        f"/api/v1/maps/hazard/{world['seed'].centers_version_id}/overlay.png"
    ).status_code == 404


def test_explain_uses_only_stored_result_and_counts_tokens(world) -> None:
    client = _client(world, "planner@example.test")
    seed = world["seed"]
    submitted = client.post(
        "/api/v1/assessments",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "hub_code": "adpc",
            "boundary_id": seed.boundary_id,
            "hazard": {"type": "flood", "return_period_years": 100,
                       "dataset_version_id": seed.hazard_version_id},
            "evacuation_centers_dataset_version_id": seed.centers_version_id,
            "method": {"key": "center-flood-overlay", "version": "1.0.0"},
        },
    ).json()
    assessment_id = submitted["assessment_id"]
    not_ready = client.post(f"/api/v1/assessments/{assessment_id}/explain",
                            json={"question": "Which centers are exposed?"})
    with Session(world["engine"]) as session:
        process_job(session, world["storage"], claim_next_job(session, lease_minutes=15))
    prompts: list[str] = []

    async def provider(settings, *, instructions, prompt, hub_code):
        prompts.append(prompt)
        return "Three centers may be exposed under this scenario.", "test-model", 300, 40

    world["monkeypatch"].setattr(api.ai_gateway, "call_openai", provider)

    answer = client.post(f"/api/v1/assessments/{assessment_id}/explain",
                         json={"question": "Which centers are exposed?"})

    assert not_ready.status_code == 409
    body = answer.json()
    assert answer.status_code == 200, body
    assert body["label"] == "AI explanation. Numbers come from the assessment result."
    assert body["usage"]["tokens_used"] == 340
    sent = json.loads(prompts[0])
    assert sent["result"]["counts"]["potentially_exposed"] == 3
    assert {c["name"] for c in sent["result"]["centers"]} >= {"Synthetic School A"}
    # Section 10.5: no identities, secrets, internal keys or file links reach the model.
    text = prompts[0]
    for forbidden in ("planner@example.test", "storage_key", "rasters/", "sha256", "support_ref"):
        assert forbidden not in text


def _router_then(world: dict, *replies: str) -> list[str]:
    queue = list(replies)
    prompts: list[str] = []

    async def provider(settings, *, instructions, prompt, hub_code):
        prompts.append(prompt)
        return queue.pop(0), "test-model", 30, 10

    world["monkeypatch"].setattr(api.ai_gateway, "call_openai", provider)
    return prompts


def _chat(client: TestClient, message: str, **context):
    return client.post("/api/v1/planning/chat", json={"message": message, **context})


def test_chat_starts_assessment_then_explains_it_naturally(world) -> None:
    client = _client(world, "planner@example.test")
    prompts = _router_then(
        world,
        '{"mode": "run_assessment", "reply": "", "place": "Synthetic Test District",'
        ' "return_period_years": null}',
        '{"mode": "explain_result", "reply": "", "place": null, "return_period_years": null}',
        "Three centers may be exposed under this scenario.",
    )

    started = _chat(client, "Run a flood assessment for the synthetic test district").json()
    with Session(world["engine"]) as session:
        process_job(session, world["storage"], claim_next_job(session, lease_minutes=15))
    explained = _chat(
        client, "Which centers are exposed?", assessment_id=started["assessment_id"]
    ).json()

    assert started["mode"] == "assessment_started"
    assert started["boundary_id"] == world["seed"].boundary_id
    assert explained["mode"] == "explain_result"
    assert explained["label"] == "AI explanation. Numbers come from the assessment result."
    context = json.loads(prompts[0])["context"]
    assert "Synthetic Test District" in context["supported_areas"]
    assert json.loads(prompts[1])["context"]["has_result"] is True


def test_chat_uses_map_selection_when_no_place_is_named(world) -> None:
    client = _client(world, "planner@example.test")
    _router_then(
        world,
        '{"mode": "run_assessment", "reply": "", "place": null, "return_period_years": 100}',
    )

    body = _chat(client, "Run it here", boundary_id=world["seed"].boundary_id).json()

    assert body["mode"] == "assessment_started"


def test_confirmed_assessment_area_overrides_a_different_model_place(world) -> None:
    client = _client(world, "planner@example.test")
    _router_then(
        world,
        '{"mode": "run_assessment", "reply": "", "place": "Chiang Yuen",'
        ' "return_period_years": 100}',
    )

    body = _chat(
        client, "Assess the selected area", place="Synthetic Test District"
    ).json()

    assert body["mode"] == "assessment_started"
    assert body["boundary_id"] == world["seed"].boundary_id


def test_chat_explains_unsupported_area_and_missing_result(world) -> None:
    client = _client(world, "planner@example.test")
    _router_then(
        world,
        '{"mode": "run_assessment", "reply": "", "place": "Chiang Yuen",'
        ' "return_period_years": null}',
        '{"mode": "run_assessment", "reply": "", "place": "Chiang Yuen",'
        ' "return_period_years": null}',
        '{"mode": "run_assessment", "reply": "", "place": "Synthetic Test District",'
        ' "return_period_years": 500}',
        '{"mode": "explain_result", "reply": "", "place": null, "return_period_years": null}',
    )

    # Model-only place must be confirmed before SIG is contacted.
    proposed = _chat(client, "Assess Chiang Yuen", boundary_id=world["seed"].boundary_id).json()
    unsupported = _chat(client, "Assess Chiang Yuen", place=proposed["place"])
    no_scenario = _chat(
        client, "Assess the synthetic district for RP500", boundary_id=world["seed"].boundary_id
    ).json()
    no_result = _chat(client, "Explain the result").json()

    assert proposed["mode"] == "needs_area_confirmation"
    assert unsupported.status_code == 401
    assert unsupported.json()["error"]["code"] == "SIG_REAUTH_REQUIRED"
    assert no_scenario["mode"] == "unsupported_area" and "500-year" in no_scenario["answer"]
    assert no_result["mode"] == "needs_result"
    with Session(world["engine"]) as session:
        from core.assessment_models import Assessment

        assert session.scalars(select(Assessment)).all() == []


def test_confirmed_place_with_conflicting_province_does_not_start_grp_job(world) -> None:
    client = _client(world, "planner@example.test")
    _router_then(
        world,
        '{"mode": "run_assessment", "reply": "",'
        ' "place": "Synthetic Test District, Bangkok", "return_period_years": 100}',
        '{"mode": "run_assessment", "reply": "",'
        ' "place": "Synthetic Test District, Bangkok", "return_period_years": 100}',
    )

    proposed = _chat(
        client, "Assess Synthetic Test District in Bangkok", boundary_id=world["seed"].boundary_id
    ).json()
    confirmed = _chat(
        client, "Assess Synthetic Test District in Bangkok", place=proposed["place"]
    )

    assert proposed["mode"] == "needs_area_confirmation"
    assert confirmed.status_code == 401  # unsupported GRP area falls through to SIG
    with Session(world["engine"]) as session:
        from core.assessment_models import Assessment

        assert session.scalars(select(Assessment)).all() == []
