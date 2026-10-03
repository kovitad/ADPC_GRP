"""The provider-neutral observation an adapter produces (spec FB-2), before it is stored."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ROAD_SEGMENT = "road_segment"
REPORT = "report"
# Evidence classes (tweak v0.1): always stored, always shown.
OBSERVED = "observed"
PROVIDER_DERIVED = "provider_derived"
FORECAST = "forecast"
STATIC_SCENARIO = "static_scenario"
SYNTHETIC_DEMO = "synthetic_demo"
EVIDENCE_CLASSES = (OBSERVED, PROVIDER_DERIVED, FORECAST, STATIC_SCENARIO, SYNTHETIC_DEMO)
VEHICLES = ("motorbike", "sedan", "pickup", "truck")
VERDICTS = ("ok", "caution", "risky", "blocked")


class SourceFormatError(ValueError):
    """The provider's file is not the shape GRP was built for. Nothing from it is stored."""


@dataclass(frozen=True)
class ObservationDraft:
    kind: str
    # Stable within the source: a geometry hash for a road, the provider's ID for a report.
    external_id: str
    observed_at: datetime
    # When the provider last said this state still holds; drives freshness.
    reported_at: datetime
    geometry: dict[str, Any]
    # Observed facts only. A change here is a new state; see state_hash().
    state: dict[str, Any]
    # The independent sources underneath (traffy, crowd, bma_sensor...), for corroboration.
    underlying_sources: tuple[str, ...]
    # observed, or provider_derived when the provider inferred it (a zone, an estimate).
    evidence_class: str
    # The provider's own time-decaying scores (Floodboard conf, current_weight). Never a state.
    provider_judgement: dict[str, Any] = field(default_factory=dict)
    depth_cm: float | None = None
    text_sha256: str | None = None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_key(external_id: str) -> str:
    """A fixed-length key for an external ID, which can be a long URL."""

    return sha256_text(external_id)


def state_hash(draft: ObservationDraft) -> str:
    """Fingerprint of what was observed. Provider scores and refresh times are left out, so a
    decaying confidence does not create a new observation, and a real change always does.

    A road's time is left out too: Floodboard moves ``updated`` on an unchanged segment, which
    refreshes the state rather than replacing it. A report's own time is part of what it says.
    """

    payload = {
        "observed_at": draft.observed_at.isoformat() if draft.kind == REPORT else None,
        "depth_cm": draft.depth_cm,
        "state": draft.state,
        "sources": sorted(draft.underlying_sources),
        "evidence_class": draft.evidence_class,
        "geometry": draft.geometry if draft.kind == REPORT else None,
        "text": draft.text_sha256,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))
