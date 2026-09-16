from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def test_login_entry_fails_closed_until_oidc_is_configured() -> None:
    response = TestClient(app).get("/api/v1/auth/login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/?auth=unavailable"


def test_sign_in_screen_uses_servir_without_local_password() -> None:
    page = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert "Continue with SERVIR" in page
    assert 'href="/api/v1/auth/login"' in page
    assert 'type="password"' not in page
    assert "does not create or store a" in page
    assert "separate password" in page
    assert "Get access" not in page
    assert "access.html" not in page


def test_sign_in_screen_explains_admin_membership_assignment() -> None:
    page = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "First sign-in without a GRP membership is denied" in page
    assert "Administrator assignment required" in script
    assert "no active GRP membership was found" in script
    assert "<form" not in page


def test_workspace_renders_server_data_without_inner_html() -> None:
    page = (WEB_ROOT / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "workspace.js").read_text(encoding="utf-8")

    assert 'fetch("/api/v1/me"' in script
    assert "textContent" in script
    assert "innerHTML" not in script
    assert "Hub memberships" in page
