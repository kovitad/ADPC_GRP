"""The Langfuse connector helper handles project credentials only in the local browser."""

from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def test_connector_helper_is_local_only_and_makes_no_requests() -> None:
    page = (WEB_ROOT / "langfuse-mcp-connector.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "langfuse-mcp-connector.js").read_text(encoding="utf-8")

    assert "connect-src 'none'" in page
    assert 'localHosts = new Set(["localhost", "127.0.0.1", "[::1]", "::1"])' in script
    assert "if (!isLocal)" in script
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script


def test_connector_helper_copies_basic_header_without_rendering_it() -> None:
    page = (WEB_ROOT / "langfuse-mcp-connector.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "langfuse-mcp-connector.js").read_text(encoding="utf-8")

    assert "https://langfuse-risk-servir.adpc.net/api/public/mcp" in page
    assert 'validateKey(publicKey, "pk-lf-", "Public key")' in script
    assert 'validateKey(secretKey, "sk-lf-", "Secret key")' in script
    assert "window.btoa(`${publicKey}:${secretKey}`)" in script
    assert "await copyText(authorization)" in script
    assert "clearKeys();" in script
    assert "textContent = authorization" not in script
    assert 'type="password"' in page
    assert "disabled" in page
    assert "Add the copied value to Claude" in page
    assert "Header name: <code>Authorization</code>" in page
    assert "Header value: <code>Basic &lt;generated value&gt;</code>" in page
