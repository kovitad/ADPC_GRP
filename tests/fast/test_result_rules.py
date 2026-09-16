from core.result_rules import ResultCounts, validate_result_counts


def test_status_counts_must_sum_to_in_scope() -> None:
    counts = ResultCounts(
        in_scope=3,
        potentially_exposed=1,
        not_exposed_under_scenario=1,
        unable_to_assess=0,
    )

    assert validate_result_counts(counts) == ["status_counts_must_equal_in_scope"]


def test_valid_status_counts_pass() -> None:
    counts = ResultCounts(
        in_scope=3,
        potentially_exposed=1,
        not_exposed_under_scenario=1,
        unable_to_assess=1,
    )

    assert validate_result_counts(counts) == []
