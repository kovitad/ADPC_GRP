from __future__ import annotations

import argparse
import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine

import core.access_models  # noqa: F401 - imports the tables into Base.metadata
from core.db import Base


@dataclass(frozen=True)
class LocalEnvironment:
    database_path: Path
    database_url_file: Path
    session_secret_file: Path


def _write_once(path: Path, value: str) -> bool:
    if path.exists():
        if not path.read_text(encoding="utf-8").strip():
            raise RuntimeError(f"Existing local configuration is empty: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{value}\n", encoding="utf-8")
    path.chmod(0o600)
    return True


def initialize_local_environment(base_dir: Path = Path(".")) -> LocalEnvironment:
    """Create idempotent SQLite and session-secret state under the ignored .local tree."""

    local_root = (base_dir / ".local").resolve()
    data_root = local_root / "data"
    secret_root = local_root / "secrets"
    data_root.mkdir(parents=True, exist_ok=True)
    secret_root.mkdir(parents=True, exist_ok=True)

    database_path = local_root / "grp.db"
    database_url_file = secret_root / "database_url"
    session_secret_file = secret_root / "session_secret"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    _write_once(database_url_file, database_url)
    _write_once(session_secret_file, secrets.token_urlsafe(48))

    engine = create_engine(database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    return LocalEnvironment(database_path, database_url_file, session_secret_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize an idempotent GRP local runtime")
    parser.add_argument("--base-dir", type=Path, default=Path("."))
    arguments = parser.parse_args()
    environment = initialize_local_environment(arguments.base_dir)
    print(f"Local database ready at {environment.database_path}")
    print(f"Session secret ready at {environment.session_secret_file}")


if __name__ == "__main__":
    main()
