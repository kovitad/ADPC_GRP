"""Managed import staging verifies bytes and promotes only generated immutable keys."""

from pathlib import Path
from uuid import uuid4

import pytest

from core.data_import_jobs import ImportClaim
from core.import_staging import (
    SourceFile,
    cleanup_import_staging,
    promote_staged_import,
    stage_import_files,
)
from core.storage import LocalStorage


def _source(path: Path, content: bytes = b"district-boundary") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.fast
def test_stage_and_promote_builds_verified_immutable_manifest(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    storage = LocalStorage(tmp_path / "managed")
    shp = _source(source_root / "delivered" / "district.shp")
    dbf = _source(source_root / "delivered" / "district.dbf", b"attributes")
    claim = ImportClaim(uuid4(), 1)

    staged = stage_import_files(
        storage,
        claim,
        source_root=source_root,
        files=[
            SourceFile("source_shp", shp, "boundary.shp", {"component": "geometry"}),
            SourceFile("source_dbf", dbf, "boundary.dbf", {"component": "attributes"}),
        ],
    )
    dataset_id = uuid4()
    version_id = uuid4()
    promoted = promote_staged_import(storage, staged, dataset_id=dataset_id, version_id=version_id)

    assert staged.total_bytes == len(b"district-boundaryattributes")
    assert len(promoted.files) == 2
    assert storage.exists(promoted.manifest_key)
    assert all(storage.sha256(item.storage_key) == item.sha256 for item in promoted.files)
    assert promoted.manifest["manifest_sha256"] == promoted.manifest_sha256
    assert {item.storage_key.rsplit("/", 1)[-1] for item in promoted.files} == {
        "boundary.shp",
        "boundary.dbf",
    }

    cleanup_import_staging(storage, claim)
    assert not storage.exists(staged.source_manifest_key)
    assert storage.exists(promoted.manifest_key)


@pytest.mark.fast
def test_staging_rejects_source_escape_and_user_controlled_managed_name(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    outside = _source(tmp_path / "outside.shp")
    inside = _source(source_root / "inside.shp")
    storage = LocalStorage(tmp_path / "managed")
    claim = ImportClaim(uuid4(), 1)

    with pytest.raises(ValueError, match="outside"):
        stage_import_files(
            storage,
            claim,
            source_root=source_root,
            files=[SourceFile("source_shp", outside, "boundary.shp", {})],
        )
    with pytest.raises(ValueError, match="managed filename"):
        stage_import_files(
            storage,
            claim,
            source_root=source_root,
            files=[SourceFile("source_shp", inside, "../source.shp", {})],
        )


@pytest.mark.fast
def test_promotion_is_idempotent_but_fails_closed_on_key_collision(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source = _source(source_root / "district.shp")
    storage = LocalStorage(tmp_path / "managed")
    claim = ImportClaim(uuid4(), 1)
    staged = stage_import_files(
        storage,
        claim,
        source_root=source_root,
        files=[SourceFile("source_shp", source, "boundary.shp", {})],
    )
    dataset_id = uuid4()
    version_id = uuid4()

    first = promote_staged_import(storage, staged, dataset_id=dataset_id, version_id=version_id)
    second = promote_staged_import(storage, staged, dataset_id=dataset_id, version_id=version_id)
    assert second.manifest_sha256 == first.manifest_sha256

    final_path = storage.root / first.files[0].storage_key
    final_path.write_bytes(b"tampered")
    with pytest.raises(FileExistsError):
        promote_staged_import(storage, staged, dataset_id=dataset_id, version_id=version_id)


@pytest.mark.fast
def test_reclaimed_attempt_reuses_the_same_content_manifest(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source = _source(source_root / "district.shp")
    storage = LocalStorage(tmp_path / "managed")
    import_id = uuid4()
    specs = [SourceFile("source_shp", source, "boundary.shp", {})]
    first_stage = stage_import_files(
        storage,
        ImportClaim(import_id, 1),
        source_root=source_root,
        files=specs,
    )
    reclaimed_stage = stage_import_files(
        storage,
        ImportClaim(import_id, 2),
        source_root=source_root,
        files=specs,
    )
    dataset_id = uuid4()
    version_id = uuid4()

    first = promote_staged_import(
        storage, first_stage, dataset_id=dataset_id, version_id=version_id
    )
    reclaimed = promote_staged_import(
        storage, reclaimed_stage, dataset_id=dataset_id, version_id=version_id
    )

    assert first_stage.source_manifest_sha256 == reclaimed_stage.source_manifest_sha256
    assert first.manifest_sha256 == reclaimed.manifest_sha256
