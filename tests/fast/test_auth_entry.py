from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def test_login_entry_fails_closed_until_oidc_is_configured() -> None:
    response = TestClient(app).get("/api/v1/auth/login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/?auth=unavailable"


def test_registration_entry_fails_closed_until_oidc_is_configured() -> None:
    response = TestClient(app).get(
        "/api/v1/auth/login?intent=register", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/register.html?registration=unavailable"


def test_admin_entry_fails_closed_until_oidc_is_configured() -> None:
    response = TestClient(app).get(
        "/api/v1/auth/login?intent=admin", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin-login.html?auth=unavailable"


def test_admin_shortcut_opens_the_dedicated_login() -> None:
    response = TestClient(app).get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin-login.html"


def test_sign_in_screen_uses_servir_without_local_password() -> None:
    page = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert "Continue with SERVIR" in page
    assert "/assets/servir-global-collaborative.png" in page
    assert "/assets/thailand-flood-planning-cover.webp" in page
    assert 'href="/api/v1/auth/login"' in page
    assert 'type="password"' not in page
    assert "does not create or store a" in page
    assert "separate password" in page
    assert 'href="/register.html"' in page
    assert "Register with an existing SIG account" in page


def test_sign_in_screen_explains_admin_membership_assignment() -> None:
    page = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "First sign-in without a GRP membership is denied" in page
    assert "Administrator assignment required" in script
    assert "no active GRP membership was found" in script
    assert "<form" not in page


def test_registration_requires_an_existing_sig_account() -> None:
    page = (WEB_ROOT / "register.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "register.js").read_text(encoding="utf-8")

    assert "Existing SIG account required" in page
    assert 'href="/api/v1/auth/login?intent=register"' in page
    assert "does not create a SIG account or GRP password" in page
    assert "Registration request received" in script
    assert 'type="password"' not in page
    assert "<form" not in page


def test_admin_screen_uses_sig_and_explains_preprovisioning() -> None:
    page = (WEB_ROOT / "admin-login.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "admin-login.js").read_text(encoding="utf-8")

    assert 'href="/api/v1/auth/login?intent=admin"' in page
    assert "does not grant administrator rights" in page
    assert "Administrator authority required" in script
    assert 'type="password"' not in page


def test_workspace_renders_server_data_without_inner_html() -> None:
    page = (WEB_ROOT / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "workspace.js").read_text(encoding="utf-8")

    assert "GRP.me()" in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "Hub memberships" in page
    # The menu comes from the shared top bar rendered by grp-common.js.
    common = (WEB_ROOT / "grp-common.js").read_text(encoding="utf-8")
    assert "data-grp-topbar" in page
    assert '"Administration"' in common
    assert "data-admin-menu" in common
    assert "innerHTML" not in common
    assert 'adminMenu.hidden = false' in script


def test_every_signed_in_page_uses_the_same_top_bar() -> None:
    for name in ("workspace.html", "assessments.html", "platform.html", "planning.html"):
        page = (WEB_ROOT / name).read_text(encoding="utf-8")
        assert "<header data-grp-topbar></header>" in page, name
        assert "workspace-nav" not in page and "pw-nav" not in page, name


def test_shared_menu_is_compact_and_wraps_on_small_screens() -> None:
    styles = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "@media (max-width: 900px)" in styles
    assert "flex-wrap: wrap" in styles
    assert "flex: 1 0 100%" in styles
    assert "padding: 0.36rem 0.58rem" in styles


def test_data_inspector_supports_profiles_and_shareable_reports() -> None:
    page = (WEB_ROOT / "data-inspector.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "data-inspector.js").read_text(encoding="utf-8")

    assert 'value="general"' in page
    assert 'value="grp_baseline"' in page
    assert "Download simple report" in page
    assert "Download consultation JSON" in page
    assert "Observations to confirm with the data team" in page
    assert ".local/data-in" in page
    assert "simpleReportHtml" in script
    assert "Source data confirmation request" in script
    assert "Request data-team confirmation of our current understanding" in script
    assert "Advice requested:" in script
    assert "delete finding.grade" in script
    assert "Do not load this dataset" not in script
    assert "Known already" not in script
    assert "full-resolution min/max" in script
    assert "text encoding" in script
    assert "(assumed)" in script
    assert "sampled" in script
    assert 'body: { folder, profile }' in script
    assert "innerHTML" not in script


def test_planning_location_lookup_requires_an_administrative_district() -> None:
    script = (WEB_ROOT / "planning.js").read_text(encoding="utf-8")

    # A district (amphoe, or khet in Bangkok) is required; a sub-district (tambon) is not.
    # OpenStreetMap returns it in `county` outside Bangkok and `suburb` inside it.
    assert "address.county," in script and "address.suburb," in script
    assert "sub-?district" in script
    assert "CURRENT_LOCATION_NO_DISTRICT" in script
    assert "reverse?format=jsonv2&zoom=${zoom}&addressdetails=1" in script
    assert "for (const zoom of [10, 12, 14, 8])" in script
    assert "polygon_geojson=1&addressdetails=1" in script
    # Clicking the map focuses that point's district and can add SIG evidence.
    assert 'map.on("click"' in script
    assert "const useMapPoint" in script


def test_planning_sig_embed_is_sandboxed_and_educational() -> None:
    page = (WEB_ROOT / "planning.html").read_text(encoding="utf-8")

    assert 'sandbox="allow-scripts allow-same-origin"' in page
    assert 'referrerpolicy="no-referrer"' in page
    assert 'loading="lazy"' in page
    assert "Flood hazard and asset exposure" in page
    assert "not a vulnerability-weighted" in page
    assert "Verify this exact brief and create a public receipt?" in page
    assert "replayable public receipt" in page

    script = (WEB_ROOT / "planning.js").read_text(encoding="utf-8")
    assert "floodToggle.checked = Boolean(selectedFloodLayer())" in script
    assert "configureFloodScenarios(layers.flood_scenarios)" in script
    assert 'data-flood-scenario' in page
    assert "RP20 and RP50 stay disabled until their source versions are imported" in script
    assert "centersToggle.checked = false" in script
    assert 'url.searchParams.set("boundary_id", state.selected.id)' in script
    assert (
        "Promise.all([loadFloodOverlay(selectedFloodLayer()), drawPendingCenters()])"
        not in script
    )
    assert "districtToggle.checked = state.boundaries.length > 0" in script
    assert "Loaded immediately from this login’s 10-minute cache." in script
    assert "Explore the available flood information" in script
    assert "Display-first MVP 1" in script
    assert "Available data:" in script
    assert "refresh: true" in script
    assert "loadAssessmentCenters(id)" in script
    assert "floodToggle.checked = true" in script
    assert "await loadFloodOverlay({ ...result.map, available: true })" in script
    assert 'data-ev-tab="summary"' in page
    assert "Where people could move" in page
    assert "Preparedness funding case" in page
    assert "renderAssessmentSummary(result, assessedCenters)" in script
    assert 'data-ev-tab="centres"' in page
    assert 'data-centre-search' in page
    assert 'data-ev-tab="vulnerable"' in page
    assert "Repeated names are kept as separate source records" in script
    assert "Flood and evacuation-centre layers are visible" in script
    assert "Candidate means lower mapped flood exposure" in page
    assert "Deterministic evidence summary · not publishable" in script
    assert "Key findings from SIG evidence" in script
    assert "Existing evidence may be restored from this browser tab" in script
    # The connection banner offers the one action that helps, and warns before expiry.
    assert "Sign in again" in script
    assert "SIG_EXPIRY_WARNING_SECONDS" in script
    assert "SIG metadata consistency" in script
    assert "payload.map_note" in script
    assert "verified flood-hazard map" in script
    assert "/planning.js?v=20260922f" in page
    assert "/planning.css?v=20260922b" in page
    assert 'const STORE_KEY = "grp.planning.v5"' in script
    assert "innerHTML" not in script


def test_assessments_and_planning_share_compatible_result_context() -> None:
    assessment_page = (WEB_ROOT / "assessments.html").read_text(encoding="utf-8")
    assessment_script = (WEB_ROOT / "assessments.js").read_text(encoding="utf-8")
    planning_script = (WEB_ROOT / "planning.js").read_text(encoding="utf-8")

    assert 'data-open-planning' in assessment_page
    assert 'data-incompatible' in assessment_page
    assert "/assessments.js?v=20260922a" in assessment_page
    assert "Boolean(dataset.synthetic) === Boolean(boundary.synthetic)" in assessment_script
    assert "Real district: synthetic test inputs are excluded." in assessment_script
    assert "/planning.html?assessment_id=" in assessment_script
    assert 'get("assessment_id")' in planning_script
    assert "/assessments.html?assessment_id=" in planning_script
    assert "data-incompatible-result" in (WEB_ROOT / "planning.html").read_text(encoding="utf-8")
