"""Dedicated VM deployment carries the same Thailand bootstrap contract as local Docker."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_staging_compose_mounts_source_read_only_and_worker_scratch_on_disk() -> None:
    compose = (REPOSITORY_ROOT / "deploy" / "compose.yml").read_text(encoding="utf-8")

    assert compose.count("/srv/grp/bootstrap-data:/srv/grp/data-in:ro") == 2
    assert compose.count("DATA_IN_ROOT: /srv/grp/data-in") == 2
    assert "/srv/grp/tmp:/tmp" in compose


def test_entrypoint_populates_secret_tmpfs_before_transferring_directory_ownership() -> None:
    entrypoint = (REPOSITORY_ROOT / "deploy" / "container-entrypoint.sh").read_text(
        encoding="utf-8"
    )

    create = "install -d -o 0 -g 0 -m 0700 /run/grp-secrets"
    copy = 'install -o 0 -g 0 -m 0400 "$source" "/run/grp-secrets/$name"'
    transfer_file = 'chown 10001:10001 "/run/grp-secrets/$name"'
    transfer_directory = "chown 10001:10001 /run/grp-secrets"
    assert entrypoint.index(create) < entrypoint.index(copy)
    assert entrypoint.index(copy) < entrypoint.index(transfer_file)
    assert entrypoint.index(transfer_file) < entrypoint.index(transfer_directory)
    assert "install -d -o 10001" not in entrypoint


def test_staging_secret_file_settings_use_the_container_tmpfs_copy() -> None:
    environment = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")

    file_settings = [
        line
        for line in environment.splitlines()
        if "_FILE=/run/" in line and not line.lstrip().startswith("#")
    ]
    assert file_settings
    assert all("=/run/grp-secrets/" in line for line in file_settings)
    assert "/run/source-secrets/" not in environment


def test_staging_sets_permanent_feed_address_but_keeps_public_routes_off() -> None:
    environment = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    script = (REPOSITORY_ROOT / "deploy" / "bootstrap-ubuntu.sh").read_text(
        encoding="utf-8"
    )

    assert 'set_env_value GRP_PUBLIC_FEED_BASE_URL "https://$DOMAIN"' in script
    assert '--small-host) SMALL_HOST="true"' in script
    assert '--enable-thaiwater-shadow) ENABLE_THAIWATER_SHADOW="true"' in script
    assert 'set_env_value THAIWATER_API_KEY_FILE "/run/grp-secrets/thaiwater_api_key"' in script
    assert 'read -r -s -p "ThaiWater API key: " THAIWATER_KEY' in script
    assert "FLOOD_FEED_PUBLIC=false" in environment
    assert "AIR_QUALITY_FEED_PUBLIC=false" in environment


def test_container_publish_waits_for_successful_main_ci_and_tags_the_exact_sha() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "container.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_run:" in workflow
    assert "workflows: [CI]" in workflow
    assert "branches: [main]" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in workflow
    assert "git rev-parse --short=7 HEAD" in workflow
    assert "type=raw,value=sha-${{ steps.release.outputs.short_sha }}" in workflow
    assert "platforms: linux/amd64" in workflow


def test_running_container_cli_uses_the_non_root_secret_owner() -> None:
    script = (REPOSITORY_ROOT / "deploy" / "bootstrap-ubuntu.sh").read_text(
        encoding="utf-8"
    )

    command = "exec --no-TTY --user 10001:10001 api python -m grpcli."
    assert script.count(command) == 4
    assert "exec --no-TTY api python" not in script


def test_staging_bootstrap_can_provision_and_install_thailand_data() -> None:
    script = (REPOSITORY_ROOT / "deploy" / "bootstrap-ubuntu.sh").read_text(
        encoding="utf-8"
    )
    runbook = (REPOSITORY_ROOT / "deploy" / "BOOTSTRAP.md").read_text(encoding="utf-8")

    assert 'SOURCE_DATA_DIR="${BASE_DIR}/bootstrap-data"' in script
    assert '--bootstrap-thailand-data requires --admin-email' in script
    assert "bootstrap-platform-admin" in script
    assert "python -m grpcli.bootstrap install-thailand" in script
    assert "python -m grpcli.bootstrap status" in script
    assert "/srv/grp/bootstrap-data/administrative_boundary/district_boundary/" in runbook
