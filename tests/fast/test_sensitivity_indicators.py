"""ADR-0030: sensitivity indicators are shown where planners look, never turned into counts."""

from api.maps import WITHHELD_INDICATORS, _planner_status


def test_the_disability_indicator_is_withheld_from_planners_with_its_reason() -> None:
    status = _planner_status("disability_support")

    assert status["planner_status"] == "withheld"
    assert "data owner" in status["withheld_reason"]


def test_child_and_older_person_sensitivity_are_shown() -> None:
    for key in ("child_sensitivity", "elderly_sensitivity"):
        assert _planner_status(key) == {"planner_status": "shown", "withheld_reason": None}
    assert set(WITHHELD_INDICATORS) == {"disability_support"}
