"""Managed staging and immutable file promotion for data-library imports.

Only workers call this module. Source paths are constrained to the configured read-only source root,
all bytes are checksummed after copying, and final keys are generated rather than user-controlled.
Database visibility is finalized separately by ``promote_import_version``.
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from core.data_import_jobs import ImportClaim
from core.storage import Storage
from core.validation import canonical_sha256

_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_STORAGE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,199}$")


@dataclass(frozen=True)
class SourceFile:
    """One category-approved source file and its generated managed name."""

    role: str
    path: Path
    storage_name: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class StagedFile:
    role: str
    original_name: str
    storage_name: str
    staging_key: str
    size_bytes: int
    sha256: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class StagedImport:
    claim: ImportClaim
    files: tuple[StagedFile, ...]
    total_bytes: int
    source_manifest_key: str
    source_manifest_sha256: str


@dataclass(frozen=True)
class PromotedFile:
    role: str
    original_name: str
    storage_key: str
    size_bytes: int
    sha256: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class PromotedImport:
    files: tuple[PromotedFile, ...]
    total_bytes: int
    manifest_key: str
    manifest_sha256: str
    manifest: dict[str, object]


def _write_json_to_storage(storage: Storage, key: str, value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        path = Path(handle.name)
        handle.write(encoded)
    try:
        return storage.put(key, path)
    finally:
        path.unlink(missing_ok=True)


def _source_path(source_root: Path, candidate: Path) -> Path:
    root = source_root.resolve()
    resolved = candidate.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("Source file is outside the configured source root")
    if not resolved.is_file():
        raise ValueError("Required source file is missing")
    return resolved


def _validate_specs(files: list[SourceFile]) -> list[SourceFile]:
    if not files:
        raise ValueError("At least one source file is required")
    seen_roles: set[str] = set()
    seen_names: set[str] = set()
    for item in files:
        if not _ROLE_PATTERN.fullmatch(item.role):
            raise ValueError("Invalid generated file role")
        if not _STORAGE_NAME_PATTERN.fullmatch(item.storage_name) or ".." in item.storage_name:
            raise ValueError("Invalid generated managed filename")
        if item.role in seen_roles:
            raise ValueError("File roles must be unique within one dataset version")
        if item.storage_name in seen_names:
            raise ValueError("Managed filenames must be unique within one dataset version")
        seen_roles.add(item.role)
        seen_names.add(item.storage_name)
    return sorted(files, key=lambda item: (item.role, item.storage_name))


def stage_import_files(
    storage: Storage,
    claim: ImportClaim,
    *,
    source_root: Path,
    files: list[SourceFile],
) -> StagedImport:
    """Copy approved source files into attempt-scoped staging and recompute SHA-256."""

    staged: list[StagedFile] = []
    prefix = f"imports/{claim.import_id}/{claim.attempt}"
    for item in _validate_specs(files):
        source = _source_path(source_root, item.path)
        before = source.stat()
        staging_key = f"{prefix}/original/{item.storage_name}"
        digest = storage.put(staging_key, source)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Source file changed while it was being staged")
        staged.append(
            StagedFile(
                role=item.role,
                original_name=source.name,
                storage_name=item.storage_name,
                staging_key=staging_key,
                size_bytes=after.st_size,
                sha256=digest,
                metadata=dict(item.metadata),
            )
        )

    source_content: dict[str, object] = {
        "schema_version": 1,
        "files": [
            {
                "role": item.role,
                "original_name": item.original_name,
                "storage_name": item.storage_name,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
                "metadata": item.metadata,
            }
            for item in staged
        ],
        "total_bytes": sum(item.size_bytes for item in staged),
    }
    # The content fingerprint excludes attempt bookkeeping so a reclaimed retry produces exactly
    # the same final manifest and can safely reuse deterministic immutable keys.
    content_digest = canonical_sha256(source_content)
    source_manifest = {
        **source_content,
        "import_id": str(claim.import_id),
        "attempt": claim.attempt,
        "content_sha256": content_digest,
    }
    manifest_key = f"{prefix}/source-manifest.json"
    _write_json_to_storage(storage, manifest_key, source_manifest)
    return StagedImport(
        claim=claim,
        files=tuple(staged),
        total_bytes=int(source_content["total_bytes"]),
        source_manifest_key=manifest_key,
        source_manifest_sha256=content_digest,
    )


def promote_staged_import(
    storage: Storage,
    staged: StagedImport,
    *,
    dataset_id: UUID,
    version_id: UUID,
) -> PromotedImport:
    """Idempotently copy verified staged bytes to immutable dataset/version keys."""

    prefix = f"datasets/{dataset_id}/{version_id}"
    promoted: list[PromotedFile] = []
    for item in staged.files:
        target_key = f"{prefix}/original/{item.storage_name}"
        storage.promote(item.staging_key, target_key, item.sha256)
        promoted.append(
            PromotedFile(
                role=item.role,
                original_name=item.original_name,
                storage_key=target_key,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                metadata=dict(item.metadata),
            )
        )

    manifest: dict[str, object] = {
        "schema_version": 1,
        "source_manifest_sha256": staged.source_manifest_sha256,
        "files": [
            {
                "role": item.role,
                "original_name": item.original_name,
                "storage_key": item.storage_key,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
                "metadata": item.metadata,
            }
            for item in promoted
        ],
        "total_bytes": staged.total_bytes,
    }
    # The dataset-version fingerprint is the canonical manifest, not an order-dependent file hash.
    manifest_digest = canonical_sha256(manifest)
    manifest["manifest_sha256"] = manifest_digest
    staging_manifest_key = (
        f"imports/{staged.claim.import_id}/{staged.claim.attempt}/final-manifest.json"
    )
    written_digest = _write_json_to_storage(storage, staging_manifest_key, manifest)
    manifest_key = f"{prefix}/manifest.json"
    storage.promote(staging_manifest_key, manifest_key, written_digest)
    return PromotedImport(
        files=tuple(promoted),
        total_bytes=staged.total_bytes,
        manifest_key=manifest_key,
        manifest_sha256=manifest_digest,
        manifest=manifest,
    )


def cleanup_import_staging(storage: Storage, claim: ImportClaim) -> None:
    """Remove only this attempt's staging tree after durable database finalization."""

    storage.delete_prefix(f"imports/{claim.import_id}/{claim.attempt}")
