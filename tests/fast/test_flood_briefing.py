"""What changed, and the facts an answer may use (ADR-0043, slice 7a)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import core.flood_evidence.briefing as briefing
from core.db import Base
from core.flood_evidence.config import pilot_config
from core.flood_evidence.models import (
    FETCH_OK,
    FloodIncident,
    FloodIncidentEvent,
    FloodIncidentRun,
    FloodReview,
    FloodSourceFetch,
)

CONFIG = pilot_config("bangkok")
START = datetime(2026, 10, 3, 4, 0, tzinfo=UTC)
CENTER = [100.5413, 13.8399]  # Pracha Chuen, Bang Sue (in the demo area)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _run(session, at, active):
    fetch = FloodSourceFetch(pilot_id="bangkok", source_id="floodboard_roads", url="x",
                             retrieved_at=at, outcome=FETCH_OK)
    session.add(fetch)
    session.flush()
    session.add(FloodIncidentRun(pilot_id="bangkok", fetch_id=fetch.id, snapshot_at=at,
                                 active_count=active, duration_ms=1))


def _incident(session, at, *, keys=("a" * 16,), confidence="low", conflict=False):
    incident = FloodIncident(
        pilot_id="bangkok", status="active", opened_at=at, last_active_at=at, last_snapshot_at=at,
        road_keys=list(keys), bbox=[100.54, 13.83, 100.55, 13.84], rule_version="t",
        summary={"road_keys": list(keys), "report_keys": [], "contrary_keys": [],
                 "confidence": confidence, "conflict": conflict, "reasons": ["source_types:traffy"],
                 "source_families": ["traffy"], "freshness_basis": "newest_report",
                 "newest_evidence_at": at.isoformat(), "freshness": "current", "center": CENTER,
                 "max_depth_cm": 30, "closed_roads": 0},
    )
    session.add(incident)
    session.flush()
    return incident


def _event(session, incident, at, kind, **detail):
    session.add(FloodIncidentEvent(pilot_id="bangkok", incident_id=incident.id, at=at, kind=kind,
                                   detail=detail))


def test_the_first_run_is_a_baseline_not_new_flooding(session) -> None:
    _run(session, START, 2)
    for _ in range(2):
        _event(session, _incident(session, START), START, "created")
    session.commit()
    changes = briefing.get_situation_changes(
        session, CONFIG, "corridor", START - timedelta(hours=1), START + timedelta(minutes=5))
    assert changes["window_starts_before_tracking"] is True
    assert changes["counts"]["new"] == 0
    assert changes["tracked_since"] == START.isoformat()


def test_changes_after_the_baseline_are_counted_by_kind(session) -> None:
    _run(session, START, 1)
    first = _incident(session, START)
    _event(session, first, START, "created")
    later = START + timedelta(minutes=30)
    _run(session, later, 2)
    second = _incident(session, later, keys=("b" * 16,))
    _event(session, second, later, "created")
    _event(session, first, later, "size_changed", before=1, after=4)
    _event(session, first, later, "conflict_started", contrary_keys=["x"])
    _event(session, first, later, "confidence_changed", before="low", after="medium")
    session.commit()
    changes = briefing.get_situation_changes(session, CONFIG, "corridor", START,
                                             START + timedelta(hours=1))
    counts = changes["counts"]
    assert (counts["new"], counts["grew"], counts["conflict_started"], counts["confidence_up"]) \
        == (1, 1, 1, 1)
    assert changes["window_starts_before_tracking"] is False
    assert (changes["demo_area_active_then"], changes["demo_area_active_now"]) == (1, 2)


def test_incidents_outside_the_chosen_area_are_left_out(session) -> None:
    _run(session, START, 1)
    incident = _incident(session, START)
    _event(session, incident, START + timedelta(minutes=10), "receding")
    session.commit()
    # 1011 is Lat Krabang: the Bang Sue incident is not part of it.
    changes = briefing.get_situation_changes(session, CONFIG, "1011", START,
                                             START + timedelta(hours=1))
    assert changes["counts"]["receded"] == 0
    assert briefing.get_situation_changes(session, CONFIG, "1029", START,
                                          START + timedelta(hours=1))["counts"]["receded"] == 1


def test_an_unknown_area_is_refused(session) -> None:
    with pytest.raises(LookupError):
        briefing.area_outlines(CONFIG, "9999")


def test_facts_are_labelled_capped_and_never_carry_notes_or_hazard_scenarios(session) -> None:
    _run(session, START, 20)
    incidents = [_incident(session, START, keys=(f"{n:016x}",)) for n in range(20)]
    session.add(FloodReview(pilot_id="bangkok", hub_id=incidents[0].id, user_id=incidents[0].id,
                            target_kind="incident", target_id=str(incidents[0].id),
                            action="dry_seen", note="SECRET NOTE call 081-234-5678",
                            road_keys=incidents[0].road_keys, created_at=START,
                            expires_at=START + timedelta(hours=3)))
    session.commit()
    names = {f"{n:016x}": f"Road {n}" for n in range(20)}
    names["0" * 16] = "<script>alert(1)</script>" + "x" * 100
    bundle = briefing.build_facts(session, CONFIG, "corridor", START,
                                  START + timedelta(minutes=10), names)
    ids = [f["id"] for f in bundle["facts"]]
    assert ids[:2] == ["S", "C"] and ids[-1] == "L"
    assert sum(1 for i in ids if i.startswith("I")) == briefing.MAX_INCIDENTS
    limits = bundle["facts"][-1]
    assert limits["incidents_not_listed"] == 5
    text = json.dumps(bundle["facts"], ensure_ascii=False)
    assert "SECRET" not in text and "081" not in text
    for banned in ("HAND", "RP100", "return period"):
        assert banned not in text
    assert all(len(name) <= briefing.NAME_MAX for f in bundle["facts"] if f["kind"] == "incident"
               for name in f["roads"])
    # Labels are opaque; the UUID mapping goes to the page, never into the facts.
    assert str(incidents[0].id) not in text
    assert bundle["labels"]["I1"]["kind"] == "incident"
