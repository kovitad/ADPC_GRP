"""GRP's own live feeds that a Hub can share with Global Risk (Share data, ADR-0052).

Each entry names a manifest in ``core/data/live_feeds/``, whose ``fetch.url`` holds a
``{public_base}`` placeholder. A feed can be shared only when this deployment has a permanent
public address (``GRP_PUBLIC_FEED_BASE_URL``) and serves the public feed route
(``FLOOD_FEED_PUBLIC``). Otherwise the page lists it with the reason it cannot be sent yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.contribution_rules import feed_url_problem

MANIFESTS = Path(__file__).resolve().parent / "data" / "live_feeds"


@dataclass(frozen=True)
class PlatformFeed:
    dataset: str
    label: str
    summary: str
    switch: str  # the setting that serves its public route
    note: str | None = None


FEEDS = (
    PlatformFeed(
        "bangkok_flood_districts_live",
        "Bangkok and Nonthaburi flood by district",
        "All 56 districts, most concerning last; never empty. Share this one first.",
        "flood_feed_public",
    ),
    PlatformFeed(
        "bangkok_flood_incidents_live",
        "Bangkok and Nonthaburi flood incidents",
        "One record per open incident. Global Risk refuses an empty list, so send it on a day "
        "with flooding.",
        "flood_feed_public",
        note="empty_on_dry_days",
    ),
)


@lru_cache
def _template(dataset: str) -> dict[str, Any]:
    return json.loads((MANIFESTS / f"{dataset}.json").read_text(encoding="utf-8"))


def platform_feeds(public_base: str | None, switches: dict[str, bool]) -> list[dict[str, Any]]:
    """Every shareable GRP feed, with its filled manifest or the reason it cannot be sent."""

    base = (public_base or "").rstrip("/")
    out = []
    for feed in FEEDS:
        manifest = json.loads(json.dumps(_template(feed.dataset)))
        reason = None
        if not base:
            reason = ("This GRP has no permanent public address yet (GRP_PUBLIC_FEED_BASE_URL). "
                      "Global Risk must be able to fetch the feed for as long as it is listed.")
        elif not switches.get(feed.switch):
            reason = "The public feed route is switched off on this GRP."
        if base:
            manifest["fetch"]["url"] = manifest["fetch"]["url"].replace("{public_base}", base)
            reason = reason or feed_url_problem(manifest["fetch"]["url"])
        else:
            manifest["fetch"]["url"] = None
        out.append({
            "dataset": feed.dataset, "label": feed.label, "summary": feed.summary,
            "note": feed.note, "available": reason is None, "reason": reason,
            "manifest": manifest,
        })
    return out
