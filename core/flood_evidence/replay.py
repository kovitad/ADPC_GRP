"""Replay a stored period through the same engines, in its own namespace (ADR-0044, slice 6a).

A replay copies nothing from live tables. It walks the live pilot's stored fetches (successes
and failures) in time order and feeds each through ``ingest_body`` under a replay ``pilot_id``,
pointing at the original raw bytes. The same exposure and incident code runs after each roads
snapshot, with the snapshot time as "now". The replay clock is the time processed so far:

- reads in a replay are clamped to that clock (a road row only knows its newest snapshot, so
  any later time would be wrong);
- the clock only moves forward; going back means ``restart``, which wipes the namespace;
- the worker processes one stored fetch per idle pass, so a replay never stalls live work.

A replay uses today's facility list, camera list and rules, not the ones that were in force at
the time; the page and the facts say so.
"""

from __future__ import annotations

import dataclasses
import gzip
import re
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.flood_evidence.config import PilotConfig, pilot_config
from core.flood_evidence.ingest import Pulled, ingest_body, utc
from core.flood_evidence.models import (
    FETCH_OK,
    FloodAssetExposure,
    FloodIncident,
    FloodIncidentEvent,
    FloodIncidentRun,
    FloodObservation,
    FloodReplay,
    FloodReview,
    FloodSourceFetch,
)
from core.storage import LocalStorage

REPLAY_ID = re.compile(r"^r[0-9a-f]{11}$")
MAX_OPEN = 3
MAX_WINDOW = timedelta(hours=12)
KEEP_FOR = timedelta(hours=24)
BUILDING = "building"
READY = "ready"
FAILED = "failed"


class ReplayRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def is_replay_id(value: str) -> bool:
    return bool(REPLAY_ID.fullmatch(value))


def replay_config(replay: FloodReplay) -> PilotConfig | None:
    """The live pilot's config, moved into the replay namespace and clock. Never cached."""

    base = pilot_config(replay.base_pilot_id)
    if base is None:
        return None
    clock = utc(replay.processed_at) if replay.processed_at else utc(replay.start_at)
    return dataclasses.replace(base, pilot_id=replay.replay_pilot_id, base_id=base.pilot_id,
                               clock=clock)


def find_replay(session: Session, replay_pilot_id: str) -> FloodReplay | None:
    if not is_replay_id(replay_pilot_id):
        return None
    return session.scalar(
        select(FloodReplay).where(FloodReplay.replay_pilot_id == replay_pilot_id)
    )


def _base_fetches(
    session: Session, base: PilotConfig, after: datetime | None, until: datetime
) -> list[FloodSourceFetch]:
    query = select(FloodSourceFetch).where(
        FloodSourceFetch.pilot_id == base.pilot_id, FloodSourceFetch.retrieved_at <= until
    )
    if after is not None:
        query = query.where(FloodSourceFetch.retrieved_at > after)
    return list(session.scalars(query.order_by(FloodSourceFetch.retrieved_at,
                                               FloodSourceFetch.source_id)))


def available_range(session: Session, base: PilotConfig) -> dict[str, Any]:
    roads = next(s for s in base.sources if s.adapter == "floodboard_roads")
    first, last = session.execute(
        select(func.min(FloodSourceFetch.retrieved_at), func.max(FloodSourceFetch.retrieved_at))
        .where(FloodSourceFetch.pilot_id == base.pilot_id,
               FloodSourceFetch.source_id == roads.source_id,
               FloodSourceFetch.outcome == FETCH_OK)
    ).one()
    return {"first": utc(first).isoformat() if first else None,
            "last": utc(last).isoformat() if last else None}


def create_replay(
    session: Session, base: PilotConfig, *, start_at: datetime, end_at: datetime,
    user_id: UUID, hub_id: UUID, now: datetime,
) -> FloodReplay:
    if base.is_replay:
        raise ReplayRejected("nested_replay", "A replay cannot be replayed")
    if not start_at < end_at <= now:
        raise ReplayRejected("bad_window", "The period must end after it starts, in the past")
    if end_at - start_at > MAX_WINDOW:
        raise ReplayRejected("window_too_long", "A replay can cover at most 12 hours")
    open_count = session.scalar(
        select(func.count()).select_from(FloodReplay)
        .where(FloodReplay.base_pilot_id == base.pilot_id, FloodReplay.expires_at > now)
    )
    if open_count >= MAX_OPEN:
        raise ReplayRejected("too_many", "Delete an older replay first")
    fetches = _base_fetches(session, base, start_at - timedelta(microseconds=1), end_at)
    if not any(f.outcome == FETCH_OK and f.source_id.endswith("roads") for f in fetches):
        raise ReplayRejected("no_data", "No stored road data in that period")
    replay = FloodReplay(
        replay_pilot_id="r" + secrets.token_hex(6)[:11], base_pilot_id=base.pilot_id,
        hub_id=hub_id, created_by=user_id, start_at=start_at, end_at=end_at,
        target_at=start_at, processed_at=None, steps_total=len(fetches), steps_done=0,
        status=BUILDING, injections=[], created_at=now, expires_at=now + KEEP_FOR,
    )
    session.add(replay)
    session.flush()
    return replay


