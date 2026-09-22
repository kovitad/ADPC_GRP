from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_ubuntu_launcher_keeps_shared_host_ports_private() -> None:
    launcher = (REPOSITORY_ROOT / "scripts" / "docker-ubuntu.sh").read_text(
        encoding="utf-8"
    )
    compose = (REPOSITORY_ROOT / "deploy" / "compose.desktop.yml").read_text(
        encoding="utf-8"
    )

    assert '"127.0.0.1:8000:8000"' in compose
    assert "ports 80 and 443 are not used" in launcher.lower()
    assert "deploy/compose.desktop.yml" in launcher
    assert "deploy/compose.yml" not in launcher
    assert "bootstrap-ubuntu.sh" not in launcher


def test_ubuntu_launcher_uses_ignored_secret_files() -> None:
    launcher = (REPOSITORY_ROOT / "scripts" / "docker-ubuntu.sh").read_text(
        encoding="utf-8"
    )
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert 'SECRET_ROOT="$LOCAL_ROOT/docker/secrets"' in launcher
    assert 'chmod 600 "$SECRET_ROOT/ai_key_adpc"' in launcher
    assert "OPENAI_API_KEY=" not in launcher
    assert 'REPOSITORY_ROOT/.env"' in launcher
    assert "does not read it" in launcher
    assert ".local/" in gitignore


def test_shared_host_runbook_documents_tunnel_and_rerun() -> None:
    runbook = (REPOSITORY_ROOT / "deploy" / "UBUNTU_SHARED_HOST.md").read_text(
        encoding="utf-8"
    )

    assert "127.0.0.1:8000" in runbook
    assert "PuTTY" in runbook
    assert "safe to rerun" in runbook
    assert "--configure-ai" in runbook
    assert "Do not put `OPENAI_API_KEY`" in runbook
