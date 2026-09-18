"""Safe reading of the read-only source-data folder (ADR-0006).

Nothing here opens a GIS file, so the API may import it. It resolves a folder chosen in the
browser inside the configured root, lists what is there, and fingerprints it so a cached
inspection is never shown for files that have since changed.

Fingerprints deliberately do not use the modification time. A bind-mounted folder on Windows
can report a shifted time after a copy, and can keep the same time after an edit in place, so
a time-based cache key would be both noisy and unsafe. Files are hashed instead. Files larger
than FULL_HASH_LIMIT_BYTES are hashed at their head and tail only, and the report says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from core.validation import sha256_file

# Shapefiles and the flood tiles are hashed whole; the ~600 MB vulnerability rasters are not.
FULL_HASH_LIMIT_BYTES = 200 * 1024 * 1024
EDGE_BYTES = 8 * 1024 * 1024
MAX_FILES = 2000


class DataFolderError(ValueError):
    """The chosen folder cannot be used; the caller turns this into a safe message."""


@dataclass(frozen=True)
class SourceFile:
    relative_path: str
    size_bytes: int
    suffix: str
    fingerprint: str
    fingerprint_method: str  # "sha256" or "sha256-head-tail"

    @property
    def fully_fingerprinted(self) -> bool:
        return self.fingerprint_method == "sha256"


def resolve_folder(root: Path, relative: str) -> Path:
    """Resolve a browser-supplied folder inside `root`, or raise DataFolderError.

    The empty string means the root itself. Absolute paths, drive letters and `..` segments are
    refused before resolving, and the resolved path is checked to still be inside the root.
    """

    cleaned = (relative or "").strip().replace("\\", "/").strip("/")
    if cleaned:
        parts = [part for part in cleaned.split("/") if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise DataFolderError("That folder is outside the data folder.")
        candidate = Path(*parts)
        if candidate.is_absolute() or candidate.drive or candidate.anchor:
            raise DataFolderError("That folder is outside the data folder.")
    else:
        candidate = Path()

    base = root.resolve()
    target = (base / candidate).resolve()
    if target != base and base not in target.parents:
        raise DataFolderError("That folder is outside the data folder.")
    if not target.is_dir():
        raise DataFolderError("That folder is not in the data folder.")
    return target


def fingerprint_file(path: Path) -> tuple[str, str]:
    """Return (fingerprint, method) for one file."""

    size = path.stat().st_size
    if size <= FULL_HASH_LIMIT_BYTES:
        return sha256_file(path), "sha256"
    digest = sha256()
    digest.update(str(size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(EDGE_BYTES))
        handle.seek(max(size - EDGE_BYTES, EDGE_BYTES))
        digest.update(handle.read(EDGE_BYTES))
    return digest.hexdigest(), "sha256-head-tail"


def list_files(folder: Path, root: Path) -> list[SourceFile]:
    """Every file beneath `folder`, fingerprinted, sorted by path."""

    base = root.resolve()
    found: list[SourceFile] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if len(found) >= MAX_FILES:
            raise DataFolderError(
                f"That folder holds more than {MAX_FILES} files. Choose a folder inside it."
            )
        fingerprint, method = fingerprint_file(path)
        found.append(
            SourceFile(
                relative_path=path.resolve().relative_to(base).as_posix(),
                size_bytes=path.stat().st_size,
                suffix=path.suffix.lower(),
                fingerprint=fingerprint,
                fingerprint_method=method,
            )
        )
    return found


def folder_fingerprint(files: list[SourceFile]) -> str:
    """One fingerprint for the whole scope: the cache key for an inspection."""

    digest = sha256()
    for item in sorted(files, key=lambda f: f.relative_path):
        digest.update(f"{item.relative_path}\0{item.size_bytes}\0{item.fingerprint}\0".encode())
    return digest.hexdigest()


def list_folders(root: Path) -> list[dict[str, object]]:
    """Folders a person may pick, with what each holds. The root is offered first."""

    base = root.resolve()
    entries: list[dict[str, object]] = []
    for path in [base, *sorted(p for p in base.rglob("*") if p.is_dir())]:
        files = [p for p in path.rglob("*") if p.is_file()]
        entries.append(
            {
                "path": "" if path == base else path.relative_to(base).as_posix(),
                "name": "All source data" if path == base else path.name,
                "depth": 0 if path == base else len(path.relative_to(base).parts),
                "file_count": len(files),
                "size_bytes": sum(p.stat().st_size for p in files),
                "has_data_files": any(
                    p.suffix.lower() in (".shp", ".tif", ".tiff", ".geojson") for p in files
                ),
            }
        )
        if len(entries) > MAX_FILES:
            break
    return entries
