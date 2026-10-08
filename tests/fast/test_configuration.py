import pytest

from api.settings import (
    Settings,
    global_risk_contributions_available,
    sig_user_tools_available,
)
from grpcli.configure import write_secret_file


def test_secret_writer_does_not_overwrite_without_rotation_flag(tmp_path) -> None:
    path = tmp_path / "ai-key"
    write_secret_file(path, "first-token")

    with pytest.raises(ValueError, match="--replace"):
        write_secret_file(path, "second-token")

    assert path.read_text(encoding="utf-8") == "first-token\n"


def test_global_risk_contributions_need_local_chat_or_an_explicit_server_switch() -> None:
    local = Settings(grp_env="dev", planning_chat_enabled=True)
    staging_off = Settings(grp_env="staging", planning_chat_enabled=False)
    staging_on = Settings(
        grp_env="staging",
        planning_chat_enabled=False,
        global_risk_contributions_enabled=True,
    )

    assert global_risk_contributions_available(local)
    assert not global_risk_contributions_available(staging_off)
    assert global_risk_contributions_available(staging_on)
    assert sig_user_tools_available(staging_on)
