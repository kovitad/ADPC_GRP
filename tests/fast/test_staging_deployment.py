"""Dedicated VM deployment carries the same Thailand bootstrap contract as local Docker."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_staging_compose_mounts_source_read_only_and_worker_scratch_on_disk() -> None:
    compose = (REPOSITORY_ROOT / "deploy" / "compose.yml").read_text(encoding="utf-8")

    assert compose.count("/srv/grp/bootstrap-data:/srv/grp/data-in:ro") == 2
    assert compose.count("DATA_IN_ROOT: /srv/grp/data-in") == 2
    assert "/srv/grp/tmp:/tmp" in compose


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
