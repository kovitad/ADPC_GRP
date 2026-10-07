"""Longdo Traffic event feed: flood reports from the Department of Highways and iTIC (ADR-0048).

``https://event.longdo.com/feed/json`` is public and needs no key. Measured on 3 October 2026:
219 events, 197 of them floods (``icon`` "flood", ``type`` "6"), 159 by "DOH Admin". Rules:

- only flood events are kept, and only while ``stop`` is in the future;
- ``start``/``stop`` carry no zone and are Bangkok time (+07:00);
- the feed is national: points outside the pilot region are skipped, not a reason to refuse it;
  a change in the feed's shape still refuses the whole file;
- "(ผ่านไม่ได้)" (not passable) means closed to traffic; "(ผ่านได้)" (passable) means flooded but
  passable. Neither ever means dry or cleared;
- freshness is measured from ``start``: an event that stays listed is not re-confirmed;
- the contributor becomes a source family (``doh``, ``itic``, ``longdo_user``); raw contributor
  names, which can be usernames, are never stored, and description text is kept only as a hash.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from core.flood_evidence.floodboard import BANGKOK_REGION
from core.flood_evidence.observation import (
    OBSERVED,
    REPORT,
    ObservationDraft,
    SourceFormatError,
    sha256_text,
)

BANGKOK_TIME = timezone(timedelta(hours=7))
EVENT_KEYS = frozenset({"eid", "title", "title_en", "start", "stop", "latitude", "longitude",
                        "contributor", "icon"})
NOT_PASSABLE = "ผ่านไม่ได้"
PASSABLE = "ผ่านได้"


def contributor_family(contributor: str) -> str:
    name = (contributor or "").strip().lower()
    if name == "doh admin":
        return "doh"
    if name.startswith("itic"):
        return "itic"
    return "longdo_user"


def _bangkok(value: Any, field: str) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError as error:
        raise SourceFormatError(f"{field} is not a time") from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=BANGKOK_TIME)
    return moment.astimezone(UTC)


def parse_events(body: bytes, retrieved_at: datetime | None = None) -> list[ObservationDraft]:
    try:
        items = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceFormatError("The event feed is not JSON") from error
    if not isinstance(items, list):
        raise SourceFormatError("The event feed is not a list")
    now = retrieved_at or datetime.now(UTC)
    west, south, east, north = BANGKOK_REGION
    drafts: dict[str, ObservationDraft] = {}
    for item in items:
        if not isinstance(item, dict) or not EVENT_KEYS <= item.keys():
            raise SourceFormatError("An event is missing expected fields")
        if item.get("icon") != "flood":
            continue
        start, stop = _bangkok(item["start"], "start"), _bangkok(item["stop"], "stop")
        if stop <= now or start > now + timedelta(minutes=5):
            continue
        try:
            lat, lon = float(item["latitude"]), float(item["longitude"])
        except (TypeError, ValueError):
            continue
        if not (west <= lon <= east and south <= lat <= north):
            continue
        title = f"{item.get('title') or ''} {item.get('title_en') or ''}"
        closed = NOT_PASSABLE in title
        external_id = f"longdo:{item['eid']}"
        description = str(item.get("description") or "")
        drafts[external_id] = ObservationDraft(
            kind=REPORT,
            external_id=external_id,
            observed_at=start,
            reported_at=start,
            geometry={"type": "Point", "coordinates": [lon, lat]},
            state={
                "tier": "official" if contributor_family(item["contributor"]) == "doh" else "crowd",
                "closed_all": closed,
                "closed_small": closed,
                # "Passable" is still flooding; nothing in this feed says a road is dry.
                "cleared": False,
                "passable_stated": (PASSABLE in title) and not closed,
                "expires_at": stop.isoformat(),
            },
            underlying_sources=(contributor_family(item["contributor"]),),
            evidence_class=OBSERVED,
            provider_judgement={"severity": item.get("severity") or None},
            depth_cm=None,
            text_sha256=sha256_text(description) if description else None,
        )
    return list(drafts.values())
