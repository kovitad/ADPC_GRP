from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, Protocol


class Storage(Protocol):
    """Replaceable storage boundary for rasters, uploads, results, and exports."""

    def put(self, key: str, source: Path) -> str: ...

    def get(self, key: str, destination: Path) -> Path: ...

    def exists(self, key: str) -> bool: ...

    def open_window(self, key: str, window: object) -> Iterator[BinaryIO]: ...

    def internal_url(self, key: str) -> str: ...
