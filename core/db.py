from pathlib import Path

from sqlalchemy.orm import DeclarativeBase

from api.settings import get_settings


class Base(DeclarativeBase):
    """Declarative base for the 16 architecture-defined tables."""


def read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"Secret file is empty: {path}")
    return value


def get_database_url() -> str:
    return read_secret(get_settings().database_url_file)
