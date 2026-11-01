"""Mangrove 360 brand assets are exact, local, and labelled as decorative."""

import hashlib
import json
from pathlib import Path

SOURCE = Path("docs/adhoc/mangrove360-brand-kit-v1")
WEB = Path("web")


def test_mangrove_360_assets_match_the_supplied_manifest() -> None:
    manifest = json.loads((SOURCE / "asset-manifest.json").read_text(encoding="utf-8"))

    for item in manifest["assets"]:
        deployed = WEB / "assets/mangrove360" / Path(item["file"]).name
        assert deployed.is_file()
        assert hashlib.sha256(deployed.read_bytes()).hexdigest() == item["sha256"]


def test_coastal_page_uses_the_brand_without_claiming_illustrations_are_evidence() -> None:
    page = (WEB / "coastal-zoning.html").read_text(encoding="utf-8")

    assert "Mangrove 360" in page
    assert "/assets/mangrove360/logo-primary.png" in page
    assert "/assets/mangrove360/dashboard-banner.png" in page
    assert "/assets/mangrove360/empty-state.png" in page
    assert "not geographic evidence" in page
    assert "carbon-credit estimate" in page
    assert 'type="button" data-run>' in page
    assert "All zoning classes" in page
    assert "Resort candidates" in page
    assert "data-map-notice" in page

    workflow = (WEB / "coastal-zoning.js").read_text(encoding="utf-8")
    assert "Check live evidence successfully before running" in workflow
    assert 'error.status === 401' in workflow
    assert "Sign in with SERVIR again" in workflow
    assert "applyResultView" in workflow
    assert "Bright outlines show exactly where" in workflow

    login = (WEB / "index.html").read_text(encoding="utf-8")
    assert "/assets/mangrove360/login-hero.png" in login
    assert "Continue with SERVIR" in login
    assert 'type="password"' not in login
