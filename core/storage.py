from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from core.validation import sha256_file

_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9/_.-]{0,400}$")


class Storage(Protocol):
    """Replaceable storage boundary for rasters, uploads, results, and exports (Section 7.4)."""

    def put(self, key: str, source: Path) -> str: ...

    def get(self, key: str, destination: Path) -> Path: ...

    def exists(self, key: str) -> bool: ...

    def open_window(self, key: str) -> Iterator[Any]: ...

    def internal_url(self, key: str) -> str: ...


class LocalStorage:
    """Files under STORAGE_ROOT, addressed only by generated keys. Stored files are never
    overwritten: put() on an existing key fails unless the bytes are identical."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        if not _KEY_PATTERN.fullmatch(key) or ".." in key.split("/"):
            raise ValueError("Invalid storage key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage key")
        return path

    def put(self, key: str, source: Path) -> str:
        """Copy a file in and return its SHA-256 fingerprint."""

        target = self._path(key)
        digest = sha256_file(source)
        if target.exists():
            if sha256_file(target) != digest:
                raise FileExistsError("A different file is already stored under this key")
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        shutil.copyfile(source, temporary)
        temporary.replace(target)
        return digest

    def get(self, key: str, destination: Path) -> Path:
        shutil.copyfile(self._path(key), destination)
        return destination

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def sha256(self, key: str) -> str:
        return sha256_file(self._path(key))

    @contextmanager
    def open_window(self, key: str) -> Iterator[Any]:
        """Open a raster for windowed reads (the worker reads only the pixels it needs)."""

        import rasterio

        with rasterio.open(self._path(key)) as dataset:
            yield dataset

    def internal_url(self, key: str) -> str:
        return self._path(key).as_uri()
