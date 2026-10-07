"""Longdo Weather rain context (ADR-0049): live only, key never stored, unknown is not dry."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import core.flood_evidence.weather as weather_module
from core.db import Base
from core.flood_evidence.answer import instructions_for
from core.flood_evidence.config import pilot_config
from core.flood_evidence.models import FloodWeather
from core.flood_evidence.weather import (
    LongdoWeather,
    WeatherUnavailable,
    latest_weather,
    run_weather,
)

CONFIG = pilot_config("bangkok")
KEY = "k" * 32
NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
STATS = {"stats": {"rain_coverage_pct": 12.5, "max_intensity": 4, "avg_intensity": 0.3,
                   "dominant_level": {"level": "light", "description": "x", "intensity": 2}}}
FORECAST = {"forecast": [
    {"forecast_time": "2026-10-03T09:15:00Z", "available": True, **STATS},
    {"forecast_time": "2026-10-03T09:30:00Z", "available": False},
]}


@pytest.fixture
def session(monkeypatch) -> Iterator[Session]:
    # No incidents: the scopes are the four demo districts.
    monkeypatch.setattr(weather_module, "list_incidents", lambda *a: {"incidents": []})
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _client(base=1791017100, now_fails=False, calls=None):
    calls = calls if calls is not None else []

    def get(path, params):
        calls.append(path)
        if path.endswith("layer/list"):
            return {"radar": {"observation_base_time": base}}
        if path.endswith("forecast/area"):
            return FORECAST
        if now_fails:
            # A provider error that echoes the request, key and all.
            raise WeatherUnavailable(f"HTTP 503 for ...?key={KEY}")
        return STATS

    def post(path, body):
        raise AssertionError("no POST calls are made")

    return LongdoWeather(key=KEY, get=get, post=post), calls


def test_rain_is_recorded_once_per_radar_observation(session) -> None:
    client, calls = _client()
    assert run_weather(session, CONFIG, client, NOW) == 4
    session.commit()
    assert run_weather(session, CONFIG, client, NOW) is None  # same radar image: no new calls
    assert calls.count("/rain/api/v1/area") == 4
    rows = session.scalars(select(FloodWeather)).all()
    assert {r.rain_now["max_level"] for r in rows} == {"heavy"}
    assert rows[0].forecast[1] == {"time": "2026-10-03T09:30:00Z", "available": False}


def test_an_unavailable_reading_is_unknown_and_the_key_is_never_stored(session, caplog) -> None:
    client, _ = _client(now_fails=True)
    with caplog.at_level(logging.INFO):
        run_weather(session, CONFIG, client, NOW)
    session.commit()
    rows = session.scalars(select(FloodWeather)).all()
    assert all(r.rain_now is None and r.forecast for r in rows)  # unknown now, forecast kept
    stored = json.dumps([[r.error, r.rain_now, r.forecast] for r in rows])
    assert KEY not in stored and "<key>" in stored
    assert KEY not in caplog.text
    view = latest_weather(session, CONFIG)
    assert all(s["rain_now"] is None for s in view["scopes"])


def test_the_httpx_logger_never_prints_request_urls() -> None:
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_replays_never_call_longdo(session) -> None:
    replay = dataclasses.replace(CONFIG, pilot_id="r0123456789a", base_id="bangkok")
    client, calls = _client()
    with pytest.raises(ValueError):
        run_weather(session, replay, client, NOW)
    assert calls == []
    assert latest_weather(session, replay) == {"available": False, "reason": "replay",
                                               "scopes": []}


def test_the_ai_is_told_rain_is_not_flooding() -> None:
    assert "rain is not flooding" in instructions_for("en")
