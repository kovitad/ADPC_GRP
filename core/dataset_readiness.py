"""Legal dataset-version readiness transitions (ADR-0008)."""

from __future__ import annotations

from enum import StrEnum


class DatasetReadiness(StrEnum):
    RECEIVED = "received"
    VALIDATING = "validating"
    NEEDS_CORRECTION = "needs_correction"
    TECHNICALLY_VALID = "technically_valid"
    WAITING_FOR_METHOD = "waiting_for_method"
    READY_FOR_ACCEPTANCE = "ready_for_acceptance"
    ASSESSMENT_READY = "assessment_ready"
    RETIRED = "retired"


_ALLOWED: dict[DatasetReadiness, frozenset[DatasetReadiness]] = {
    DatasetReadiness.RECEIVED: frozenset({DatasetReadiness.VALIDATING, DatasetReadiness.RETIRED}),
    DatasetReadiness.VALIDATING: frozenset(
        {
            DatasetReadiness.NEEDS_CORRECTION,
            DatasetReadiness.TECHNICALLY_VALID,
            DatasetReadiness.WAITING_FOR_METHOD,
            DatasetReadiness.READY_FOR_ACCEPTANCE,
            DatasetReadiness.RETIRED,
        }
    ),
    DatasetReadiness.NEEDS_CORRECTION: frozenset(
        {DatasetReadiness.VALIDATING, DatasetReadiness.RETIRED}
    ),
    DatasetReadiness.TECHNICALLY_VALID: frozenset(
        {
            DatasetReadiness.WAITING_FOR_METHOD,
            DatasetReadiness.READY_FOR_ACCEPTANCE,
            DatasetReadiness.RETIRED,
        }
    ),
    DatasetReadiness.WAITING_FOR_METHOD: frozenset(
        {
            DatasetReadiness.READY_FOR_ACCEPTANCE,
            DatasetReadiness.ASSESSMENT_READY,
            DatasetReadiness.RETIRED,
        }
    ),
    DatasetReadiness.READY_FOR_ACCEPTANCE: frozenset(
        {DatasetReadiness.ASSESSMENT_READY, DatasetReadiness.RETIRED}
    ),
    DatasetReadiness.ASSESSMENT_READY: frozenset({DatasetReadiness.RETIRED}),
    DatasetReadiness.RETIRED: frozenset(),
}


def require_readiness_transition(current: str, target: str) -> DatasetReadiness:
    """Return the target state or fail closed on an unknown/illegal transition."""

    try:
        current_state = DatasetReadiness(current)
        target_state = DatasetReadiness(target)
    except ValueError as exc:
        raise ValueError("Unknown dataset readiness state") from exc
    if target_state not in _ALLOWED[current_state]:
        raise ValueError(f"Illegal dataset readiness transition: {current_state} -> {target_state}")
    return target_state