def advance(replay: FloodReplay, to: datetime) -> None:
    """Move the requested time forward. Going back needs ``restart``."""

    current = utc(replay.processed_at) if replay.processed_at else utc(replay.start_at)
    if to < current:
        raise ReplayRejected("backwards", "A replay only moves forward; restart it instead")
    replay.target_at = min(to, utc(replay.end_at))
    if replay.status == READY and replay.target_at > current:
        replay.status = BUILDING


def wipe(session: Session, replay_pilot_id: str) -> None:
    """Delete every row of a replay namespace, children first."""

    if not is_replay_id(replay_pilot_id):
        raise ValueError("Only a replay namespace can be wiped")
    for model in (FloodReview, FloodIncidentEvent, FloodIncidentRun, FloodAssetExposure):
        session.execute(delete(model).where(model.pilot_id == replay_pilot_id))
    session.execute(delete(FloodIncident).where(FloodIncident.pilot_id == replay_pilot_id))
    session.execute(delete(FloodObservation).where(FloodObservation.pilot_id == replay_pilot_id))
    session.execute(delete(FloodSourceFetch).where(FloodSourceFetch.pilot_id == replay_pilot_id))
    session.flush()


def restart(session: Session, replay: FloodReplay) -> None:
    wipe(session, replay.replay_pilot_id)
    replay.processed_at = None
    replay.target_at = utc(replay.start_at)
    replay.steps_done = 0
    replay.status = BUILDING
    replay.error = None


def _pulled_from(storage: LocalStorage, fetch: FloodSourceFetch) -> Pulled:
    if fetch.outcome != FETCH_OK or not fetch.storage_key:
        return Pulled(fetch.http_status, None, fetch.outcome, fetch.error)
    body = gzip.decompress(storage.read_bytes(fetch.storage_key))
    return Pulled(fetch.http_status, body, FETCH_OK)


def step(session: Session, storage: LocalStorage, replay: FloodReplay) -> bool:
    """Process the next stored fetch up to the requested time. Returns True if one was done."""

    base = pilot_config(replay.base_pilot_id)
    config = replay_config(replay)
    if base is None or config is None:
        replay.status, replay.error = FAILED, "Unknown base pilot"
        return False
    target = min(utc(replay.target_at), utc(replay.end_at))
    after = utc(replay.processed_at) if replay.processed_at else (
        utc(replay.start_at) - timedelta(microseconds=1))
    upcoming = _base_fetches(session, base, after, target)
    if not upcoming:
        replay.status = READY
        if replay.processed_at is None:
            replay.processed_at = utc(replay.start_at)
        return False
    fetch = upcoming[0]
    source = config.source(fetch.source_id)
    if source is not None:
        at = utc(fetch.retrieved_at)
        ingest_body(session, storage, config, source, _pulled_from(storage, fetch), at,
                    stored_key=fetch.storage_key)
    replay.processed_at = utc(fetch.retrieved_at)
    replay.steps_done += 1
    if len(upcoming) == 1:
        replay.status = READY
    return True


def run_one_step(session: Session, storage: LocalStorage, now: datetime) -> bool:
    """Worker entry: expire old replays, then advance the oldest building one by one fetch."""

    for old in session.scalars(select(FloodReplay).where(FloodReplay.expires_at <= now)):
        wipe(session, old.replay_pilot_id)
        session.delete(old)
    session.commit()
    replay = session.scalars(
        select(FloodReplay).where(FloodReplay.status == BUILDING)
        .order_by(FloodReplay.created_at).limit(1)
    ).first()
    if replay is None:
        return False
    try:
        worked = step(session, storage, replay)
        session.commit()
        return worked
    except Exception as error:  # a broken replay must never stop the worker
        session.rollback()
        replay = session.get(FloodReplay, replay.id)
        replay.status, replay.error = FAILED, type(error).__name__
        session.commit()
        return False


def public(replay: FloodReplay) -> dict[str, Any]:
    return {
        "replay_id": replay.replay_pilot_id,
        "base_pilot_id": replay.base_pilot_id,
        "status": replay.status,
        "start_at": utc(replay.start_at).isoformat(),
        "end_at": utc(replay.end_at).isoformat(),
        "target_at": utc(replay.target_at).isoformat(),
        "clock": utc(replay.processed_at).isoformat() if replay.processed_at else None,
        "steps_done": replay.steps_done,
        "steps_total": replay.steps_total,
        "injections": replay.injections,
        "error": replay.error,
        "expires_at": utc(replay.expires_at).isoformat(),
        "uses_current_registries": True,
    }
