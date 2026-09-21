"""Data inspector rules (ADR-0006): safe paths, honest caching, one claim per job."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.access_models import Base
from core.data_folder import (
    FULL_HASH_LIMIT_BYTES,
    DataFolderError,
    fingerprint_file,
    folder_fingerprint,
    list_files,
    list_folders,
    resolve_folder,
)
from core.dataset_scan import Finding, LayerReport, describe_raster, find_problems
from core.inspection_jobs import (
    PREVIEW_FOLDERS,
    claim_next_inspection,
    process_inspection,
    request_inspection,
)
from core.inspection_models import DatasetInspection  # noqa: F401 - registers the table
from core.models import AssessmentState


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "data-in"
    (root / "floods").mkdir(parents=True)
    (root / "floods" / "depth.tif").write_bytes(b"not really a raster")
    (root / "notes.txt").write_text("a note", encoding="utf-8")
    return root


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------- a browser-supplied path never escapes the root ----------


@pytest.mark.fast
@pytest.mark.parametrize(
    "attempt",
    [
        "..",
        "../..",
        "floods/../../secrets",
        "/etc",
        "C:/Windows",
        "\\\\server\\share",
        "floods/../../../",
    ],
)
def test_a_folder_outside_the_root_is_refused(source: Path, attempt: str) -> None:
    with pytest.raises(DataFolderError):
        resolve_folder(source, attempt)


@pytest.mark.fast
def test_the_root_and_its_folders_resolve(source: Path) -> None:
    assert resolve_folder(source, "") == source.resolve()
    assert resolve_folder(source, "floods") == (source / "floods").resolve()
    assert resolve_folder(source, "/floods/") == (source / "floods").resolve()


@pytest.mark.fast
def test_a_folder_that_is_not_there_is_refused(source: Path) -> None:
    with pytest.raises(DataFolderError):
        resolve_folder(source, "nothing-here")


# ---------- the cache key notices a change ----------


@pytest.mark.fast
def test_editing_a_file_changes_the_folder_fingerprint(source: Path) -> None:
    before = folder_fingerprint(list_files(source, source))

    # Same length, so a size-and-time key would not notice; the content is different.
    (source / "notes.txt").write_text("a NOTE", encoding="utf-8")

    assert folder_fingerprint(list_files(source, source)) != before


@pytest.mark.fast
def test_the_fingerprint_does_not_depend_on_the_order_files_are_listed(source: Path) -> None:
    files = list_files(source, source)

    assert folder_fingerprint(files) == folder_fingerprint(list(reversed(files)))


@pytest.mark.fast
def test_a_small_file_is_hashed_whole_and_says_so(source: Path) -> None:
    _, method = fingerprint_file(source / "notes.txt")

    assert method == "sha256"
    assert all(item.fully_fingerprinted for item in list_files(source, source))


@pytest.mark.fast
def test_a_very_large_file_is_hashed_at_its_edges_and_is_marked(tmp_path: Path) -> None:
    root = tmp_path / "big"
    root.mkdir()
    huge = root / "vulnerability.tif"
    with huge.open("wb") as handle:
        handle.truncate(FULL_HASH_LIMIT_BYTES + 1)

    _, method = fingerprint_file(huge)

    assert method == "sha256-head-tail"
    assert not list_files(root, root)[0].fully_fingerprinted


@pytest.mark.fast
def test_folders_are_listed_with_the_root_first(source: Path) -> None:
    folders = list_folders(source)

    assert folders[0]["path"] == ""
    assert folders[0]["file_count"] == 2
    assert [item["path"] for item in folders[1:]] == ["floods"]


# ---------- queueing, caching and claiming ----------


def _ask(db: Session, source: Path, folder: str = ""):
    return request_inspection(
        db,
        root=source,
        folder=folder,
        hub_id=None,
        user_id=uuid4(),
        support_ref="GRP-TEST-01",
    )


@pytest.mark.fast
def test_an_unchanged_folder_reuses_the_stored_report(db: Session, source: Path) -> None:
    first = _ask(db, source)
    stored = db.get(DatasetInspection, first.inspection_id)
    stored.state = AssessmentState.SUCCEEDED
    stored.report = {"layers": [], "findings": []}
    db.commit()

    again = _ask(db, source)

    assert again.inspection_id == first.inspection_id
    assert again.cached is True


@pytest.mark.fast
def test_the_same_folder_uses_a_separate_cache_entry_per_profile(
    db: Session, source: Path
) -> None:
    common = {
        "root": source,
        "folder": "",
        "hub_id": None,
        "user_id": uuid4(),
        "support_ref": "GRP-TEST-PROFILE",
    }

    baseline = request_inspection(db, profile="grp_baseline", **common)
    general = request_inspection(db, profile="general", **common)

    assert baseline.inspection_id != general.inspection_id


def test_an_old_report_format_is_not_reused(db: Session, source: Path) -> None:
    first = _ask(db, source)
    stored = db.get(DatasetInspection, first.inspection_id)
    stored.state = AssessmentState.SUCCEEDED
    stored.report = {"layers": [], "findings": [{"title": "obsolete wording"}]}
    stored.fingerprint = folder_fingerprint(list_files(source, source))
    db.commit()

    again = _ask(db, source)

    assert again.inspection_id != first.inspection_id
    assert again.cached is False


@pytest.mark.fast
def test_a_changed_folder_is_read_again(db: Session, source: Path) -> None:
    first = _ask(db, source)
    stored = db.get(DatasetInspection, first.inspection_id)
    stored.state = AssessmentState.SUCCEEDED
    stored.report = {"layers": [], "findings": []}
    db.commit()

    (source / "notes.txt").write_text("changed after the report was stored", encoding="utf-8")
    again = _ask(db, source)

    assert again.inspection_id != first.inspection_id
    assert again.cached is False
    assert again.state == AssessmentState.QUEUED


@pytest.mark.fast
def test_an_empty_folder_is_refused(db: Session, tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()

    with pytest.raises(DataFolderError):
        _ask(db, root)


@pytest.mark.fast
def test_a_queued_inspection_is_claimed_once(db: Session, source: Path) -> None:
    asked = _ask(db, source)

    first = claim_next_inspection(db, lease_minutes=15)
    second = claim_next_inspection(db, lease_minutes=15)

    assert first == asked.inspection_id
    assert second is None, "a claimed inspection must not be handed to a second worker"


@pytest.mark.fast
def test_an_expired_lease_is_claimed_again(db: Session, source: Path) -> None:
    asked = _ask(db, source)
    claim_next_inspection(db, lease_minutes=15)
    stale = db.get(DatasetInspection, asked.inspection_id)
    stale.lease_until = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    assert claim_next_inspection(db, lease_minutes=15) == asked.inspection_id
    assert db.get(DatasetInspection, asked.inspection_id).attempt == 2


# ---------- findings say the right thing ----------


def test_a_crash_inside_one_inspection_fails_it_and_does_not_stop_the_worker(
    db: Session, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _ask(db, source)
    claim_next_inspection(db, lease_minutes=15)

    def broken(*_args, **_kwargs):
        raise ModuleNotFoundError("No module named 'pyogrio'")

    monkeypatch.setattr("core.dataset_scan.scan_folder", broken)
    assert process_inspection(db, source, asked.inspection_id) == AssessmentState.FAILED
    stored = db.get(DatasetInspection, asked.inspection_id)
    assert stored.error_code == "INTERNAL_ERROR"


def test_an_empty_raster_statistic_is_stored_as_no_value(
    db: Session, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _ask(db, source)
    claim_next_inspection(db, lease_minutes=15)
    monkeypatch.setattr(
        "core.dataset_scan.scan_folder",
        lambda *_a, **_k: {"layers": [{"value_min": float("nan"), "value_max": float("inf")}]},
    )
    assert process_inspection(db, source, asked.inspection_id) == AssessmentState.SUCCEEDED
    layer = db.get(DatasetInspection, asked.inspection_id).report["layers"][0]
    assert layer["value_min"] is None and layer["value_max"] is None


def test_a_district_preview_and_a_folder_report_never_share_a_cache_entry(
    db: Session, tmp_path: Path
) -> None:
    for folder in PREVIEW_FOLDERS:
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "layer.txt").write_text(folder, encoding="utf-8")
    common = {"root": tmp_path, "hub_id": None, "user_id": uuid4(), "support_ref": "GRP-T"}
    folder_report = request_inspection(db, folder="", **common)
    pua = request_inspection(db, folder="", district="Pua", **common)
    nan = request_inspection(db, folder="", district="Nan", **common)
    again = request_inspection(db, folder="", district="Pua", **common)
    assert len({folder_report.inspection_id, pua.inspection_id, nan.inspection_id}) == 3
    assert again.inspection_id == pua.inspection_id


def _grades(findings: list[Finding], title_part: str) -> list[str]:
    return [f.grade for f in findings if title_part in f.title]


@pytest.mark.fast
def test_a_mostly_empty_flood_layer_blocks_because_the_no_data_rule_is_undecided() -> None:
    layer = LayerReport(
        path="flood.tif", kind="raster", crs_epsg=4326, nodata=-9999.0, nodata_share=0.83
    )

    findings = find_problems([layer], ["flood.tif", "licence.txt"])

    assert _grades(findings, "is mostly empty") == ["blocker"]
    assert any("DEP-05" in f.detail for f in findings)


@pytest.mark.fast
def test_a_utm_vulnerability_raster_is_known_not_a_surprise() -> None:
    layer = LayerReport(
        path="disability.tif", kind="raster", crs_epsg=32647, nodata=0.0, nodata_share=0.1
    )

    findings = find_problems([layer], ["disability.tif", "readme.md"])

    assert _grades(findings, "is not EPSG:4326") == ["known"]


@pytest.mark.fast
def test_an_unexpected_projection_is_a_problem_not_a_known_one() -> None:
    layer = LayerReport(
        path="flood.tif", kind="raster", crs_epsg=3857, nodata=0.0, nodata_share=0.1
    )

    findings = find_problems([layer], ["flood.tif", "licence.txt"])

    assert _grades(findings, "is not EPSG:4326") == ["problem"]


@pytest.mark.fast
def test_general_profile_does_not_apply_grp_or_flood_assumptions() -> None:
    layer = LayerReport(
        path="local/elevation.tif",
        kind="raster",
        crs_epsg=3857,
        nodata=-9999.0,
        nodata_share=0.8,
        value_min=-20.0,
        value_max=3000.0,
    )

    findings = find_problems(
        [layer], ["local/elevation.tif", "metadata.txt"], profile="general"
    )

    titles = [finding.title for finding in findings]
    assert not any("not EPSG:4326" in title for title in titles)
    assert not any("mostly empty" in title for title in titles)
    assert not any("holds values over" in title for title in titles)
    assert not any("negative values" in title for title in titles)


def test_missing_provenance_is_registration_work_not_a_data_blocker() -> None:
    layer = LayerReport(path="flood.tif", kind="raster", crs_epsg=4326, nodata=0.0)

    findings = find_problems([layer], ["flood.tif"])

    assert _grades(findings, "Approval and provenance need registering") == ["known"]


@pytest.mark.fast
def test_a_provenance_file_clears_that_finding() -> None:
    layer = LayerReport(path="flood.tif", kind="raster", crs_epsg=4326, nodata=0.0)

    findings = find_problems([layer], ["flood.tif", "APPROVAL_AND_PROVENANCE.md"])

    assert _grades(findings, "Approval and provenance need registering") == []


@pytest.mark.fast
def test_a_shapefile_missing_its_projection_file_blocks() -> None:
    layer = LayerReport(
        path="shelters.shp",
        kind="vector",
        crs_epsg=4326,
        feature_count=10,
        geometry_type="Point",
        fields=[
            {"name": "name", "filled": 10, "empty": 0, "samples": [],
             "possibly_truncated": False}
        ],
    )

    findings = find_problems([layer], ["shelters.shp", "shelters.dbf", "licence.txt"])

    assert _grades(findings, "shelters.shx is missing") == ["blocker"]
    assert _grades(findings, "shelters.prj is missing") == ["blocker"]


@pytest.mark.fast
def test_cut_short_thai_columns_are_reported_as_known() -> None:
    layer = LayerReport(
        path="shelters.shp",
        kind="vector",
        crs_epsg=4326,
        feature_count=1,
        geometry_type="Point",
        fields=[
            {"name": "ละต", "filled": 1, "empty": 0, "samples": ["13.9"],
             "possibly_truncated": True}
        ],
    )

    findings = find_problems([layer], ["shelters.shp", "shelters.shx", "shelters.dbf",
                                       "shelters.prj", "licence.txt"])

    assert _grades(findings, "Thai column names are cut short") == ["known"]
    assert any("DEP-06" in f.detail for f in findings)


# ---------- the worker path, end to end on a generated raster ----------


@pytest.mark.fast
def test_raster_extrema_are_read_at_full_resolution(tmp_path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_origin

    path = tmp_path / "large-flood.tif"
    values = np.zeros((2048, 2048), dtype="float32")
    values[1, 1] = 99.0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2048,
        width=2048,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(100.0, 14.0, 0.01, 0.01),
        nodata=-9999.0,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as target:
        target.write(values, 1)

    layer = describe_raster(path, "large-flood.tif")

    assert layer.value_max == 99.0
    assert layer.value_stats_scope == "full_resolution"


@pytest.mark.fast
def test_the_worker_describes_a_real_raster_and_stores_it_once(db: Session, tmp_path: Path) -> None:
    """One inspection through claim, scan and cache, on a raster this test writes itself."""

    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_origin

    root = tmp_path / "data-in"
    root.mkdir()
    depths = np.array([[0.0, 1.5], [-9999.0, 12.0]], dtype="float32")
    with rasterio.open(
        root / "flood.tif",
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(100.0, 14.0, 0.01, 0.01),
        nodata=-9999.0,
    ) as target:
        target.write(depths, 1)

    asked = _ask(db, root)
    claimed = claim_next_inspection(db, lease_minutes=15)
    state = process_inspection(db, root, claimed)

    assert state == AssessmentState.SUCCEEDED
    stored = db.get(DatasetInspection, asked.inspection_id)
    report = stored.report
    layer = report["layers"][0]
    assert layer["crs_epsg"] == 4326
    assert layer["value_max"] == pytest.approx(12.0)
    # 12 m is suspiciously deep; absent provenance is setup work rather than a rejection of the
    # Data Science delivery (ADR-0007).
    assert any("holds values over 10" in f["title"] for f in report["findings"])
    assert any(f["grade"] == "known" for f in report["findings"])
    assert not any(f["grade"] == "blocker" for f in report["findings"])
    # Every file was small enough to hash whole, so the cache key is exact.
    assert report["partly_fingerprinted"] is False
    assert report["files"][0]["fully_fingerprinted"] is True

    # Nothing changed, so asking again reuses the stored report instead of reading the file.
    assert _ask(db, root).cached is True


@pytest.mark.fast
def test_a_file_changed_after_queueing_stops_the_job_safely(db: Session, source: Path) -> None:
    """A report must never describe files other than the ones it was fingerprinted against."""

    asked = _ask(db, source)
    claimed = claim_next_inspection(db, lease_minutes=15)
    (source / "notes.txt").write_text("changed while the job sat in the queue", encoding="utf-8")

    state = process_inspection(db, source, claimed)

    assert state == AssessmentState.FAILED
    stored = db.get(DatasetInspection, asked.inspection_id)
    assert stored.error_code == "INPUT_FINGERPRINT_MISMATCH"
    assert stored.report is None
