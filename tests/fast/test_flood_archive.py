"""Research archive (ADR-0055): one file per table per finished day, no personal data."""

from __future__ import annotations

import dataclasses
import gzip
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.flood_evidence.archive import (
    TABLES,
    export_day,
    export_pending,
    manifest_key,
    table_key,
)
from core.flood_evidence.config import pilot_config
from core.flood_evidence.floodboard import clean_reports_csv, parse_reports
from core.flood_evidence.ingest import Pulled, ingest_body
from core.flood_evidence.models import FETCH_OK, FloodReview
from core.flood_evidence.observation import record_key, state_hash
from core.storage import LocalStorage

CONFIG = pilot_config("bangkok")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "floodboard"
ROADS = (FIXTURES / "roads_20261003.geojson").read_bytes()
REPORTS = (FIXTURES / "reports_20261003.csv").read_bytes()
DAY = date(2026, 10, 3)
AT = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
OFFICER = uuid4()
NOTE = "seen from the soi entrance by a named officer"


@pytest.fixture
def world(tmp_path) -> Iterator[dict]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    storage = LocalStorage(tmp_path / "storage")
    with Session(engine) as session:
        ingest_body(session, storage, CONFIG, CONFIG.source("floodboard_reports"),
                    Pulled(200, REPORTS, FETCH_OK), AT)
        ingest_body(session, storage, CONFIG, CONFIG.source("floodboard_roads"),
                    Pulled(200, ROADS, FETCH_OK), AT + timedelta(minutes=1))
        for target in ("incident-a", "incident-b"):
            session.add(FloodReview(
                pilot_id="bangkok", hub_id=uuid4(), user_id=OFFICER, target_kind="incident",
                target_id=target, action="flooding_seen", camera_id=None, note=NOTE,
                road_keys=["0123456789abcdef"], created_at=AT + timedelta(hours=1),
                expires_at=AT + timedelta(hours=3),
            ))
        session.commit()
    yield {"engine": engine, "storage": storage}


def _rows(storage: LocalStorage, table: str, day: date = DAY) -> list[dict]:
    raw = gzip.decompress(storage.read_bytes(table_key("bangkok", table, day)))
    return [json.loads(line) for line in raw.decode().splitlines()]


def test_a_finished_day_writes_every_table_and_a_manifest_once(world) -> None:
    storage = world["storage"]
    with Session(world["engine"]) as session:
        manifest = export_day(session, storage, CONFIG, DAY, NOW)
        assert manifest is not None
        assert set(manifest["tables"]) == set(TABLES)
        for table in TABLES:
            assert len(_rows(storage, table)) == manifest["tables"][table]["rows"]
        assert manifest["tables"]["road_state"]["rows"] > 0
        assert manifest["tables"]["report"]["rows"] > 0
        assert manifest["tables"]["label"]["rows"] == 2
        assert storage.exists(manifest_key("bangkok", DAY))
        # Written once: a second run changes nothing.
        assert export_day(session, storage, CONFIG, DAY, NOW) is None


def test_no_text_links_provider_ids_or_names_reach_the_archive(world) -> None:
    storage = world["storage"]
    with Session(world["engine"]) as session:
        export_day(session, storage, CONFIG, DAY, NOW)
    everything = "".join(
        gzip.decompress(storage.read_bytes(table_key("bangkok", t, DAY))).decode()
        for t in TABLES
    )
    assert "traffy:fixture" not in everything
    assert "redacted for fixture" not in everything
    assert "http" not in everything
    assert NOTE not in everything
    assert str(OFFICER) not in everything
    report = _rows(storage, "report")[0]
    assert set(report) >= {"report_key", "observed_at", "underlying_source", "rule_version"}


def test_officer_labels_keep_one_stable_pseudonym(world) -> None:
    storage = world["storage"]
    with Session(world["engine"]) as session:
        export_day(session, storage, CONFIG, DAY, NOW)
    labels = _rows(storage, "label")
    assert {row["label"] for row in labels} == {"flooding_seen"}
    assert len({row["checker"] for row in labels}) == 1
    assert labels[0]["method"] == "officer"


def test_rows_carry_their_rule_version(world) -> None:
    storage = world["storage"]
    with Session(world["engine"]) as session:
        export_day(session, storage, CONFIG, DAY, NOW)
    for table in ("road_state", "report", "facility_exposure"):
        rows = _rows(storage, table)
        assert rows and all(row["rule_version"] for row in rows), table


def test_today_and_replays_are_refused(world) -> None:
    storage = world["storage"]
    replay = dataclasses.replace(CONFIG, pilot_id="r0123456789a")
    with Session(world["engine"]) as session:
        with pytest.raises(ValueError, match="once it is over"):
            export_day(session, storage, CONFIG, NOW.date(), NOW)
        with pytest.raises(ValueError, match="replays"):
            export_day(session, storage, replay, DAY, NOW)


def test_every_finished_day_from_the_first_fetch_is_written(world) -> None:
    with Session(world["engine"]) as session:
        written = export_pending(session, world["storage"], CONFIG, NOW)
        assert written == ["2026-10-03", "2026-10-04"]
        assert export_pending(session, world["storage"], CONFIG, NOW) == []


def test_a_cleaned_capture_reads_to_the_same_reports() -> None:
    cleaned = clean_reports_csv(REPORTS)
    assert b"traffy:fixture" not in cleaned and b"redacted for fixture" not in cleaned
    assert clean_reports_csv(cleaned) == cleaned
    before = {record_key(d.external_id): state_hash(d) for d in parse_reports(REPORTS)}
    after = {record_key(d.external_id): state_hash(d) for d in parse_reports(cleaned)}
    assert before == after
