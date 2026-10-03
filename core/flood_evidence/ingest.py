"""Fetch flood sources on schedule, keep the raw bytes, and store distinct observed states.

Runs in the worker, never in a web request (AGENTS.md). Every attempt writes a fetch row, so a
failed pull is visible as source health and the last good data keeps its true age. A file that
fails its format check stores nothing from that file (fail closed).

``ingest_body`` is the single entry point for bytes, whether they came from a live pull or from
a saved capture folder, so a captured event and a live one are read by the same code.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.flood_evidence.config import PilotConfig, SourceConfig
from core.flood_evidence.floodboard import PARSERS
from core.flood_evidence.models import (
    FETCH_FORMAT_ERROR,
    FETCH_HTTP_ERROR,
    FETCH_NETWORK_ERROR,
    FETCH_OK,
    FETCH_TOO_LARGE,
    FloodObservation,
    FloodSourceFetch,
)
from core.flood_evidence.observation import (
    ObservationDraft,
    SourceFormatError,
    record_key,
    state_hash,
)
from core.storage import LocalStorage

logger = logging.getLogger("grp.flood_evidence")
RULE_VERSION = "FloodboardAdapter v0.1"
FETCH_TIMEOUT_SECONDS = 20.0
USER_AGENT = "GRP-flood-pilot/0.1 (ADPC SERVIR pilot)"
IN_CHUNK = 500


def utc(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; every stored time is UTC."""

    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Pulled:
    http_status: int | None
    body: bytes | None
    outcome: str
    error: str | None = None


Fetcher = Callable[[SourceConfig], Pulled]


