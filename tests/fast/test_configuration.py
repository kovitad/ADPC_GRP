import pytest

from grpcli.configure import write_secret_file


def test_secret_writer_does_not_overwrite_without_rotation_flag(tmp_path) -> None:
    path = tmp_path / "ai-key"
    write_secret_file(path, "first-token")

    with pytest.raises(ValueError, match="--replace"):
        write_secret_file(path, "second-token")

    assert path.read_text(encoding="utf-8") == "first-token\n"
