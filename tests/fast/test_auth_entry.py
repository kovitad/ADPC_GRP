from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def test_login_entry_fails_closed_until_oidc_adapter_exists() -> None:
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


def test_get_access_screen_does_not_offer_self_registration() -> None:
    page = (WEB_ROOT / "access.html").read_text(encoding="utf-8")

    assert "GRP does not support self-registration" in page
    assert "Your Hub administrator must approve access" in page
    assert "SIG account team sends the SERVIR invitation" in page
    assert "<form" not in page
