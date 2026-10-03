"""How old a piece of evidence is, in the bands of spec section 11.

Expired evidence never sets a current state: callers check ``counts_as_current`` before using
a value for "what is happening now".
"""

from __future__ import annotations

from datetime import datetime

EXPIRED = "expired"
FUTURE = "future"
LIVE_BANDS = frozenset({"current", "recent", "aging", "stale"})
CURRENT_BANDS = frozenset({"current", "recent", "aging"})


def freshness(observed_at: datetime, as_of: datetime, bands: dict[str, int]) -> str:
    """Return current, recent, aging, stale or expired. Evidence from after ``as_of`` is future.

    A small clock difference (up to 5 minutes) between the provider and GRP still counts as
    current rather than future.
    """

    minutes = (as_of - observed_at).total_seconds() / 60
    if minutes < -5:
        return FUTURE
    for name in ("current", "recent", "aging", "stale"):
        if minutes <= bands[name]:
            return name
    return EXPIRED


def counts_as_current(band: str) -> bool:
    """Only current, recent and aging evidence may describe the situation now."""

    return band in CURRENT_BANDS
