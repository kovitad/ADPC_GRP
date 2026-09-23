"""Local Developer-only quarantine for uploaded shelter Shapefile bundles.

The API streams the archive to a generated job directory. This module validates
the ZIP directory before extracting any member and never uses ``extractall``.
Database rows hold workflow metadata; large source bytes stay in managed storage.
"""

from __future__ import annotations

import os
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from core.shelter_import import (
    OPTIONAL_SUFFIXES,
    REQUIRED_SUFFIXES,
    SHELTER_SOURCE_REF,
    SHELTER_STEM,
)

MAX_ARCHIVE_MEMBERS = 12
MAX_MEMBER_COMPRESSION_RATIO = 100


class BrowserUploadError(ValueError):
    """An uploaded archive failed the deterministic quarantine gate."""


@dataclass(frozen=True)
class PreparedShelterUpload:
    source_ref: str
    filenames: tuple[str, ...]
    compressed_bytes: int
    uncompressed_bytes: int


def upload_prefix(import_id: UUID) -> str:
    return f"quarantine/browser-uploads/{import_id}"


def upload_directory(storage_root: Path, import_id: UUID) -> Path:
    return storage_root.resolve() / upload_prefix(import_id)


def shelter_source_ref(import_id: UUID) -> str:
    return f"{upload_prefix(import_id)}/source/{SHELTER_SOURCE_REF}"


def _safe_member_name(info: zipfile.ZipInfo) -> str:
    raw = info.filename.replace("\\", "/")
    path = PurePosixPath(raw)
    if info.is_dir() or path.is_absolute() or len(path.parts) != 1 or path.name != raw:
        raise BrowserUploadError("The ZIP must contain files only, without folders or paths")
    unix_mode = info.external_attr >> 16
    if unix_mode and stat.S_ISLNK(unix_mode):
        raise BrowserUploadError("The ZIP must not contain symbolic links")
    if info.flag_bits & 0x1:
        raise BrowserUploadError("Encrypted ZIP files are not accepted")
    return path.name


def extract_shelter_archive(
    archive_path: Path,
    storage_root: Path,
    import_id: UUID,
    *,
    max_uncompressed_bytes: int,
) -> PreparedShelterUpload:
    """Validate and extract one exact DDPM Shapefile bundle into quarantine."""

    allowed = {f"{SHELTER_STEM}{suffix}" for suffix in (*REQUIRED_SUFFIXES, *OPTIONAL_SUFFIXES)}
    required = {f"{SHELTER_STEM}{suffix}" for suffix in REQUIRED_SUFFIXES}
    base = upload_directory(storage_root, import_id)
    target = storage_root.resolve() / shelter_source_ref(import_id)
    partial = base / "source.partial" / SHELTER_SOURCE_REF
    try:
        with zipfile.ZipFile(archive_path) as bundle:
            infos = bundle.infolist()
            if not infos or len(infos) > MAX_ARCHIVE_MEMBERS:
                raise BrowserUploadError(
                    f"The ZIP must contain 1 to {MAX_ARCHIVE_MEMBERS} Shapefile components"
                )
            names: list[str] = []
            seen: set[str] = set()
            total = 0
            for info in infos:
                name = _safe_member_name(info)
                if name not in allowed:
                    raise BrowserUploadError(
                        "The ZIP may contain only the ddpm_shelters Shapefile components"
                    )
                if name in seen:
                    raise BrowserUploadError("The ZIP contains a duplicate filename")
                if info.file_size < 0 or info.compress_size < 0:
                    raise BrowserUploadError("The ZIP contains an invalid file size")
                if (
                    info.file_size > 1024 * 1024
                    and info.file_size > max(1, info.compress_size) * MAX_MEMBER_COMPRESSION_RATIO
                ):
                    raise BrowserUploadError("The ZIP contains a suspicious compression ratio")
                total += info.file_size
                if total > max_uncompressed_bytes:
                    raise BrowserUploadError("The extracted Shapefile bundle is too large")
                names.append(name)
                seen.add(name)
            missing = sorted(required - seen)
            if missing:
                raise BrowserUploadError(
                    "The ZIP is missing required Shapefile components: " + ", ".join(missing)
                )

            partial.mkdir(parents=True, exist_ok=False)
            for info, name in zip(infos, names, strict=True):
                destination = partial / name
                written = 0
                with bundle.open(info) as source, destination.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        written += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if written != info.file_size:
                    raise BrowserUploadError("A ZIP component did not match its declared size")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, target)
        shutil.rmtree(base / "source.partial", ignore_errors=True)
        return PreparedShelterUpload(
            source_ref=shelter_source_ref(import_id),
            filenames=tuple(sorted(names)),
            compressed_bytes=archive_path.stat().st_size,
            uncompressed_bytes=total,
        )
    except zipfile.BadZipFile as exc:
        raise BrowserUploadError("The uploaded file is not a valid ZIP archive") from exc
    except Exception:
        shutil.rmtree(base / "source.partial", ignore_errors=True)
        raise
