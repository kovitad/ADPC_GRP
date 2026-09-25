"""ADR-0030: sensitivity indicators are shown where planners look, never turned into counts."""

from uuid import uuid4

from api.maps import WITHHELD_INDICATORS, _planner_status
from core.assessment_models import Dataset, DatasetVersion, Feature
from core.centre_sensitivity import sample_points
from core.data_library_models import DatasetFile


def test_the_disability_indicator_is_withheld_from_planners_with_its_reason() -> None:
    status = _planner_status("disability_support")

    assert status["planner_status"] == "withheld"
    assert "data owner" in status["withheld_reason"]


def test_child_and_older_person_sensitivity_are_shown() -> None:
    for key in ("child_sensitivity", "elderly_sensitivity"):
        assert _planner_status(key) == {"planner_status": "shown", "withheld_reason": None}
    assert set(WITHHELD_INDICATORS) == {"disability_support"}


# --- per-centre values ------------------------------------------------------------------

UTM_ORIGIN = (500_000.0, 1_700_000.0)  # EPSG:32647, near 15.4 N 99 E
CELL = 100.0


def _raster_file(tmp_path, values):
    """A small EPSG:32647 float raster; NaN marks cells outside the indicator."""

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "sensitivity.tif"
    data = np.array(values, dtype="float32")
    with rasterio.open(
        path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0], count=1,
        dtype="float32", crs="EPSG:32647",
        transform=from_origin(UTM_ORIGIN[0], UTM_ORIGIN[1], CELL, CELL),
    ) as target:
        target.write(data, 1)
    return path


def _lonlat(col: float, row: float) -> tuple[float, float]:
    from rasterio.warp import transform

    x = UTM_ORIGIN[0] + (col + 0.5) * CELL
    y = UTM_ORIGIN[1] - (row + 0.5) * CELL
    lons, lats = transform("EPSG:32647", "EPSG:4326", [x], [y])
    return lons[0], lats[0]


def test_a_centre_reads_the_cell_it_stands_in_and_nothing_outside(tmp_path) -> None:
    import rasterio

    nan = float("nan")
    path = _raster_file(tmp_path, [[0.314159, 0.0], [nan, 1.0]])
    points = [_lonlat(0, 0), _lonlat(1, 0), _lonlat(0, 1), _lonlat(1, 1), _lonlat(9, 9)]
    with rasterio.open(path) as raster:
        values = sample_points(raster, points)

    # Rounded for display; an exact 0 stays 0; NaN and off-raster are "outside coverage".
    assert values == [0.31, 0.0, None, 1.0, None]


class _Storage:
    def __init__(self, path) -> None:
        self.path = path

    def open_window(self, key):
        import rasterio

        return rasterio.open(self.path)


def _world(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    import api.main  # noqa: F401  registers every model
    from core.access_models import Hub
    from core.db import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    hubs = {code: Hub(code=code, name=f"{code} Hub") for code in ("adpc", "other")}
    session.add_all(hubs.values())
    session.flush()

    def version(kind, meta, hub=None, title="T"):
        dataset = Dataset(id=uuid4(), type=kind, owner_kind="hub_local" if hub else "platform",
                          hub_id=hub.id if hub else None, title=title, provider="P")
        row = DatasetVersion(id=uuid4(), dataset_id=dataset.id, sha256=uuid4().hex * 2, meta=meta,
                             readiness="technically_valid", is_current=True)
        session.add_all([dataset, row])
        session.flush()
        return row

    centres = version("evacuation_centers", {})
    foreign = version("evacuation_centers", {}, hub=hubs["other"])
    child = version("vulnerability", {"indicator_key": "child_sensitivity"}, title="Child")
    disability = version("vulnerability", {"indicator_key": "disability_support"})
    for indicator in (child, disability):
        session.add(DatasetFile(dataset_version_id=indicator.id, role="source_geotiff",
                                storage_key=f"{indicator.id}.tif", sha256="e" * 64,
                                size_bytes=1, original_name="s.tif"))
    features = []
    for owner, (col, row) in ((centres, (0, 0)), (centres, (0, 1)), (foreign, (1, 1))):
        lon, lat = _lonlat(col, row)
        feature = Feature(id=uuid4(), dataset_version_id=owner.id, name="c", lon=lon, lat=lat,
                          attributes={})
        session.add(feature)
        features.append(feature)
    session.commit()
    return session, hubs, centres, foreign, features


def _planner(hub):
    from api.sessions import CurrentPrincipal
    from core.identity import MembershipView

    return CurrentPrincipal(
        user_id=uuid4(), email="p@example.test", display_name=None, is_platform_admin=False,
        memberships=(MembershipView(hub.id, hub.code, hub.name, "planner"),),
        issued_at=0, session_id="s",
    )


def test_values_are_sampled_once_and_served_only_for_shown_indicators(tmp_path) -> None:
    from sqlalchemy import func, select

    from api.maps import CentreIndicatorRequest, centre_indicator_values
    from core.centre_sensitivity import build_centre_sensitivity
    from core.data_library_models import CentreIndicatorValue

    nan = float("nan")
    storage = _Storage(_raster_file(tmp_path, [[0.42, 0.0], [nan, 0.9]]))
    session, hubs, centres, foreign, features = _world(tmp_path)

    written = build_centre_sensitivity(session, storage, centers_version_id=centres.id)
    again = build_centre_sensitivity(session, storage, centers_version_id=centres.id)
    build_centre_sensitivity(session, storage, centers_version_id=foreign.id)

    # The disability indicator is withheld, so it is never sampled.
    assert written == again == {"child_sensitivity": 1}
    assert session.scalar(select(func.count()).select_from(CentreIndicatorValue)) == 3

    body = centre_indicator_values(
        CentreIndicatorRequest(feature_ids=[feature.id for feature in features]),
        _planner(hubs["adpc"]),
        session,
    )
    assert [item["indicator_key"] for item in body["indicators"]] == ["child_sensitivity"]
    # The second centre is outside coverage; the other Hub's centre is not returned at all.
    assert body["values"] == {
        str(features[0].id): {"child_sensitivity": 0.42},
        str(features[1].id): {"child_sensitivity": None},
    }


def test_no_assessment_chat_or_ai_path_reads_centre_values() -> None:
    """ADR-0030 decision 3: display context only, enforced at the source."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    readers = [
        path.relative_to(root).as_posix()
        for folder in ("api", "core", "worker")
        for path in (root / folder).rglob("*.py")
        if "CentreIndicatorValue" in path.read_text(encoding="utf-8")
    ]
    assert sorted(readers) == [
        "api/maps.py",
        "core/centre_sensitivity.py",
        "core/data_library_models.py",
    ]
