from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from core.validation import sha256_file

_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9/_.-]{0,400}$")


class Storage(Protocol):
    """Replaceable storage boundary for rasters, uploads, results, and exports (Section 7.4)."""

    def put(self, key: str, source: Path) -> str: ...

    def get(self, key: str, destination: Path) -> Path: ...

    def exists(self, key: str) -> bool: ...

    def promote(self, source_key: str, target_key: str, expected_sha256: str) -> str: ...

    def delete_prefix(self, prefix: str) -> None: ...

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
        temporary = target.with_name(f"{target.name}.partial.{uuid4().hex}")
        try:
            shutil.copyfile(source, temporary)
            if sha256_file(temporary) != digest:
                raise OSError("Stored copy failed checksum verification")
            with temporary.open("rb+") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # A hard-link create is atomic and never overwrites an immutable key. This also
                # closes the race between the existence check above and final publication.
                os.link(temporary, target)
            except FileExistsError:
                if sha256_file(target) != digest:
                    raise FileExistsError(
                        "A different file is already stored under this key"
                    ) from None
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def get(self, key: str, destination: Path) -> Path:
        shutil.copyfile(self._path(key), destination)
        return destination

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def promote(self, source_key: str, target_key: str, expected_sha256: str) -> str:
        """Copy a staged file to an immutable final key and verify both ends.

        This is intentionally idempotent. A retry may find the final bytes already present, but a
        key collision with different bytes fails closed.
        """

        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("Invalid expected SHA-256")
        source = self._path(source_key)
        if not source.is_file() or sha256_file(source) != expected_sha256:
            raise ValueError("Staged file is missing or failed checksum verification")
        digest = self.put(target_key, source)
        if digest != expected_sha256 or self.sha256(target_key) != expected_sha256:
            raise OSError("Promoted file failed checksum verification")
        return digest

    def delete_prefix(self, prefix: str) -> None:
        """Delete only a generated subtree, never the storage root or an individual loose key."""

        normalized = prefix.rstrip("/")
        if not normalized or "/" not in normalized:
            raise ValueError("Storage cleanup requires a nested prefix")
        path = self._path(normalized)
        if path.exists() and not path.is_dir():
            raise ValueError("Storage cleanup prefix is not a directory")
        shutil.rmtree(path, ignore_errors=True)

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
