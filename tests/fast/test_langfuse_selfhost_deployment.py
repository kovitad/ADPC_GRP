from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = REPOSITORY_ROOT / "deploy" / "langfuse"


def test_langfuse_override_pins_release_and_private_service_ports() -> None:
    override = (DEPLOYMENT_ROOT / "compose.override.yml").read_text(encoding="utf-8")

    assert "langfuse/langfuse:4.59.0" in override
    assert "langfuse/langfuse-worker:4.59.0" in override
    assert "127.0.0.1:3000:3000" in override
    assert "127.0.0.1:9090:9000" in override
    assert "AUTH_DISABLE_SIGNUP: ${AUTH_DISABLE_SIGNUP:-true}" in override
    assert "AUTH_DISABLE_USERNAME_PASSWORD: ${AUTH_DISABLE_USERNAME_PASSWORD:-false}" in override
    assert "AUTH_GOOGLE_CLIENT_SECRET: ${AUTH_GOOGLE_CLIENT_SECRET:-}" in override
    assert 'LANGFUSE_CSP_ENFORCE_HTTPS: "true"' in override


def test_langfuse_proxy_publishes_only_the_named_https_origin() -> None:
    caddyfile = (DEPLOYMENT_ROOT / "Caddyfile").read_text(encoding="utf-8")

    assert "langfuse-risk-servir.adpc.net" in caddyfile
    assert "reverse_proxy @object_storage minio:9000" in caddyfile
    assert "reverse_proxy langfuse-web:3000" in caddyfile
    assert "Strict-Transport-Security" in caddyfile


def test_vendored_compose_records_exact_upstream_source() -> None:
    compose = (DEPLOYMENT_ROOT / "compose.upstream.yml").read_text(encoding="utf-8")

    assert "Langfuse v4.59.0" in compose
    assert "3aa29f7b41e3e007ab1efd2856ffca50ee7a9006" in compose
    assert "Local production changes belong in compose.override.yml" in compose