def http_fetch(source: SourceConfig) -> Pulled:
    """One bounded GET. Never raises: every failure becomes an outcome."""

    try:
        with httpx.Client(
            timeout=FETCH_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client, client.stream("GET", source.url) as response:
            if response.status_code != 200:
                return Pulled(response.status_code, None, FETCH_HTTP_ERROR, "Not HTTP 200")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > source.max_bytes:
                    return Pulled(response.status_code, None, FETCH_TOO_LARGE, "Over the byte cap")
                chunks.append(chunk)
            return Pulled(response.status_code, b"".join(chunks), FETCH_OK)
    except httpx.HTTPError as error:
        return Pulled(None, None, FETCH_NETWORK_ERROR, type(error).__name__)


def _store_raw(
    storage: LocalStorage, pilot_id: str, source_id: str, retrieved_at: datetime, body: bytes
) -> str:
    stamp = retrieved_at.strftime("%Y%m%dt%H%M%Sz")
    key = (
        f"flood/{pilot_id}/{source_id}/{retrieved_at:%Y/%m/%d}/{stamp}-"
        f"{sha256_text_bytes(body)[:12]}.gz"
    )
    with tempfile.TemporaryDirectory() as folder:
        packed = Path(folder) / "raw.gz"
        packed.write_bytes(gzip.compress(body, mtime=0))
        storage.put(key, packed)
    return key


def sha256_text_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _existing(
    session: Session, pilot_id: str, source_id: str, keys: Iterable[str]
) -> dict[tuple[str, str], FloodObservation]:
    found: dict[tuple[str, str], FloodObservation] = {}
    ordered = sorted(set(keys))
    for start in range(0, len(ordered), IN_CHUNK):
        rows = session.scalars(
            select(FloodObservation).where(
                FloodObservation.pilot_id == pilot_id,
                FloodObservation.source_id == source_id,
                FloodObservation.record_key.in_(ordered[start : start + IN_CHUNK]),
            )
        )
        for row in rows:
            found[(row.record_key, row.state_hash)] = row
    return found


def _apply(
    session: Session,
    fetch: FloodSourceFetch,
    drafts: list[ObservationDraft],
) -> int:
    keyed = [(record_key(d.external_id), state_hash(d), d) for d in drafts]
    existing = _existing(session, fetch.pilot_id, fetch.source_id, (k for k, _, _ in keyed))
    new_states = 0
    for key, digest, draft in keyed:
        row = existing.get((key, digest))
        if row is not None:
            row.reported_at = max(utc(row.reported_at), draft.reported_at)
            # A capture loaded after a newer live pull must not move "last seen" backwards.
            if fetch.retrieved_at >= utc(row.last_seen_at):
                row.last_seen_at = fetch.retrieved_at
                row.last_fetch_id = fetch.id
                row.provider_judgement = draft.provider_judgement
            continue
        new_states += 1
        session.add(
            FloodObservation(
                pilot_id=fetch.pilot_id,
                source_id=fetch.source_id,
                kind=draft.kind,
                record_key=key,
                external_id=draft.external_id,
                state_hash=digest,
                observed_at=draft.observed_at,
                reported_at=draft.reported_at,
                first_seen_at=fetch.retrieved_at,
                last_seen_at=fetch.retrieved_at,
                first_fetch_id=fetch.id,
                last_fetch_id=fetch.id,
                geometry=draft.geometry,
                depth_cm=draft.depth_cm,
                state=draft.state,
                underlying_sources=list(draft.underlying_sources),
                evidence_class=draft.evidence_class,
                provider_judgement=draft.provider_judgement,
                text_sha256=draft.text_sha256,
                rule_version=RULE_VERSION,
            )
        )
    return new_states


def ingest_body(
    session: Session,
    storage: LocalStorage,
    config: PilotConfig,
    source: SourceConfig,
    pulled: Pulled,
    retrieved_at: datetime,
) -> FloodSourceFetch:
    """Record one attempt and, when its bytes parse, every observed state in it."""

    fetch = FloodSourceFetch(
        pilot_id=config.pilot_id,
        source_id=source.source_id,
        url=source.url,
        retrieved_at=retrieved_at,
        outcome=pulled.outcome,
        http_status=pulled.http_status,
        error=pulled.error,
    )
    session.add(fetch)
    if pulled.outcome != FETCH_OK or pulled.body is None:
        session.flush()
        return fetch
    fetch.byte_count = len(pulled.body)
    fetch.sha256 = sha256_text_bytes(pulled.body)
    fetch.storage_key = _store_raw(
        storage, config.pilot_id, source.source_id, retrieved_at, pulled.body
    )
    try:
        drafts = PARSERS[source.adapter](pulled.body)
    except SourceFormatError as error:
        fetch.outcome = FETCH_FORMAT_ERROR
        fetch.error = str(error)[:500]
        session.flush()
        return fetch
    session.flush()
    fetch.record_count = len(drafts)
    fetch.new_states = _apply(session, fetch, drafts)
    session.flush()
    if source.adapter == "floodboard_roads":
        # Imported here: exposure reads the snapshot through the situation module.
        from core.flood_evidence.exposure import store_exposure
        from core.flood_evidence.incident_store import update_incidents

        store_exposure(session, config, fetch)
        update_incidents(session, config, fetch)
    return fetch


def last_attempt(session: Session, pilot_id: str, source_id: str) -> FloodSourceFetch | None:
    return session.scalars(
        select(FloodSourceFetch)
        .where(FloodSourceFetch.pilot_id == pilot_id, FloodSourceFetch.source_id == source_id)
        .order_by(FloodSourceFetch.retrieved_at.desc())
        .limit(1)
    ).first()


def due_sources(session: Session, config: PilotConfig, now: datetime) -> list[SourceConfig]:
    due = []
    for source in config.sources:
        attempt = last_attempt(session, config.pilot_id, source.source_id)
        if attempt is None or now - utc(attempt.retrieved_at) >= timedelta(
            minutes=source.interval_minutes
        ):
            due.append(source)
    return due


def pull_due(
    session: Session,
    storage: LocalStorage,
    config: PilotConfig,
    now: datetime | None = None,
    fetcher: Fetcher = http_fetch,
) -> list[FloodSourceFetch]:
    """Pull every source whose interval has passed, committing after each one."""

    fetches = []
    for source in due_sources(session, config, now or datetime.now(UTC)):
        retrieved_at = datetime.now(UTC) if now is None else now
        fetch = ingest_body(session, storage, config, source, fetcher(source), retrieved_at)
        session.commit()
        logger.info(
            "Flood source %s/%s: %s, %s records, %s new states",
            config.pilot_id,
            source.source_id,
            fetch.outcome,
            fetch.record_count,
            fetch.new_states,
        )
        fetches.append(fetch)
    return fetches


__all__ = [
    "Pulled",
    "due_sources",
    "http_fetch",
    "ingest_body",
    "pull_due",
    "utc",
]
