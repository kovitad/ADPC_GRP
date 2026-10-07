"""GRP-ARC-001 Section 9.4 permission matrix for the routes that exist today.

Requests go through the real session cookie, CSRF check, rate limiter and database
membership lookup; nothing is overridden except the database and settings.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

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
import api.planning
import api.platform
import api.uploads
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
    # The area profile is planning data: planning roles reach it, a Platform Admin with no
    # planning membership does not. The fixture has no boundary, so a reached route 404s
    # rather than confirming an area exists.
    "area_profile": (401, 404, 404, 404, 403),
    # The province list is planning data derived from supported districts. Planning roles read
    # it; a Platform Admin with no planning membership does not.
    "provinces": (401, 200, 200, 200, 403),
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
    "upload_evacuation_centers": (401, 403, 403, 403, 200),
    "accept_shelter_version": (401, 403, 403, 403, 404),
    # An unknown import is hidden after authorization, so allowed Admins receive 404.
    "read_import": (401, 403, 404, 404, 404),
    # Planning map layers require a Hub role; a Platform Admin has no implicit Hub access.
    "map_layers": (401, 200, 200, 200, 403),
    "hazard_overlay": (401, 404, 404, 404, 403),
    "vulnerability_overlay": (401, 404, 404, 404, 403),
    "dataset_features": (401, 404, 404, 404, 403),
    "live_flood": (401, 404, 404, 404, 403),
    "live_flood_summary": (401, 200, 200, 200, 403),
    "live_flood_source": (401, 200, 200, 200, 403),
    # ADR-0029: a planning conversation is its owner's, in a Hub they plan for. Every planning
    # role reads its own; a Platform Admin with no planning membership has none to read.
    "read_conversation": (401, 200, 200, 200, 403),
    "clear_conversation": (401, 200, 200, 200, 403),
    # ADR-0030: centre sensitivity values are planning display context, like the map layers.
    "centre_indicator_values": (401, 200, 200, 200, 403),
    # ADR-0032: contributions use the SERVIR sign-in, which exists only where the planning chat
    # runs (local development, ADR-0004). This fixture is not dev, so every signed-in caller is
    # told the feature is not here; tests/fast/test_contributions.py covers the Hub and sender
    # rules where it is.
    "list_contributions": (401, 404, 404, 404, 404),
    "check_contribution": (401, 404, 404, 404, 404),
    "on_global_risk": (401, 404, 404, 404, 404),
    # ADR-0052: live-feed contributions follow the same dev-only rule.
    "platform_feeds": (401, 404, 404, 404, 404),
    "feed_check": (401, 404, 404, 404, 404),
    # ADR-0033: the district summary downloads need a planning role; an unknown district is not
    # found, and a Platform Admin with no planning membership is refused first.
    "summary_docx": (401, 404, 404, 404, 403),
    "summary_centres_csv": (401, 404, 404, 404, 403),
    "read_contribution": (401, 404, 404, 404, 404),
    "refresh_contribution": (401, 404, 404, 404, 404),
    # ADR-0034: the Planning layer picker follows the planning conversation: every planning role
    # reads its own Hub's list, a Platform Admin with no planning membership has none.
    "global_risk_layers": (401, 200, 200, 200, 403),
    # Sub-district plan: area search and lookup by point follow the planning catalogue rules.
    "areas_search": (401, 200, 200, 200, 403),
    "areas_at": (401, 200, 200, 200, 403),
    # ADR-0036: the River Watch pilot is for Admins. An unknown reach is not found, after the
    # caller is authorized, so no matrix case reaches GEOGLOWS.
    "river_watch_reaches": (401, 403, 200, 200, 200),
    "river_watch_forecast": (401, 403, 404, 404, 404),
    "river_watch_feed_preview": (401, 403, 404, 404, 404),
    "river_watch_raw": (401, 403, 404, 404, 404),
    # Phase B1 practice example: made-up data, Admins only like the rest of the Pilot tab.
    "hand_practice": (401, 403, 200, 200, 200),
    "river_watch_districts": (401, 403, 200, 200, 200),
    "river_watch_district": (401, 403, 404, 404, 404),
    # ADR-0038: a flood pilot is open to every role in its configured Hubs (Bangkok: adpc) and to
    # Platform Admins; another Hub's Admin is refused. The list only names pilots you can open.
    "flood_pilots": (401, 200, 200, 200, 200),
    "flood_pilot": (401, 200, 200, 403, 200),
    "flood_situation": (401, 200, 200, 403, 200),
    "flood_government_observation_status": (401, 200, 200, 403, 200),
    "flood_roads": (401, 200, 200, 403, 200),
    "flood_reports": (401, 200, 200, 403, 200),
    "flood_areas": (401, 200, 200, 403, 200),
    "flood_cameras": (401, 200, 200, 403, 200),
    "flood_assets": (401, 200, 200, 403, 200),
    "flood_incidents": (401, 200, 200, 403, 200),
    # ADR-0052: the Global Risk feed follows the pilot rules; its anonymous copy is off by default.
    "flood_feed": (401, 200, 200, 403, 200),
    # No incident is stored in the fixture, so allowed callers are told it is not found.
    "flood_incident": (401, 404, 404, 403, 404),
    # ADR-0042: recording an observation needs a pilot-Hub membership. A Platform Admin with no
    # membership reads but never writes; no incident exists here, so members get 404.
    "flood_incident_review": (401, 404, 404, 403, 403),
    "flood_facility_access": (401, 404, 404, 403, 403),
    "flood_changes": (401, 200, 200, 403, 200),
    "flood_facts": (401, 200, 200, 403, 200),
    # A non-member Platform Admin gets the computed answer without AI (200, withheld).
    "flood_ask": (401, 200, 200, 403, 200),
    # ADR-0044: anyone who can open the pilot sees its replays; building, moving, restarting and
    # deleting one needs a pilot-Hub membership. The fixture has no stored fetches (422 for a new
    # replay) and no replay (404).
    "flood_replays": (401, 200, 200, 403, 200),
    "flood_replay_create": (401, 422, 422, 403, 403),
    "flood_replay": (401, 404, 404, 403, 404),
    "flood_replay_advance": (401, 404, 404, 403, 403),
    "flood_replay_restart": (401, 404, 404, 403, 403),
    "flood_replay_delete": (401, 404, 404, 403, 403),
    "flood_replay_inject_report": (401, 404, 404, 403, 403),
    "flood_replay_inject_outage": (401, 404, 404, 403, 403),
    "flood_weather": (401, 200, 200, 403, 200),
    # No road is stored in the fixture, so allowed callers are told it is not found.
    "flood_road_cameras": (401, 404, 404, 403, 404),
    # ADR-0051: the relay is off unless switched on, so members get 404 here.
    "flood_camera_frame": (401, 404, 404, 403, 404),
    # An unknown pilot is not found for any signed-in caller; it names no Hub to check.
    "flood_unknown_pilot": (401, 404, 404, 404, 404),
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
    "area_profile": "area_profile_api_v1_catalog_areas__boundary_id__profile_get",
    "provinces": "provinces_api_v1_catalog_provinces_get",
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
    "upload_evacuation_centers": (
        "upload_evacuation_centers_api_v1_uploads_evacuation_centers_post"
    ),
    "accept_shelter_version": (
        "accept_shelter_version_api_v1_data_library_versions__version_id__accept_post"
    ),
    "read_import": "read_import_api_v1_data_library_imports__import_id__get",
    "map_layers": "map_layers_api_v1_maps_layers_get",
    "hazard_overlay": "hazard_overlay_api_v1_maps_hazard__version_id__overlay_png_get",
    "vulnerability_overlay": (
        "vulnerability_overlay_api_v1_maps_vulnerability__version_id__overlay_png_get"
    ),
    "dataset_features": "dataset_features_api_v1_maps_datasets__version_id__features_get",
    "live_flood": "live_flood_api_v1_maps_live_flood_get",
    "live_flood_summary": "live_flood_summary_api_v1_maps_live_flood_summary_get",
    "live_flood_source": "live_flood_source_api_v1_maps_live_flood_sources__name__get",
    "read_conversation": "read_conversation_api_v1_planning_conversation_get",
    "clear_conversation": "clear_conversation_api_v1_planning_conversation_delete",
    "centre_indicator_values": "centre_indicator_values_api_v1_maps_centres_indicator_values_post",
    "summary_docx": "summary_docx_api_v1_planning_summary_docx_post",
    "summary_centres_csv": "summary_centres_csv_api_v1_planning_summary_centres_csv_get",
    "list_contributions": "list_contributions_api_v1_contributions_get",
    "check_contribution": "create_contribution_api_v1_contributions_post",
    "on_global_risk": "on_global_risk_api_v1_contributions_on_global_risk_get",
    "areas_search": "search_areas_api_v1_catalog_areas_search_get",
    "areas_at": "area_at_api_v1_catalog_areas_at_get",
    "platform_feeds": "list_platform_feeds_api_v1_contributions_platform_feeds_get",
    "feed_check": "check_live_feed_api_v1_contributions_feed_check_post",
    "read_contribution": "read_contribution_api_v1_contributions__contribution_id__get",
    "refresh_contribution": (
        "refresh_contribution_api_v1_contributions__contribution_id__refresh_post"
    ),
    "global_risk_layers": "global_risk_layers_api_v1_planning_global_risk_layers_get",
    "river_watch_reaches": "list_reaches_api_v1_pilot_river_watch_reaches_get",
    "river_watch_forecast": "river_forecast_api_v1_pilot_river_watch__reach_id__get",
    "river_watch_feed_preview": (
        "river_feed_preview_api_v1_pilot_river_watch__reach_id__feed_preview_get"
    ),
    "river_watch_raw": "river_raw_response_api_v1_pilot_river_watch__reach_id__raw__run__get",
    "hand_practice": "hand_practice_api_v1_pilot_hand_demo_get",
    "river_watch_districts": "list_districts_api_v1_pilot_river_watch_districts_get",
    "river_watch_district": (
        "read_district_api_v1_pilot_river_watch_districts__admin_code__get"
    ),
    "flood_pilots": "list_flood_pilots_api_v1_pilot_flood_get",
    "flood_pilot": "read_flood_pilot_api_v1_pilot_flood__pilot_id__get",
    "flood_situation": "read_situation_api_v1_pilot_flood__pilot_id__situation_get",
    "flood_government_observation_status": (
        "read_government_observation_status_"
        "api_v1_pilot_flood__pilot_id__government_observations_status_get"
    ),
    "flood_feed": "read_flood_feed_api_v1_pilot_flood__pilot_id__feed_json_get",
    "flood_roads": "read_roads_api_v1_pilot_flood__pilot_id__roads_get",
    "flood_reports": "read_reports_api_v1_pilot_flood__pilot_id__reports_get",
    "flood_areas": "read_areas_api_v1_pilot_flood__pilot_id__areas_get",
    "flood_cameras": "read_cameras_api_v1_pilot_flood__pilot_id__cameras_get",
    "flood_assets": "read_assets_api_v1_pilot_flood__pilot_id__assets_get",
    "flood_incidents": "read_incidents_api_v1_pilot_flood__pilot_id__incidents_get",
    "flood_incident": (
        "read_incident_api_v1_pilot_flood__pilot_id__incidents__incident_id__get"
    ),
    "flood_incident_review": (
        "post_incident_review_api_v1_pilot_flood__pilot_id__incidents__incident_id__reviews_post"
    ),
    "flood_facility_access": (
        "post_facility_access_api_v1_pilot_flood__pilot_id__facilities_access_post"
    ),
    "flood_changes": "read_changes_api_v1_pilot_flood__pilot_id__changes_get",
    "flood_facts": "read_facts_api_v1_pilot_flood__pilot_id__facts_get",
    "flood_ask": "ask_api_v1_pilot_flood__pilot_id__ask_post",
    "flood_replays": "list_replays_api_v1_pilot_flood__pilot_id__replays_get",
    "flood_replay_create": "post_replay_api_v1_pilot_flood__pilot_id__replays_post",
    "flood_replay": "read_replay_api_v1_pilot_flood__pilot_id__replays__replay_id__get",
    "flood_replay_advance": (
        "post_advance_api_v1_pilot_flood__pilot_id__replays__replay_id__advance_post"
    ),
    "flood_replay_restart": (
        "post_restart_api_v1_pilot_flood__pilot_id__replays__replay_id__restart_post"
    ),
    "flood_replay_delete": (
        "delete_replay_api_v1_pilot_flood__pilot_id__replays__replay_id__delete"
    ),
    "flood_replay_inject_report": (
        "post_inject_report_api_v1_pilot_flood__pilot_id__replays__replay_id__inject_report_post"
    ),
    "flood_replay_inject_outage": (
        "post_inject_outage_api_v1_pilot_flood__pilot_id__replays__replay_id__inject_outage_post"
    ),
    "flood_weather": "read_weather_api_v1_pilot_flood__pilot_id__weather_get",
    "flood_road_cameras": (
        "read_road_cameras_api_v1_pilot_flood__pilot_id__roads__road_id__cameras_get"
    ),
    "flood_camera_frame": (
        "read_camera_frame_api_v1_pilot_flood__pilot_id__cameras__camera_id__frame_jpg_get"
    ),
    "flood_unknown_pilot": "read_flood_pilot_api_v1_pilot_flood__pilot_id__get",
}

# Protected operations covered elsewhere. Remove an entry when its role behavior moves into MATRIX.
KNOWN_UNCOVERED = {
    # ADR-0061: tests/fast/test_air_quality_feed.py covers it without calling AQ Tracker.
    "read_air_quality_api_v1_air_quality_sea_latest_get",
    # AI gateway permission cases live in fast tests.
    "ai_test_call_api_v1_ai_test_call_post",
    # Golden assessment tests cover Hub submission.
    "submit_assessment_api_v1_assessments_post",
    # Golden tests cover Hub-scoped assessment lists.
    "list_assessments_api_v1_assessments_get",
    # Golden tests cover job reads.
    "assessment_status_api_v1_assessments__assessment_id__get",
    # Assessment worker tests cover the persistent user-facing progress trace.
    "assessment_trace_api_v1_assessments__assessment_id__trace_get",
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
    # Planning tests cover starting a lookup and reading only your own.
    "start_lookup_api_v1_planning_lookups_post",
    "read_lookup_api_v1_planning_lookups__job_id__get",
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
        storage_root=tmp_path_factory.mktemp("managed-data"),
        shelter_browser_upload_enabled=True,
        planning_chat_enabled=True,
    )
    patch = pytest.MonkeyPatch()
    for module in (
        api.access, api.admin, api.ai, api.auth, api.integrations.sig,
        api.permissions, api.planning, api.platform, api.data_inspector, api.data_library,
        api.maps, api.uploads,
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


def _shelter_archive() -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as bundle:
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            bundle.writestr(f"ddpm_shelters{suffix}", suffix.encode())
    return archive.getvalue()


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
    if route == "area_profile":
        return client.get(
            "/api/v1/catalog/areas/00000000-0000-7000-8000-000000000000/profile"
        )
    if route == "provinces":
        return client.get("/api/v1/catalog/provinces")
    if route == "access_message":
        return client.get(f"/api/v1/admin/hubs/adpc/members/{member}/access-message")
    if route == "upload_evacuation_centers":
        upload_headers = {
            **headers,
            "Idempotency-Key": f"permission-{route}",
            "X-Upload-Filename": "ddpm_shelters.zip",
            "Content-Type": "application/zip",
        }
        return client.post(
            "/api/v1/uploads/evacuation-centers",
            content=_shelter_archive(),
            headers=upload_headers,
        )
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
        "accept_shelter_version": (
            "POST",
            f"/api/v1/data-library/versions/{user_id}/accept",
            None,
        ),
        "read_import": ("GET", f"/api/v1/data-library/imports/{user_id}", None),
        "map_layers": ("GET", "/api/v1/maps/layers", None),
        "hazard_overlay": ("GET", f"/api/v1/maps/hazard/{user_id}/overlay.png", None),
        "vulnerability_overlay": (
            "GET",
            f"/api/v1/maps/vulnerability/{user_id}/overlay.png",
            None,
        ),
        "dataset_features": ("GET", f"/api/v1/maps/datasets/{user_id}/features", None),
        "live_flood": ("GET", f"/api/v1/maps/live-flood?boundary_id={user_id}", None),
        "live_flood_summary": ("GET", "/api/v1/maps/live-flood/summary", None),
        "live_flood_source": ("GET", "/api/v1/maps/live-flood/sources/outlines", None),
        "read_conversation": ("GET", "/api/v1/planning/conversation", None),
        "clear_conversation": ("DELETE", "/api/v1/planning/conversation", None),
        "centre_indicator_values": (
            "POST",
            "/api/v1/maps/centres/indicator-values",
            {"feature_ids": [str(user_id)]},
        ),
        "summary_docx": (
            "POST", "/api/v1/planning/summary.docx", {"boundary_id": str(user_id)}
        ),
        "summary_centres_csv": (
            "GET", f"/api/v1/planning/summary/centres.csv?boundary_id={user_id}", None
        ),
        "list_contributions": ("GET", "/api/v1/contributions", None),
        "check_contribution": (
            "POST",
            "/api/v1/contributions",
            {"hub_code": "adpc", "kind": "vector", "manifest": {}, "preview": True},
        ),
        "read_contribution": ("GET", f"/api/v1/contributions/{user_id}", None),
        "on_global_risk": ("GET", "/api/v1/contributions/on-global-risk", None),
        "areas_search": ("GET", "/api/v1/catalog/areas/search?q=bang", None),
        "areas_at": ("GET", "/api/v1/catalog/areas/at?lat=13.8&lon=100.5", None),
        "platform_feeds": ("GET", "/api/v1/contributions/platform-feeds", None),
        "feed_check": ("POST", "/api/v1/contributions/feed-check",
                       {"hub_code": "adpc", "url": "https://example.org/x.json",
                        "records_path": "a", "fields": {"b": "c"}}),
        "refresh_contribution": ("POST", f"/api/v1/contributions/{user_id}/refresh", None),
        "global_risk_layers": ("GET", "/api/v1/planning/global-risk-layers", None),
        "river_watch_reaches": ("GET", "/api/v1/pilot/river-watch/reaches", None),
        "river_watch_forecast": ("GET", "/api/v1/pilot/river-watch/1", None),
        "river_watch_feed_preview": ("GET", "/api/v1/pilot/river-watch/1/feed-preview", None),
        "river_watch_raw": ("GET", "/api/v1/pilot/river-watch/1/raw/2026100100", None),
        "hand_practice": ("GET", "/api/v1/pilot/hand-demo?stage_m=3", None),
        "river_watch_districts": ("GET", "/api/v1/pilot/river-watch/districts", None),
        "river_watch_district": ("GET", "/api/v1/pilot/river-watch/districts/no-such", None),
        "flood_pilots": ("GET", "/api/v1/pilot/flood", None),
        "flood_pilot": ("GET", "/api/v1/pilot/flood/bangkok", None),
        "flood_situation": ("GET", "/api/v1/pilot/flood/bangkok/situation", None),
        "flood_government_observation_status": (
            "GET",
            "/api/v1/pilot/flood/bangkok/government-observations/status",
            None,
        ),
        "flood_roads": ("GET", "/api/v1/pilot/flood/bangkok/roads", None),
        "flood_reports": ("GET", "/api/v1/pilot/flood/bangkok/reports", None),
        "flood_areas": ("GET", "/api/v1/pilot/flood/bangkok/areas", None),
        "flood_cameras": ("GET", "/api/v1/pilot/flood/bangkok/cameras", None),
        "flood_assets": ("GET", "/api/v1/pilot/flood/bangkok/assets", None),
        "flood_incidents": ("GET", "/api/v1/pilot/flood/bangkok/incidents", None),
        "flood_incident": ("GET", f"/api/v1/pilot/flood/bangkok/incidents/{user_id}", None),
        "flood_incident_review": (
            "POST", f"/api/v1/pilot/flood/bangkok/incidents/{user_id}/reviews",
            {"action": "flooding_seen"},
        ),
        "flood_facility_access": (
            "POST", "/api/v1/pilot/flood/bangkok/facilities/access",
            {"asset_id": "osm:node/0", "action": "access_disrupted"},
        ),
        "flood_changes": ("GET", "/api/v1/pilot/flood/bangkok/changes", None),
        "flood_facts": ("GET", "/api/v1/pilot/flood/bangkok/facts", None),
        "flood_ask": (
            "POST", "/api/v1/pilot/flood/bangkok/ask", {"question": "What changed?"}
        ),
        "flood_replays": ("GET", "/api/v1/pilot/flood/bangkok/replays", None),
        "flood_replay_create": (
            "POST", "/api/v1/pilot/flood/bangkok/replays",
            {"start_at": "2026-10-01T00:00:00Z", "end_at": "2026-10-01T01:00:00Z"},
        ),
        "flood_replay": ("GET", "/api/v1/pilot/flood/bangkok/replays/r00000000000", None),
        "flood_replay_advance": (
            "POST", "/api/v1/pilot/flood/bangkok/replays/r00000000000/advance",
            {"by_minutes": 10},
        ),
        "flood_replay_restart": (
            "POST", "/api/v1/pilot/flood/bangkok/replays/r00000000000/restart", None
        ),
        "flood_replay_delete": (
            "DELETE", "/api/v1/pilot/flood/bangkok/replays/r00000000000", None
        ),
        "flood_replay_inject_report": (
            "POST", "/api/v1/pilot/flood/bangkok/replays/r00000000000/inject-report",
            {"at": "2026-10-03T04:00:00Z", "lat": 13.8, "lon": 100.5},
        ),
        "flood_weather": ("GET", "/api/v1/pilot/flood/bangkok/weather", None),
        "flood_replay_inject_outage": (
            "POST", "/api/v1/pilot/flood/bangkok/replays/r00000000000/inject-outage",
            {"source_id": "floodboard_roads", "start": "2026-10-03T04:00:00Z",
             "end": "2026-10-03T04:30:00Z"},
        ),
        "flood_road_cameras": (
            "GET", "/api/v1/pilot/flood/bangkok/roads/0123456789abcdef/cameras", None
        ),
        "flood_camera_frame": (
            "GET", "/api/v1/pilot/flood/bangkok/cameras/bmatraffic%3A1362/frame.jpg", None
        ),
        "flood_unknown_pilot": ("GET", "/api/v1/pilot/flood/no-such", None),
        "flood_feed": ("GET", "/api/v1/pilot/flood/bangkok/feed.json", None),
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
def test_shelter_upload_retry_returns_the_same_complete_response(world) -> None:
    limiter.reset()
    client, headers = _client(world, "platform_admin")
    upload_headers = {
        **headers,
        "Idempotency-Key": "stable-upload-retry",
        "X-Upload-Filename": "ddpm_shelters.zip",
        "Content-Type": "application/zip",
    }
    archive = _shelter_archive()

    first = client.post(
        "/api/v1/uploads/evacuation-centers", content=archive, headers=upload_headers
    )
    retry = client.post(
        "/api/v1/uploads/evacuation-centers", content=archive, headers=upload_headers
    )

    assert first.status_code == 200, first.text
    assert retry.status_code == 200, retry.text
    assert first.json()["reused"] is False
    assert retry.json()["reused"] is True
    for field in ("import_id", "state", "received_bytes", "files", "support_ref"):
        assert retry.json()[field] == first.json()[field]


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


def test_the_camera_relay_serves_only_bmatraffic_pictures_when_switched_on(
    world, monkeypatch
) -> None:
    import api.flood_pilot as flood_module
    from core.flood_evidence.camera_relay import BmatrafficRelay

    picture = b"\xff\xd8" + b"x" * 20_000
    enabled = world["settings"].model_copy(update={"bmatraffic_relay_enabled": True})
    monkeypatch.setattr(flood_module, "get_settings", lambda: enabled)
    asked: list[str] = []

    def site(_session: str, path: str) -> tuple[int, str, bytes]:
        asked.append(path)
        return (200, "image/jpeg", picture) if path.startswith("/show.aspx") else (
            200, "text/html", b"<html>")

    monkeypatch.setattr(flood_module, "shared_relay", lambda: BmatrafficRelay(fetch=site))
    limiter.reset()
    client, headers = _client(world, "planner")
    base = "/api/v1/pilot/flood/bangkok/cameras"
    response = client.get(f"{base}/bmatraffic%3A1362/frame.jpg", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == picture
    # Only registry cameras from bmatraffic: another provider or an unknown ID never reaches it.
    asked.clear()
    for camera_id in ("bma%3AAC-DD-2-B-C1", "bmatraffic%3A99999999", "bmatraffic%3Aabc"):
        assert client.get(f"{base}/{camera_id}/frame.jpg", headers=headers).status_code == 404
    assert asked == []
    cameras = client.get(base, headers=headers).json()["cameras"]
    kinds = {(c["provider"], (c["live"] or {}).get("kind")) for c in cameras}
    assert ("BMA_TRAFFIC", "frames") in kinds and ("BMA_TRAFFIC", None) not in kinds


def test_the_public_flood_feed_is_closed_unless_switched_on(world, monkeypatch) -> None:
    import api.flood_pilot as flood_module

    limiter.reset()
    client, headers = _client(world, "planner")
    path = "/api/v1/public/flood/bangkok/feed.json"
    assert client.get(path).status_code == 404
    # The signed-in copy answers, with an ETag that gives 304 when nothing changed.
    signed_in = client.get("/api/v1/pilot/flood/bangkok/feed.json", headers=headers)
    assert signed_in.status_code == 200 and signed_in.headers["cache-control"].startswith("private")
    again = client.get("/api/v1/pilot/flood/bangkok/feed.json",
                       headers={**headers, "If-None-Match": signed_in.headers["etag"]})
    assert again.status_code == 304
    # A replay ID never resolves, even for a pilot member.
    replay = client.get("/api/v1/pilot/flood/r00000000000/feed.json", headers=headers)
    assert replay.status_code == 404

    enabled = world["settings"].model_copy(update={"flood_feed_public": True})
    monkeypatch.setattr(flood_module, "get_settings", lambda: enabled)
    # Enabling publication before a successful roads snapshot must not expose 56 misleading zeros.
    waiting = client.get(path)
    assert waiting.status_code == 503
    assert waiting.json()["error"]["code"] == "FLOOD_FEED_NOT_READY"

    ready_feed = {
        "checked_at": "2026-10-07T05:30:00Z",
        "as_of": "2026-10-07T05:30:00Z",
        "valid_until": "2026-10-07T06:00:00Z",
        "districts": [{"district_code": "1001", "active_incidents": 0}],
        "records": [],
    }
    monkeypatch.setattr(flood_module, "build_feed", lambda _session, _config: ready_feed)
    anonymous = client.get(path)
    assert anonymous.status_code == 200
    assert anonymous.headers["cache-control"] == "public, max-age=60"
    assert anonymous.json() == ready_feed
    assert client.get("/api/v1/public/flood/no-such/feed.json").status_code == 404
    assert client.get("/api/v1/public/flood/r00000000000/feed.json").status_code == 404


def test_the_public_thaiwater_feed_is_closed_unless_switched_on(world, monkeypatch) -> None:
    import api.flood_pilot as flood_module

    limiter.reset()
    client, _headers = _client(world, "anonymous")
    path = "/api/v1/public/flood/bangkok/government-observations/feed.json"
    assert client.get(path).status_code == 404

    enabled = world["settings"].model_copy(update={"thaiwater_feed_public": True})
    monkeypatch.setattr(flood_module, "get_settings", lambda: enabled)
    first = client.get(path)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "public, max-age=300"
    assert first.json()["records"] == []
    assert first.json()["attribution"].startswith("ThaiWater")
    again = client.get(path, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert client.get(
        "/api/v1/public/flood/no-such/government-observations/feed.json"
    ).status_code == 404
