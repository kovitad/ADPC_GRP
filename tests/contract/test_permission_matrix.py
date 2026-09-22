"""GRP-ARC-001 Section 9.4 permission matrix for the routes that exist today.

Requests go through the real session cookie, CSRF check, rate limiter and database
membership lookup; nothing is overridden except the database and settings.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import api.access
import api.admin
import api.ai
import api.auth
import api.data_inspector
import api.data_library
import api.integrations.sig
import api.maps
import api.permissions
import api.platform
from api.dependencies import database_session
from api.main import app
from api.rate_limits import limiter
from api.sessions import CSRF_COOKIE, set_session_cookie
from api.settings import Settings
from core.access_models import AppUser, Base, HubMembership
from core.assessment_models import Dataset, DatasetVersion
from core.identity import IdentityLinkResult
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub

ACTORS = ("anonymous", "planner", "hub_admin", "other_hub_admin", "platform_admin")

# route key -> expected status per actor, in ACTORS order.
MATRIX = {
    "list_administered_hubs": (401, 200, 200, 200, 200),
    "list_members": (401, 403, 200, 404, 200),
    "add_member": (401, 403, 200, 404, 200),
    "change_member": (401, 403, 200, 404, 200),
    "access_message": (401, 403, 200, 404, 200),
    "my_ai_usage": (401, 200, 200, 200, 200),
    "hub_security_log": (401, 403, 200, 200, 200),
    "read_ai_setting": (401, 403, 403, 403, 200),
    "change_ai_setting": (401, 403, 403, 403, 200),
    "read_risk_recipe": (401, 403, 403, 403, 200),
    "change_risk_recipe": (401, 403, 403, 403, 200),
    # Authorized Platform Admin reaches the input-readiness check; this fixture has no full set.
    "activate_baseline": (401, 403, 403, 403, 409),
    "people_ai_usage": (401, 403, 403, 403, 200),
    "reset_ai_usage": (401, 403, 403, 403, 200),
    "list_all_hubs": (401, 403, 403, 403, 200),
    "create_hub": (401, 403, 403, 403, 200),
    "change_hub_status": (401, 403, 403, 403, 200),
    "platform_health": (401, 403, 403, 403, 200),
    # Human sessions are never the SIG service, whoever they are.
    "sig_evidence_with_session": (401, 401, 401, 401, 401),
    # ADR-0006: the data inspector is for Admins. A Hub Expert or Planner is not one.
    "source_folders": (401, 403, 200, 200, 200),
    "ask_for_inspection": (401, 403, 200, 200, 200),
    "ask_for_preview": (401, 403, 200, 200, 200),
    # No picture exists for a made-up id: allowed callers get 404, the rest are refused first.
    "preview_flood_picture": (401, 403, 404, 404, 404),
    # ADR-0008: Admins can inspect the library; only a Platform Admin can import.
    "data_library": (401, 403, 200, 200, 200),
    "import_boundaries": (401, 403, 403, 403, 200),
    "import_evacuation_centers": (401, 403, 403, 403, 200),
    "import_hazard_rp100": (401, 403, 403, 403, 200),
    # An unknown import is hidden after authorization, so allowed Admins receive 404.
    "read_import": (401, 403, 404, 404, 404),
    # Planning map layers require a Hub role; a Platform Admin has no implicit Hub access.
    "map_layers": (401, 200, 200, 200, 403),
    "hazard_overlay": (401, 404, 404, 404, 403),
    "dataset_features": (401, 404, 404, 404, 403),
}

# Matrix case -> FastAPI operation ID. Keeping this explicit makes each exercised operation
# visible in review and lets the completeness test below reject newly added protected routes.
MATRIX_OPERATION_IDS = {
    "list_administered_hubs": "administered_hubs_api_v1_admin_hubs_get",
    "list_members": "hub_members_api_v1_admin_hubs__hub_code__members_get",
    "add_member": "create_hub_membership_api_v1_admin_hubs__hub_code__members_post",
    "change_member": (
        "change_hub_membership_api_v1_admin_hubs__hub_code__members__member_id__patch"
    ),
    "access_message": (
        "access_message_api_v1_admin_hubs__hub_code__members__member_id__access_message_get"
    ),
    "my_ai_usage": "my_ai_usage_api_v1_me_ai_usage_get",
    "hub_security_log": "audit_events_api_v1_admin_audit_events_get",
    "read_ai_setting": "read_ai_setting_api_v1_platform_ai_usage_setting_get",
    "change_ai_setting": "change_ai_setting_api_v1_platform_ai_usage_setting_put",
    "read_risk_recipe": "read_risk_recipe_api_v1_platform_risk_recipe_get",
    "change_risk_recipe": "change_risk_recipe_api_v1_platform_risk_recipe_put",
    "activate_baseline": "activate_baseline_api_v1_platform_mvp1_activate_post",
    "people_ai_usage": "ai_usage_people_api_v1_platform_ai_usage_people_get",
    "reset_ai_usage": "reset_ai_usage_api_v1_platform_ai_usage_people__user_id__reset_post",
    "list_all_hubs": "platform_hubs_api_v1_platform_hubs_get",
    "create_hub": "create_hub_api_v1_platform_hubs_post",
    "change_hub_status": "change_hub_status_api_v1_platform_hubs__hub_code__patch",
    "platform_health": "platform_health_api_v1_platform_health_get",
    "source_folders": "source_folders_api_v1_data_inspector_folders_get",
    "ask_for_inspection": "ask_for_inspection_api_v1_data_inspector_inspections_post",
    "ask_for_preview": "ask_for_preview_api_v1_data_inspector_previews_post",
    "preview_flood_picture": (
        "preview_flood_picture_api_v1_data_inspector_previews__inspection_id__flood_png_get"
    ),
    "data_library": "data_library_api_v1_data_library_get",
    "import_boundaries": "import_boundaries_api_v1_data_library_imports_boundaries_post",
    "import_evacuation_centers": (
        "import_evacuation_centers_api_v1_data_library_imports_evacuation_centers_post"
    ),
    "import_hazard_rp100": "import_hazard_rp100_api_v1_data_library_imports_hazard_rp100_post",
    "read_import": "read_import_api_v1_data_library_imports__import_id__get",
    "map_layers": "map_layers_api_v1_maps_layers_get",
    "hazard_overlay": "hazard_overlay_api_v1_maps_hazard__version_id__overlay_png_get",
    "dataset_features": "dataset_features_api_v1_maps_datasets__version_id__features_get",
}

# Protected operations covered elsewhere. Remove an entry when its role behavior moves into MATRIX.
KNOWN_UNCOVERED = {
    # AI gateway permission cases live in fast tests.
    "ai_test_call_api_v1_ai_test_call_post",
    # Golden assessment tests cover Hub submission.
    "submit_assessment_api_v1_assessments_post",
    # Golden tests cover Hub-scoped assessment lists.
    "list_assessments_api_v1_assessments_get",
    # Golden tests cover job reads.
    "assessment_status_api_v1_assessments__assessment_id__get",
    # Golden tests cover cancellation.
    "cancel_assessment_api_v1_assessments__assessment_id__cancel_post",
    # Golden tests cover result points.
    "assessment_centers_api_v1_assessments__assessment_id__centers_get",
    # Golden tests cover AI explain.
    "explain_assessment_api_v1_assessments__assessment_id__explain_post",
    # Golden tests cover result privacy.
    "assessment_result_api_v1_assessments__assessment_id__result_get",
    # Golden tests cover supported boundary visibility.
    "boundaries_api_v1_catalog_boundaries_get",
    # Golden tests cover current dataset visibility.
    "datasets_api_v1_catalog_datasets_get",
    # Golden tests cover approved method visibility.
    "methods_api_v1_catalog_methods_get",
    # Inspector tests cover reads.
    "read_inspection_api_v1_data_inspector_inspections__inspection_id__get",
    # Session and access tests cover the current principal.
    "current_user_api_v1_me_get",
    # Planning tests cover role and Hub denial.
    "planning_chat_api_v1_planning_chat_post",
    # Planning tests cover status access.
    "planning_status_api_v1_planning_status_get",
}


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> Iterator[dict]:
    secret = tmp_path_factory.mktemp("secrets") / "session_secret"
    secret.write_text("contract-session-secret-with-enough-length", encoding="utf-8")
    data_in = tmp_path_factory.mktemp("data-in")
    (data_in / "notes.txt").write_text("a file, so the folder is not empty", encoding="utf-8")
    boundary_folder = data_in / "administrative_boundary/district_boundary"
    boundary_folder.mkdir(parents=True)
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        (boundary_folder / f"Thailand_District_Boundaries{suffix}").write_text(
            "x", encoding="utf-8"
        )
    shelter_folder = data_in / "evacuation_centers/shelters"
    shelter_folder.mkdir(parents=True)
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        (shelter_folder / f"ddpm_shelters{suffix}").write_text("x", encoding="utf-8")
    hazard_folder = data_in / "floods/flood_depth_rp100"
    hazard_folder.mkdir(parents=True)
    for index in range(6):
        (hazard_folder / f"tile-{index}.tif").write_text("x", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        session_secret_file=secret,
        data_inspector_enabled=True,
        data_in_root=data_in,
    )
    patch = pytest.MonkeyPatch()
    for module in (
        api.access, api.admin, api.ai, api.auth, api.integrations.sig,
        api.permissions, api.platform, api.data_inspector, api.data_library, api.maps,
    ):
        patch.setattr(module, "get_settings", lambda: settings)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        for code in ("adpc", "other"):
            ensure_hub(session, actor_email="owner@example.test", code=code, name=f"{code} Hub")
        for email, hub, role in (
            ("planner@example.test", "adpc", "planner"),
            ("hub-admin@example.test", "adpc", "admin"),
            ("other-admin@example.test", "other", "admin"),
        ):
            assign_member(
                session, actor_email="owner@example.test", email=email, hub_code=hub, role=role
            )
        boundary_dataset = Dataset(
            id=uuid4(),
            type="boundary",
            owner_kind="platform",
            title="Contract boundaries",
            provider="Contract fixture",
        )
        session.add(boundary_dataset)
        session.add(
            DatasetVersion(
                id=uuid4(),
                dataset_id=boundary_dataset.id,
                sha256="a" * 64,
                meta={},
                readiness="technically_valid",
                is_current=False,
            )
        )
        session.commit()
        users = {user.email: user.id for user in session.scalars(select(AppUser))}
        planner_membership = session.scalar(
            select(HubMembership.id).where(
                HubMembership.user_id == users["planner@example.test"]
            )
        )

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database_session] = test_session
    try:
        yield {
            "settings": settings,
            "users": {
                "planner": users["planner@example.test"],
                "hub_admin": users["hub-admin@example.test"],
                "other_hub_admin": users["other-admin@example.test"],
                "platform_admin": users["owner@example.test"],
            },
            "planner_membership": planner_membership,
        }
    finally:
        app.dependency_overrides.clear()
        patch.undo()


def _client(world: dict, actor: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    if actor == "anonymous":
        return client, {}
    response = Response()
    set_session_cookie(
        response,
        world["settings"],
        IdentityLinkResult(allowed=True, reason="allowed", user_id=world["users"][actor]),
        issued_at=int(datetime.now(UTC).timestamp()) - 5,
    )
    for header in response.headers.getlist("set-cookie"):
        name, value = header.split(";", 1)[0].split("=", 1)
        client.cookies.set(name, value)
    return client, {"X-CSRF-Token": client.cookies[CSRF_COOKIE]}


def _call(client: TestClient, headers: dict[str, str], route: str, world: dict, actor: str):
    member = world["planner_membership"]
    if route == "list_administered_hubs":
        return client.get("/api/v1/admin/hubs")
    if route == "list_members":
        return client.get("/api/v1/admin/hubs/adpc/members")
    if route == "add_member":
        return client.post(
            "/api/v1/admin/hubs/adpc/members",
            json={"email": f"added-by-{actor}@example.test", "role": "planner"},
            headers=headers,
        )
    if route == "change_member":
        # Same values: exercises authorization without revoking the planner's session.
        return client.patch(
            f"/api/v1/admin/hubs/adpc/members/{member}",
            json={"role": "planner", "status": "active"},
            headers=headers,
        )
    if route == "access_message":
        return client.get(f"/api/v1/admin/hubs/adpc/members/{member}/access-message")
    user_id = world["users"]["planner"]
    requests = {
        "my_ai_usage": ("GET", "/api/v1/me/ai-usage", None),
        "hub_security_log": ("GET", "/api/v1/admin/audit-events", None),
        "read_ai_setting": ("GET", "/api/v1/platform/ai-usage/setting", None),
        "change_ai_setting": (
            "PUT",
            "/api/v1/platform/ai-usage/setting",
            {"token_limit_per_person": 200000, "ai_enabled": False},
        ),
        "read_risk_recipe": ("GET", "/api/v1/platform/risk-recipe", None),
        "change_risk_recipe": (
            "PUT",
            "/api/v1/platform/risk-recipe",
            {
                "version": "permission-matrix-v1",
                "population_weight": 0.4,
                "building_density_weight": 0.35,
                "road_distance_weight": 0.25,
                "science_owner": "Contract test owner",
                "source_ref": "Contract test source",
                "change_reason": "Exercise authorization",
            },
        ),
        "activate_baseline": ("POST", "/api/v1/platform/mvp1/activate", None),
        "people_ai_usage": ("GET", "/api/v1/platform/ai-usage/people", None),
        "reset_ai_usage": ("POST", f"/api/v1/platform/ai-usage/people/{user_id}/reset", None),
        "list_all_hubs": ("GET", "/api/v1/platform/hubs", None),
        "create_hub": ("POST", "/api/v1/platform/hubs", {"code": "adpc", "name": "adpc Hub"}),
        "change_hub_status": ("PATCH", "/api/v1/platform/hubs/adpc", {"status": "active"}),
        "platform_health": ("GET", "/api/v1/platform/health", None),
        "sig_evidence_with_session": (
            "GET",
            f"/api/v1/integrations/sig/assessments/{user_id}/evidence",
            None,
        ),
        "source_folders": ("GET", "/api/v1/data-inspector/folders", None),
        "ask_for_inspection": ("POST", "/api/v1/data-inspector/inspections", {"folder": ""}),
        "ask_for_preview": ("POST", "/api/v1/data-inspector/previews", {"district": "Pua"}),
        "preview_flood_picture": (
            "GET",
            f"/api/v1/data-inspector/previews/{user_id}/flood.png",
            None,
        ),
        "data_library": ("GET", "/api/v1/data-library", None),
        "import_boundaries": ("POST", "/api/v1/data-library/imports/boundaries", None),
        "import_evacuation_centers": (
            "POST",
            "/api/v1/data-library/imports/evacuation-centers",
            None,
        ),
        "import_hazard_rp100": (
            "POST",
            "/api/v1/data-library/imports/hazard-rp100",
            None,
        ),
        "read_import": ("GET", f"/api/v1/data-library/imports/{user_id}", None),
        "map_layers": ("GET", "/api/v1/maps/layers", None),
        "hazard_overlay": ("GET", f"/api/v1/maps/hazard/{user_id}/overlay.png", None),
        "dataset_features": ("GET", f"/api/v1/maps/datasets/{user_id}/features", None),
    }
    method, path, body = requests[route]
    request_headers = dict(headers)
    if route.startswith("import_"):
        request_headers["Idempotency-Key"] = f"permission-{route}"
    return client.request(method, path, json=body, headers=request_headers)


@pytest.mark.contract
@pytest.mark.parametrize("route", sorted(MATRIX))
@pytest.mark.parametrize("actor", ACTORS)
def test_permission_matrix(world, route: str, actor: str) -> None:
    limiter.reset()
    client, headers = _client(world, actor)

    response = _call(client, headers, route, world, actor)

    expected = MATRIX[route][ACTORS.index(actor)]
    assert response.status_code == expected, response.text
    if expected >= 400:
        assert set(response.json()["error"]) == {"code", "message", "support_ref"}


@pytest.mark.contract
def test_every_protected_operation_is_matrixed_or_explicitly_deferred() -> None:
    # The SIG service route is internal but stays in the matrix to prove human sessions fail.
    assert set(MATRIX_OPERATION_IDS) == set(MATRIX) - {"sig_evidence_with_session"}
    assert set(MATRIX_OPERATION_IDS.values()).isdisjoint(KNOWN_UNCOVERED)

    protected = {
        operation["operationId"]
        for path in app.openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and operation.get("x-grp-access") == "protected"
    }
    accounted_for = set(MATRIX_OPERATION_IDS.values()) | KNOWN_UNCOVERED

    assert protected == accounted_for, (
        f"Unaccounted protected operations: {sorted(protected - accounted_for)}; "
        f"stale entries: {sorted(accounted_for - protected)}"
    )


@pytest.mark.contract
def test_hub_admin_sees_only_own_hub(world) -> None:
    limiter.reset()
    client, _ = _client(world, "hub_admin")

    hubs = client.get("/api/v1/admin/hubs").json()["hubs"]
    unknown = client.get("/api/v1/admin/hubs/missing/members")

    message = client.get(
        f"/api/v1/admin/hubs/adpc/members/{world['planner_membership']}/access-message"
    ).json()["message"]

    assert [hub["code"] for hub in hubs] == ["adpc"]
    assert world["settings"].grp_public_base_url in message
    assert unknown.status_code == 404


@pytest.mark.contract
def test_person_is_rate_limited_after_sixty_requests_a_minute(world) -> None:
    limiter.reset()
    client, _ = _client(world, "planner")

    statuses = [client.get("/api/v1/me").status_code for _ in range(61)]
    limiter.reset()

    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429
