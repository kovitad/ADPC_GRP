"""Browser shelter uploads enter a bounded, path-safe local quarantine."""

from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from core.browser_uploads import BrowserUploadError, extract_shelter_archive
from core.shelter_import import REQUIRED_SUFFIXES, SHELTER_STEM


def _archive(path: Path, names: list[str]) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as bundle:
        for name in names:
            bundle.writestr(name, f"contents of {name}".encode())


@pytest.mark.fast
def test_exact_shelter_bundle_is_extracted_under_generated_quarantine(tmp_path: Path) -> None:
    archive = tmp_path / "shelters.zip"
    names = [f"{SHELTER_STEM}{suffix}" for suffix in REQUIRED_SUFFIXES]
    _archive(archive, names)
    import_id = uuid4()

    prepared = extract_shelter_archive(
        archive, tmp_path / "managed", import_id, max_uncompressed_bytes=1024 * 1024
    )

    source = tmp_path / "managed" / prepared.source_ref
    assert prepared.filenames == tuple(sorted(names))
    assert {item.name for item in source.iterdir()} == set(names)
    assert prepared.uncompressed_bytes == sum(len(f"contents of {name}".encode()) for name in names)


@pytest.mark.fast
def test_shelter_bundle_refuses_paths_before_extracting(tmp_path: Path) -> None:
    archive = tmp_path / "shelters.zip"
    names = [f"{SHELTER_STEM}{suffix}" for suffix in REQUIRED_SUFFIXES]
    names[-1] = f"../{names[-1]}"
    _archive(archive, names)

    with pytest.raises(BrowserUploadError, match="without folders or paths"):
        extract_shelter_archive(
            archive, tmp_path / "managed", uuid4(), max_uncompressed_bytes=1024 * 1024
        )


@pytest.mark.fast
def test_shelter_bundle_refuses_missing_sidecar(tmp_path: Path) -> None:
    archive = tmp_path / "shelters.zip"
    names = [f"{SHELTER_STEM}{suffix}" for suffix in REQUIRED_SUFFIXES[:-1]]
    _archive(archive, names)

    with pytest.raises(BrowserUploadError, match="missing required"):
        extract_shelter_archive(
            archive, tmp_path / "managed", uuid4(), max_uncompressed_bytes=1024 * 1024
        )
