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
    assert "Platform Admin authority required" in script
    assert 'type="password"' not in page


def test_workspace_renders_server_data_without_inner_html() -> None:
    page = (WEB_ROOT / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "workspace.js").read_text(encoding="utf-8")

    assert 'fetch("/api/v1/me"' in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "Hub memberships" in page
    assert "Administration" in page
    assert "data-admin-menu" in page
    assert 'adminMenu.hidden = false' in script
