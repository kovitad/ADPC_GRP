"""Retention (ADR-0045): old raw days and report IDs go, facts and history stay."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.flood_evidence.config import pilot_config
from core.flood_evidence.ingest import Pulled, ingest_body
from core.flood_evidence.models import (
    FETCH_OK,
    FloodAssetExposure,
    FloodObservation,
    FloodSourceFetch,
)
from core.flood_evidence.retention import PRUNED, delete_raw, prune
from core.storage import LocalStorage

CONFIG = pilot_config("bangkok")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "floodboard"
ROADS = (FIXTURES / "roads_20261003.geojson").read_bytes()
REPORTS = (FIXTURES / "reports_20261003.csv").read_bytes()
NOW = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
OLD = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)     # 17 days before NOW
RECENT = datetime(2026, 10, 19, 3, 0, tzinfo=UTC)  # 1 day before NOW


@pytest.fixture
def world(tmp_path) -> Iterator[dict]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    storage = LocalStorage(tmp_path / "storage")
    with Session(engine) as session:
        for at in (OLD, RECENT):
            ingest_body(session, storage, CONFIG, CONFIG.source("floodboard_roads"),
                        Pulled(200, ROADS, FETCH_OK), at)
            ingest_body(session, storage, CONFIG, CONFIG.source("floodboard_reports"),
                        Pulled(200, REPORTS, FETCH_OK), at + timedelta(minutes=1))
        session.commit()
    yield {"engine": engine, "storage": storage}


def _keys(session, before):
    return list(session.scalars(select(FloodSourceFetch.storage_key).where(
        FloodSourceFetch.retrieved_at < before)))


def test_old_raw_days_are_removed_and_recent_ones_kept(world) -> None:
    storage = world["storage"]
    with Session(world["engine"]) as session:
        old_keys = _keys(session, OLD + timedelta(hours=1))
        result = prune(session, CONFIG, NOW)
        # Nothing is deleted from storage before the database change is committed.
        assert all((storage.root / key).exists() for key in old_keys)
        session.commit()
        delete_raw(storage, result)
        assert result["raw_fetches_cleared"] == 2 and result["raw_days_removed"] == 2
        assert all(not (storage.root / key).exists() for key in old_keys)
        assert all(key is None for key in _keys(session, OLD + timedelta(hours=1)))
        recent = list(session.scalars(select(FloodSourceFetch).where(
            FloodSourceFetch.retrieved_at >= RECENT)))
        assert all(f.storage_key and (storage.root / f.storage_key).exists() for f in recent)
        # The proof of what was received stays.
        assert all(f.sha256 for f in session.scalars(select(FloodSourceFetch)))


def test_old_report_ids_become_opaque_but_their_facts_stay(world) -> None:
    with Session(world["engine"]) as session:
        # Thirty days later even the recent copies are past the raw cutoff.
        before = session.scalar(select(func.count()).select_from(FloodObservation))
        prune(session, CONFIG, NOW + timedelta(days=30))
        session.commit()
        reports = session.scalars(select(FloodObservation).where(
            FloodObservation.kind == "report")).all()
        assert reports and all(r.external_id.startswith(PRUNED) for r in reports)
        assert all("traffy:" not in r.external_id for r in reports)
        assert session.scalar(select(func.count()).select_from(FloodObservation)) == before


def test_recently_seen_report_ids_are_kept(world) -> None:
    with Session(world["engine"]) as session:
        prune(session, CONFIG, NOW)
        session.commit()
        ids = list(session.scalars(select(FloodObservation.external_id).where(
            FloodObservation.kind == "report")))
        assert any(i.startswith("traffy:") for i in ids)


def test_old_facility_states_are_deleted(world) -> None:
    with Session(world["engine"]) as session:
        fetch = session.scalar(select(FloodSourceFetch).order_by(FloodSourceFetch.retrieved_at))
        session.add(FloodAssetExposure(
            pilot_id="bangkok", fetch_id=fetch.id, asset_id="osm:node/1",
            exposure_state="no_report_nearby", access_state="access_unknown", road_keys=[],
            reasons=[], rule_version="t", computed_at=fetch.retrieved_at))
        session.commit()
        result = prune(session, CONFIG, NOW)
        session.commit()
        assert result["exposure_rows_removed"] >= 1
        assert session.scalar(select(FloodAssetExposure).where(
            FloodAssetExposure.fetch_id == fetch.id)) is None


def test_running_twice_changes_nothing_more(world) -> None:
    with Session(world["engine"]) as session:
        prune(session, CONFIG, NOW)
        session.commit()
        again = prune(session, CONFIG, NOW)
        assert again["raw_fetches_cleared"] == 0 and again["report_ids_pruned"] == 0


def test_retention_never_runs_on_a_replay_namespace(world) -> None:
    replay = dataclasses.replace(CONFIG, pilot_id="r0123456789a", base_id="bangkok")
    with Session(world["engine"]) as session, pytest.raises(ValueError):
        prune(session, replay, NOW)
