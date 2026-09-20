"""Dataset readiness is explicit and fails closed on illegal shortcuts."""

import pytest

from core.dataset_readiness import DatasetReadiness, require_readiness_transition


@pytest.mark.fast
@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("received", "validating"),
        ("validating", "needs_correction"),
        ("needs_correction", "validating"),
        ("technically_valid", "waiting_for_method"),
        ("ready_for_acceptance", "assessment_ready"),
        ("assessment_ready", "retired"),
    ],
)
def test_legal_readiness_transitions(current: str, target: str) -> None:
    assert require_readiness_transition(current, target) == DatasetReadiness(target)


@pytest.mark.fast
@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("received", "assessment_ready"),
        ("needs_correction", "assessment_ready"),
        ("retired", "assessment_ready"),
        ("assessment_ready", "validating"),
        ("unknown", "retired"),
    ],
)
def test_illegal_readiness_transitions_fail_closed(current: str, target: str) -> None:
    with pytest.raises(ValueError):
        require_readiness_transition(current, target)
