"""ADR-0032: send Hub data to Global Risk as a contribution, and follow it to the end."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.access
import api.contributions
import api.permissions
from api.dependencies import database_session
from api.main import app
from api.mcp_client import McpToolResult, SigMcpError
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from api.token_store import session_token_store
from core.access_models import AppUser, AuditEvent, Base
from core.contribution_models import SigContribution
from core.contribution_rules import check_manifest, check_point_file, drive_download_url
from core.identity import IdentityLinkResult
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub

FILE_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
DIRECT = f"https://drive.google.com/uc?export=download&id={FILE_ID}"

# Global Risk's gate, asked with an empty manifest on 28 Sep 2026 (problems only).
DECLINED_VECTOR = {
    "status": "declined",
    "kind": "vector",
    "problems": [
        "missing required field 'layer'",
        "missing required field 'license'",
    ],
}

VECTOR = {
    "layer": "evacuation_centres",
    "url": f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing",
    "title": "Evacuation centres, Thailand (DDPM)",
    "description": "One point per designated evacuation centre.",
    "source": "Thailand DDPM, compiled by ADPC",
    "license": "CC-BY-4.0",
    "vintage": "2026-09",
    "countries": "Thailand",
    "name_field": "name",
}


def _points(properties: dict | None = None) -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [100.5, 13.7]},
                    "properties": properties or {"name": "Wat A", "capacity": 200},
                }
            ],
        }
    ).encode()


# --- rules -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link",
    [
        f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing",
        f"https://drive.google.com/open?id={FILE_ID}",
        DIRECT,
    ],
)
def test_a_drive_share_link_becomes_a_direct_download(link: str) -> None:
    assert drive_download_url(link) == (DIRECT, None)


def test_a_drive_folder_is_refused_and_other_hosts_are_left_alone() -> None:
    url, problem = drive_download_url("https://drive.google.com/drive/folders/1xyzxyzxyzxyz")
    assert problem and "folder" in problem
    assert drive_download_url("https://example.org/a.tif") == ("https://example.org/a.tif", None)


def test_every_required_field_is_named_before_anything_is_sent() -> None:
    checked = check_manifest("raster", {"layer": "flood_depth", "url": "http://x.org/a.tif"})

    assert {"title", "legend", "declared", "license", "vintage"} <= set(checked.problems)
    assert "hazard_" in checked.problems["layer"]
    assert "https" in checked.problems["url"]


@pytest.mark.parametrize(
    ("layer", "refused"),
    [
        ("abc", False),
        ("a" * 40, False),
        ("early_warning_towers_ddpm_test_kj", False),
        ("ab", True),
        # The real decline of 30 Sep 2026: 43 characters.
        ("early_warning_towers_ddpm_test_yourinitials", True),
    ],
)
def test_a_layer_name_longer_than_global_risk_accepts_is_refused_before_sending(
    layer: str, refused: bool
) -> None:
    checked = check_manifest("vector", {"layer": layer})

    assert ("3 to 40 characters" in checked.problems.get("layer", "")) is refused


def test_a_population_grid_needs_no_legend() -> None:
    checked = check_manifest(
        "raster",
        {
            "layer": "population_worldpop_th", "url": DIRECT, "title": "t", "description": "d",
            "source": "WorldPop", "license": "CC-BY-4.0", "vintage": "2020-01",
            "declared": '{"dtype": "float32", "valid_min": 0, "valid_max": 200000}',
        },
    )

    assert checked.problems == {}
    assert checked.manifest["declared"]["dtype"] == "float32"


@pytest.mark.parametrize(
    ("weights", "fragment"),
    [
        ({"vulnerability_a": 0.5, "vulnerability_b": 0.4}, "add up to 0.900"),
        ({"vulnerability_a": 1.2, "vulnerability_b": -0.2}, "negative"),
        ({"population_worldpop_th": 1.0}, "cannot be weighted"),
    ],
)
def test_weights_must_add_up_to_one_and_never_weight_a_count(weights, fragment) -> None:
    checked = check_manifest("weights", {"hazard": "flood", "weights": weights, "rationale": "r"})

    assert fragment in checked.problems["weights"]


def test_unknown_fields_are_dropped_and_lists_are_split() -> None:
    checked = check_manifest("vector", {**VECTOR, "secret_token": "x"})

    assert checked.problems == {}
    assert "secret_token" not in checked.manifest
    assert checked.manifest["countries"] == ["Thailand"]
    assert checked.manifest["url"] == DIRECT


def test_a_point_file_with_contact_fields_is_refused() -> None:
    checked = check_point_file(_points({"name": "Wat A", "TEL": "02", "e_mail": "a@b"}))

    assert checked.problem and "TEL" in checked.problem and "e_mail" in checked.problem


def test_a_drive_web_page_is_not_mistaken_for_the_file() -> None:
    checked = check_point_file(b"<!DOCTYPE html><html>Virus scan warning</html>")

    assert checked.problem and "web page" in checked.problem


# --- route ------------------------------------------------------------------------------


class FakeMcp:
    calls: list[tuple[str, dict]] = []
    submit: dict | Exception = {}
    status: dict = {"status": "ok", "contributions": []}

    def __init__(self, base_url: str, access_token: str, *, client=None) -> None:
        assert access_token == "sig-token"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def call_tool(self, name: str, arguments: dict) -> McpToolResult:
        FakeMcp.calls.append((name, arguments))
        if name == "contribute_submit":
            if isinstance(FakeMcp.submit, Exception):
                raise FakeMcp.submit
            return McpToolResult([], FakeMcp.submit, False)
        return McpToolResult([], FakeMcp.status, False)


@pytest.fixture
def world(tmp_path, monkeypatch) -> Iterator[dict]:
    secret = tmp_path / "session_secret"
    secret.write_text("contribution-session-secret-long-enough", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        grp_env="dev",
        planning_chat_enabled=True,
        session_secret_file=secret,
        sig_mcp_base_url="https://sig.example/mcp",
    )
    for module in (api.access, api.permissions, api.contributions):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(api.contributions, "SigMcpClient", FakeMcp)
    fetched: dict = {"body": _points()}

    async def fetch(url: str) -> bytes:
        fetched["url"] = url
        return fetched["body"]

    monkeypatch.setattr(api.contributions, "_fetch_point_file", fetch)
    FakeMcp.calls = []
    FakeMcp.status = {"status": "ok", "contributions": []}
    FakeMcp.submit = {
        "status": "approved",
        "contribution_id": "c0ffee0000000001",
        "kind": "vector",
        "decision_note": "auto-approved: this deployment lands contributions without review",
        "reviewer_label": "auto-approve (GRP_AUTO_APPROVE on — no human reviewed this)",
        "preview": {
            "layer": "evacuation_centres",
            "observed": {"features": 1, "bbox": [100.5, 13.7, 100.5, 13.7]},
            "staged_file": "/opt/grp/cache/vectors/staged.geojson",
            "how_to_test": "assemble_pack(pack='risk', place=..., hazard='flood')",
        },
    }

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        ensure_hub(session, actor_email="owner@example.test", code="other", name="Other Hub")
        for email, hub in (
            ("planner@example.test", "adpc"),
            ("colleague@example.test", "adpc"),
            ("outsider@example.test", "other"),
        ):
            assign_member(session, actor_email="owner@example.test", email=email,
                          hub_code=hub, role="planner")
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    limiter.reset()
    try:
        yield {"settings": settings, "engine": engine, "users": users, "fetched": fetched}
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


def _send(client: TestClient, manifest: dict, *, kind: str = "vector", preview: bool = False):
    return client.post(
        "/api/v1/contributions",
        json={"hub_code": "adpc", "kind": kind, "manifest": manifest, "preview": preview},
    )


def _rows(world: dict) -> list[SigContribution]:
    with Session(world["engine"]) as session:
        return list(session.scalars(select(SigContribution)))


def test_a_preview_shows_the_exact_manifest_and_sends_nothing(world) -> None:
    body = _send(_client(world, "planner@example.test"), VECTOR, preview=True).json()

    assert body["sent"] is False and body["problems"] == {}
    assert body["manifest"]["url"] == DIRECT
    assert "direct-download" in body["notes"][0]
    assert FakeMcp.calls == [] and _rows(world) == []


def test_a_confirmed_point_layer_is_checked_submitted_and_recorded(world) -> None:
    client = _client(world, "planner@example.test")

    started = _send(client, VECTOR).json()
    polled = client.get(f"/api/v1/contributions/{started['contribution']['id']}").json()

    assert started["sent"] is True
    assert world["fetched"]["url"] == DIRECT
    assert FakeMcp.calls[0][0] == "contribute_submit"
    assert FakeMcp.calls[0][1]["manifest"]["url"] == DIRECT
    assert polled["status"] == "approved" and polled["state"] == "succeeded"
    assert polled["contribution_id"] == "c0ffee0000000001"
    assert polled["feature_count"] == 1 and len(polled["file_sha256"]) == 64
    assert "auto-approved" in polled["response"]["decision_note"]
    assert "how_to_test" in polled["response"]
    # Global Risk's own server paths are not kept.
    assert "staged_file" not in json.dumps(polled["response"])
    with Session(world["engine"]) as session:
        actions = set(session.scalars(select(AuditEvent.action)))
    assert {"sig_contribution_submitted", "sig_contribution_result"} <= actions


def test_a_declined_contribution_names_the_fields_to_fix(world) -> None:
    FakeMcp.submit = DECLINED_VECTOR
    client = _client(world, "planner@example.test")

    started = _send(client, VECTOR).json()
    polled = client.get(f"/api/v1/contributions/{started['contribution']['id']}").json()

    assert polled["status"] == "declined" and polled["state"] == "failed"
    assert polled["field_problems"] == {
        "layer": "Global Risk says this is required.",
        "license": "Global Risk says this is required.",
    }
    assert polled["problems"] == DECLINED_VECTOR["problems"]


def test_a_point_file_with_contact_fields_never_reaches_global_risk(world) -> None:
    world["fetched"]["body"] = _points({"name": "Wat A", "phone": "02-000"})
    client = _client(world, "planner@example.test")

    started = _send(client, VECTOR).json()
    polled = client.get(f"/api/v1/contributions/{started['contribution']['id']}").json()

    assert polled["status"] == "failed" and polled["error_code"] == "FILE_CHECK_FAILED"
    assert "phone" in polled["error"]
    assert FakeMcp.calls == []


def test_an_unanswered_submit_is_found_rather_than_sent_again(world) -> None:
    FakeMcp.submit = SigMcpError("read timed out")
    FakeMcp.status = {
        "status": "ok",
        "contributions": [
            {
                "contribution_id": "c0ffee0000000002",
                "kind": "vector",
                "status": "approved",
                "title": "Evacuation centres, Thailand (DDPM) (evacuation_centres)",
                "created_at": datetime.now(UTC).isoformat(),
            }
        ],
    }
    client = _client(world, "planner@example.test")

    started = _send(client, VECTOR).json()
    polled = client.get(f"/api/v1/contributions/{started['contribution']['id']}").json()

    assert [name for name, _ in FakeMcp.calls] == ["contribute_submit", "contribute_status"]
    assert polled["status"] == "approved"
    assert polled["contribution_id"] == "c0ffee0000000002"


def test_an_unanswered_submit_with_no_record_says_it_is_safe_to_send_again(world) -> None:
    FakeMcp.submit = httpx.ReadTimeout("timed out")
    client = _client(world, "planner@example.test")

    started = _send(client, VECTOR).json()
    polled = client.get(f"/api/v1/contributions/{started['contribution']['id']}").json()

    assert polled["status"] == "failed" and polled["error_code"] == "SUBMIT_UNCONFIRMED"
    assert "safe to submit it again" in polled["error"]


def test_only_the_sender_can_refresh_and_another_hub_cannot_see_it(world) -> None:
    FakeMcp.submit = {**FakeMcp.submit, "status": "staged"}
    sender = _client(world, "planner@example.test")
    row_id = _send(sender, VECTOR).json()["contribution"]["id"]

    colleague = _client(world, "colleague@example.test")
    outsider = _client(world, "outsider@example.test")
    seen = colleague.get("/api/v1/contributions?hub_code=adpc").json()["contributions"]
    refused = colleague.post(f"/api/v1/contributions/{row_id}/refresh")
    hidden = outsider.get(f"/api/v1/contributions/{row_id}")

    assert [row["id"] for row in seen] == [row_id] and seen[0]["mine"] is False
    assert refused.status_code == 403
    assert hidden.status_code == 404

    FakeMcp.status = {"status": "ok", "contribution_id": "c0ffee0000000001",
                      "kind": "vector", "status_detail": "", "decision_note": "approved by r"}
    FakeMcp.status["status"] = "approved"
    refreshed = sender.post(f"/api/v1/contributions/{row_id}/refresh").json()
    assert refreshed["status"] == "approved"


def test_sending_needs_a_servir_sign_in_and_a_complete_manifest(world) -> None:
    signed_out = _send(_client(world, "planner@example.test", sig_token=False), VECTOR)
    incomplete = _send(_client(world, "planner@example.test"), {"layer": "evacuation_centres"})

    assert signed_out.status_code == 401
    assert signed_out.json()["error"]["code"] == "SIG_REAUTH_REQUIRED"
    assert incomplete.json()["sent"] is False and "title" in incomplete.json()["problems"]
    assert _rows(world) == [] and FakeMcp.calls == []


def test_a_hub_you_do_not_plan_for_cannot_be_sent_for(world) -> None:
    response = _client(world, "outsider@example.test").post(
        "/api/v1/contributions",
        json={"hub_code": "adpc", "kind": "vector", "manifest": VECTOR, "preview": True},
    )

    assert response.status_code == 404


# --- a name is the key: never sent twice ------------------------------------------------


def _hub_id(world: dict, code: str):
    from core.access_models import Hub

    with Session(world["engine"]) as session:
        return session.scalar(select(Hub.id).where(Hub.code == code))


def _existing(world: dict, *, hub: str = "adpc", state: str = "approved", kind: str = "vector",
              name: str = "evacuation_centres", error_code: str | None = None) -> None:
    with Session(world["engine"]) as session:
        session.add(SigContribution(
            hub_id=_hub_id(world, hub), user_id=world["users"]["planner@example.test"],
            kind=kind, name=name, title="Earlier", manifest={"layer": name}, state=state,
            contribution_id="c0ffee00000000aa", error_code=error_code,
        ))
        session.commit()


def test_a_name_this_hub_already_sent_is_refused_with_the_way_to_replace_it(world) -> None:
    _existing(world)
    client = _client(world, "planner@example.test")

    preview = _send(client, VECTOR, preview=True).json()
    confirmed = _send(client, VECTOR).json()

    for body in (preview, confirmed):
        assert body["sent"] is False
        assert "Already sent" in body["problems"]["layer"]
        duplicate = body["duplicate"]
        assert duplicate["source"] == "this_hub" and duplicate["state"] == "approved"
        assert duplicate["contribution_id"] == "c0ffee00000000aa"
        assert "cannot update" in duplicate["message"]
        assert "never overwrite" in duplicate["message"]
        assert "under a new name" in duplicate["message"]
    # Nothing went to Global Risk and no second row was written.
    assert FakeMcp.calls == [] and len(_rows(world)) == 1


def test_another_hubs_name_is_refused_without_its_details(world) -> None:
    _existing(world, hub="other")

    duplicate = _send(_client(world, "planner@example.test"), VECTOR, preview=True).json()[
        "duplicate"]

    assert duplicate["source"] == "another_hub"
    assert duplicate["contribution_id"] is None and duplicate["state"] is None
    assert "another Hub" in duplicate["message"]


@pytest.mark.parametrize("state", ["declined", "rejected", "withdrawn"])
def test_a_name_that_never_landed_or_was_removed_is_free(world, state: str) -> None:
    _existing(world, state=state)

    body = _send(_client(world, "planner@example.test"), VECTOR, preview=True).json()

    assert body["duplicate"] is None and body["problems"] == {}


def test_an_unconfirmed_submit_holds_its_name_until_checked(world) -> None:
    _existing(world, state="failed", error_code="SUBMIT_UNCONFIRMED")

    body = _send(_client(world, "planner@example.test"), VECTOR, preview=True).json()

    assert body["duplicate"]["state"] == "failed"


def test_a_raster_cannot_reuse_a_point_layers_name_but_weights_can_be_resent(world) -> None:
    _existing(world, name="population_th_grid")
    _existing(world, kind="weights", name="flood")
    raster = {
        "layer": "population_th_grid", "url": DIRECT, "title": "Population",
        "description": "Counts.", "source": "ADPC", "license": "unstated", "vintage": "2026-09",
        "declared": {"dtype": "float32", "valid_min": 0, "valid_max": 1000},
    }
    weights = {"hazard": "flood", "weights": {"vulnerability_a": 0.5, "vulnerability_b": 0.5},
               "rationale": "Adjusting the flood weights again."}
    client = _client(world, "planner@example.test")

    assert _send(client, raster, kind="raster", preview=True).json()["duplicate"] is not None
    assert _send(client, weights, kind="weights", preview=True).json()["duplicate"] is None


def test_a_layer_counted_in_global_risk_evidence_is_taken(world) -> None:
    # A layer sent from Claude Desktop reaches GRP only as a count in someone's evidence.
    from core.planning_memory_models import PlanningChatMessage

    with Session(world["engine"]) as session:
        session.add(PlanningChatMessage(
            user_id=world["users"]["outsider@example.test"], hub_id=_hub_id(world, "other"),
            role="assistant", kind="evidence", text="",
            payload={"evidence": {"stats": {"counts": {
                "evacuation_centres": {"exposed": 1, "total": 2}}}}},
        ))
        session.commit()

    duplicate = _send(_client(world, "planner@example.test"), VECTOR, preview=True).json()[
        "duplicate"]

    assert duplicate["source"] == "global_risk_evidence" and duplicate["seen_at"]
    assert "counted in Global Risk evidence" in duplicate["message"]


def test_checking_an_approved_row_frees_its_name_once_global_risk_withdrew_it(world) -> None:
    client = _client(world, "planner@example.test")
    row_id = _send(client, VECTOR).json()["contribution"]["id"]
    assert _send(client, VECTOR, preview=True).json()["duplicate"] is not None

    FakeMcp.status = {"status": "ok", "contribution_id": "c0ffee0000000001",
                      "kind": "vector", "status_detail": "withdrawn by a reviewer"}
    FakeMcp.status["status"] = "withdrawn"
    refreshed = client.post(f"/api/v1/contributions/{row_id}/refresh").json()

    assert refreshed["status"] == "withdrawn"
    assert _send(client, VECTOR, preview=True).json()["duplicate"] is None


def test_a_removed_layer_stops_counting_once_evidence_for_its_place_is_gathered_again(
    world,
) -> None:
    from datetime import timedelta

    from core.planning_memory_models import PlanningChatMessage

    now = datetime.now(UTC)
    with Session(world["engine"]) as session:
        for counts, when in (
            ({"evacuation_centres": {"exposed": 1, "total": 2}}, now - timedelta(hours=2)),
            ({"schools": {"exposed": 1, "total": 2}}, now - timedelta(hours=1)),
        ):
            session.add(PlanningChatMessage(
                user_id=world["users"]["planner@example.test"], hub_id=_hub_id(world, "adpc"),
                role="assistant", kind="evidence", text="", created_at=when,
                payload={"evidence": {"area": {"requested": "Samko District, Ang Thong"},
                                      "stats": {"counts": counts}}},
            ))
        session.commit()

    body = _send(_client(world, "planner@example.test"), VECTOR, preview=True).json()

    assert body["duplicate"] is None


# --- everything the person's SERVIR sign-in sent, from any app -----------------------------


def _status_record(contribution_id: str, layer: str, title: str, features: int) -> dict:
    """The shape contribute_status returned on 1 Oct 2026, server paths included."""

    return {
        "contribution_id": contribution_id,
        "kind": "vector",
        "status": "approved",
        "title": f"{title} ({layer})",
        "contributor_label": "user_01SERVIRACCOUNT",
        "created_at": "2026-09-30T08:14:54.375968+00:00",
        "updated_at": "2026-09-30T08:14:54.408800+00:00",
        "preview": {
            "layer": layer,
            "observed": {"features": features, "bbox": [97.6, 5.8, 105.6, 20.4]},
            "staged_file": f"/opt/grp/cache/vectors/staged-{contribution_id}.geojson",
            "entry": {
                "local_path": f"vectors/staged-{contribution_id}.geojson",
                "title": title,
                "license": "unstated",
                "vintage": "2026-09",
                "usage_notes": "TEST copy. Do not use it for decisions.",
                "staged_by": "user_01SERVIRACCOUNT",
            },
        },
        "landing": {
            "layer": layer,
            "file": f"/opt/grp/cache/vectors/{layer}.geojson",
            "features": features,
        },
        "decision_note": "auto-approved: this deployment lands contributions without review",
        "reviewer_label": "auto-approve (GRP_AUTO_APPROVE on — no human reviewed this)",
    }


def test_every_contribution_of_my_sign_in_is_listed_and_marked_by_where_it_was_sent(world) -> None:
    client = _client(world, "planner@example.test")
    _send(client, VECTOR)  # GRP sends it; Global Risk answers c0ffee0000000001
    FakeMcp.calls = []
    FakeMcp.status = {
        "status": "ok",
        "contributions": [
            _status_record("212436d83e490738", "early_warning_towers_test_kovitad",
                           "Early-warning towers (TEST)", 1533),
            _status_record("c0ffee0000000001", "evacuation_centres",
                           "Evacuation centres, Thailand (DDPM)", 1),
        ],
    }

    body = client.get("/api/v1/contributions/on-global-risk?hub_code=adpc").json()

    assert FakeMcp.calls == [("contribute_status", {})]
    desktop, here = body["contributions"]
    assert desktop["name"] == "early_warning_towers_test_kovitad"
    assert desktop["title"] == "Early-warning towers (TEST)"
    assert desktop["sent_from"] == "outside_grp" and desktop["grp_row_id"] is None
    assert desktop["is_test"] is True and desktop["live"] is True
    assert desktop["features"] == 1533 and desktop["auto_approved"] is True
    assert here["sent_from"] == "grp" and here["grp_row_id"]
    assert here["is_test"] is False
    # Global Risk's server paths and the SERVIR account label never reach the browser.
    text = json.dumps(body)
    assert "/opt/grp" not in text and "staged-" not in text and "user_01" not in text


def test_a_row_another_person_sent_from_grp_is_not_marked_as_mine(world) -> None:
    _send(_client(world, "colleague@example.test"), VECTOR)
    FakeMcp.status = {
        "status": "ok",
        "contributions": [_status_record("c0ffee0000000001", "evacuation_centres", "E", 1)],
    }

    body = _client(world, "planner@example.test").get(
        "/api/v1/contributions/on-global-risk"
    ).json()

    assert body["contributions"][0]["sent_from"] == "outside_grp"


def test_listing_global_risk_needs_a_servir_sign_in_and_says_when_it_is_down(world, monkeypatch):
    signed_out = _client(world, "planner@example.test", sig_token=False).get(
        "/api/v1/contributions/on-global-risk"
    )

    class DownMcp(FakeMcp):
        async def __aenter__(self):
            raise SigMcpError("SIG MCP is unavailable")

    monkeypatch.setattr(api.contributions, "SigMcpClient", DownMcp)
    down = _client(world, "planner@example.test").get("/api/v1/contributions/on-global-risk")

    assert signed_out.status_code == 401
    assert signed_out.json()["error"]["code"] == "SIG_REAUTH_REQUIRED"
    assert down.status_code == 503 and down.json()["error"]["code"] == "SIG_UNAVAILABLE"


# ADR-0052: a live feed is tested the way Global Risk will read it, before it is shown or sent.
FEED = {
    "dataset": "bangkok_flood_districts_live", "title": "Flood by district",
    "description": "56 districts.", "source": "ADPC GRP", "validation": "unvalidated",
    "cadence": "every 10 minutes", "url": "https://grp.example.org/api/v1/public/flood/bangkok/feed.json",
    "records_path": "districts", "fields": {"district": "district_name_en", "as_of": "as_of"},
    "as_of_field": "as_of",
}


def _feed_test(monkeypatch, result: dict) -> list:
    asked = []

    def fake(url, records_path, fields, as_of_field):
        asked.append(url)
        return result

    monkeypatch.setattr(api.contributions, "check_feed", fake)
    return asked


def test_a_feed_preview_says_what_global_risk_would_read(world, monkeypatch) -> None:
    asked = _feed_test(monkeypatch, {"ok": True, "count": 56, "returned_by_default": 12,
                                     "order": "sorted newest-last by as_of", "notes": []})
    body = _send(_client(world, "planner@example.test"), FEED, kind="feed", preview=True).json()

    assert body["problems"] == {} and body["manifest"]["fetch"]["records_path"] == "districts"
    assert any("would read 56 records" in note for note in body["notes"])
    assert asked == [FEED["url"]] and FakeMcp.calls == []


def test_a_dead_or_empty_feed_is_never_sent(world, monkeypatch) -> None:
    _feed_test(monkeypatch, {"ok": False, "problem": "The feed answered HTTP 503."})
    client = _client(world, "planner@example.test")

    for preview in (True, False):
        body = _send(client, FEED, kind="feed", preview=preview).json()
        assert body["sent"] is False and "HTTP 503" in body["problems"]["url"]
    assert FakeMcp.calls == [] and _rows(world) == []


def test_a_feed_name_shares_the_dataset_names_with_tables(world, monkeypatch) -> None:
    _feed_test(monkeypatch, {"ok": True, "count": 1, "returned_by_default": 1, "order": "x",
                             "notes": []})
    _existing(world, kind="table", name="bangkok_flood_districts_live")
    body = _send(_client(world, "planner@example.test"), FEED, kind="feed", preview=True).json()
    assert "Already sent" in body["problems"]["dataset"]


def test_platform_feeds_say_when_a_feed_was_sent_and_last_read(world, monkeypatch) -> None:
    from core import public_reads

    public_reads.reset()
    public_reads.record("flood:bangkok")
    _existing(world, kind="feed", name="bangkok_flood_districts_live")
    feeds = {f["dataset"]: f for f in _client(world, "planner@example.test").get(
        "/api/v1/contributions/platform-feeds?hub_code=adpc").json()["feeds"]}

    districts = feeds["bangkok_flood_districts_live"]
    assert districts["sent"]["source"] == "this_hub" and districts["sent"]["state"] == "approved"
    assert districts["last_read"]["count"] == 1
    assert feeds["sea_pm25_province_forecast"]["sent"] is None
    assert feeds["sea_pm25_province_forecast"]["last_read"] is None


def test_a_confirmed_feed_is_sent_nested_as_global_risk_expects(world, monkeypatch) -> None:
    _feed_test(monkeypatch, {"ok": True, "count": 56, "returned_by_default": 12, "order": "x",
                             "notes": []})
    FakeMcp.submit = {"status": "approved", "contribution_id": "c0ffee0000000002", "kind": "feed",
                      "decision_note": "auto-approved", "preview": {"dataset": FEED["dataset"]}}
    client = _client(world, "planner@example.test")
    checked = _send(client, FEED, kind="feed", preview=True).json()["manifest"]
    started = _send(client, checked, kind="feed").json()

    assert started["sent"] is True
    name, arguments = FakeMcp.calls[0]
    assert name == "contribute_submit" and arguments["kind"] == "feed"
    sent = arguments["manifest"]
    assert sent["adapter"] == "generic_json" and sent["fetch"]["url"] == FEED["url"]
    assert "url" not in sent and sent["dataset"] == FEED["dataset"]
