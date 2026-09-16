from dataclasses import dataclass


@dataclass(frozen=True)
class ResultCounts:
    in_scope: int
    potentially_exposed: int
    not_exposed_under_scenario: int
    unable_to_assess: int


def validate_result_counts(counts: ResultCounts) -> list[str]:
    """Return invariant violations; an empty list means the summary is internally valid."""

    values = (
        counts.in_scope,
        counts.potentially_exposed,
        counts.not_exposed_under_scenario,
        counts.unable_to_assess,
    )
    errors: list[str] = []
    if any(value < 0 for value in values):
        errors.append("counts_must_be_non_negative")

    classified = (
        counts.potentially_exposed
        + counts.not_exposed_under_scenario
        + counts.unable_to_assess
    )
    if classified != counts.in_scope:
        errors.append("status_counts_must_equal_in_scope")
    return errors
