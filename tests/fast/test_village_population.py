"""Village population columns and the encoding recovery that made them readable.

The source columns are undocumented; docs/vulnerable-people-data-proof.md holds the evidence and
ADR-0027 records that they stay labelled as registered village population, never as vulnerability.
"""

from pathlib import Path

from core.dataset_scan import _encoding_candidates, _recover_declared_text
from core.thailand_full_import import (
    MAX_PLAUSIBLE_VILLAGE_POPULATION,
    POINT_PROFILES,
    _village_population,
)

PROFILE = POINT_PROFILES["village_locations"]


def _columns(male, female, total, households) -> dict[str, list]:
    return {
        "oct_side_9": [male],
        "oct_side10": [female],
        "oct_side11": [total],
        "oct_side12": [households],
    }


def test_a_consistent_village_row_is_counted() -> None:
    counts = _village_population(_columns(456, 394, 850, 125), PROFILE, 0)

    assert counts == {"male": 456, "female": 394, "total_population": 850, "households": 125}


def test_a_row_whose_parts_do_not_sum_to_the_total_is_excluded() -> None:
    assert _village_population(_columns(456, 394, 999, 125), PROFILE, 0) is None


def test_an_implausibly_large_village_is_excluded_not_counted() -> None:
    big = MAX_PLAUSIBLE_VILLAGE_POPULATION + 1

    assert _village_population(_columns(big, 0, big, 10), PROFILE, 0) is None


def test_an_empty_village_is_excluded_rather_than_counted_as_zero() -> None:
    assert _village_population(_columns(0, 0, 0, 0), PROFILE, 0) is None


def test_missing_and_unreadable_values_are_excluded() -> None:
    assert _village_population(_columns(None, 394, 850, 125), PROFILE, 0) is None
    assert _village_population(_columns("x", 394, 850, 125), PROFILE, 0) is None
    assert _village_population(_columns(float("nan"), 394, 850, 125), PROFILE, 0) is None


def test_a_profile_without_population_fields_reports_nothing() -> None:
    assert _village_population(_columns(1, 1, 2, 1), {"safe_fields": ()}, 0) is None


def test_a_declared_encoding_is_recovered_before_another_one_is_guessed(tmp_path: Path) -> None:
    (tmp_path / "area.cpg").write_text("UTF-8", encoding="ascii")
    (tmp_path / "area.shp").write_bytes(b"")

    candidates = _encoding_candidates(tmp_path / "area.shp")

    assert candidates[0] == ("UTF-8", "cpg")
    # Recovery comes before any guess, so a file with a few truncated values is not silently
    # decoded with a different encoding that mangles every row.
    assert candidates[1] == ("UTF-8", "cpg-recovered")
    assert [source for _, source in candidates[2:]] == ["assumed", "assumed"]


def test_recovery_re_decodes_byte_preserved_text_and_counts_what_it_cannot() -> None:
    thai = "เมืองสมุทรปราการ"
    # What a byte-preserving read returns: the file's UTF-8 bytes, one code point each.
    preserved = thai.encode("utf-8").decode("ISO-8859-1")
    truncated = thai.encode("utf-8")[:-1].decode("ISO-8859-1")

    class Column(list):
        dtype = object

    result = (None, None, None, [Column([preserved, truncated])])
    replaced = _recover_declared_text(result, "UTF-8")

    assert result[3][0][0] == thai
    assert replaced == 1
    assert "�" in result[3][0][1]
