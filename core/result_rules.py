from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID


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


def count_results(in_scope: int, statuses: Iterable[str]) -> ResultCounts:
    tally = Counter(statuses)
    return ResultCounts(
        in_scope=in_scope,
        potentially_exposed=tally["potentially_exposed"],
        not_exposed_under_scenario=tally["not_exposed_under_scenario"],
        unable_to_assess=tally["unable_to_assess"],
    )


def validate_center_results(
    in_scope_ids: Iterable[UUID],
    results: Iterable[tuple[UUID, str, str, float | None]],
    reason_codes: Mapping[str, Mapping[str, object]],
) -> list[str]:
    """Section 8.4 rules checked before a result is saved.

    `results` holds (feature_id, status, reason_code, flood_depth_m) tuples.
    """

    expected = list(in_scope_ids)
    rows = list(results)
    errors: list[str] = []
    seen = Counter(row[0] for row in rows)
    if any(count > 1 for count in seen.values()):
        errors.append("center_listed_more_than_once")
    if set(seen) != set(expected):
        errors.append("every_in_scope_center_must_appear_once")
    for _feature_id, status, reason, depth in rows:
        rule = reason_codes.get(reason)
        if rule is None:
            errors.append("reason_code_not_approved")
            break
        if str(rule.get("status")) != status:
            errors.append("status_does_not_match_reason_code")
            break
        if reason == "NO_FLOOD_DATA" and depth is not None:
            errors.append("no_data_must_not_carry_a_depth")
            break
    errors.extend(validate_result_counts(count_results(len(expected), (r[1] for r in rows))))
    return sorted(set(errors))
