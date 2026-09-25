"""An answer's map references resolve by id, and only to ids GRP issued."""

from core.answer_references import (
    reference_map,
    resolve_references,
    token_for,
)


def test_tokens_are_issued_in_the_order_the_model_was_given() -> None:
    tokens = reference_map(["aaa", "bbb", "ccc"])

    assert tokens == {"C1": "aaa", "C2": "bbb", "C3": "ccc"}
    assert token_for(1) == "C1"


def test_markers_resolve_to_feature_ids_and_leave_clean_prose() -> None:
    tokens = reference_map(["aaa", "bbb"])

    resolved = resolve_references(
        "The centres are วัดใหม่ [[C2]] and "
        "รร.บ้าน [[C1]].",
        tokens,
    )

    # Order of first mention, so a map can move through them as the reader met them.
    assert resolved.feature_ids == ("bbb", "aaa")
    assert "[[" not in resolved.text
    assert resolved.text == (
        "The centres are วัดใหม่ and "
        "รร.บ้าน."
    )


def test_a_reference_grp_never_issued_is_dropped_and_counted() -> None:
    resolved = resolve_references("Somewhere [[C9]] and here [[C1]].", reference_map(["aaa"]))

    # The invented reference cannot put a pin on the map.
    assert resolved.feature_ids == ("aaa",)
    assert resolved.unknown_tokens == ("C9",)
    assert resolved.payload == {"centers": ["aaa"], "unresolved_references": 1}
    assert "C9" not in resolved.text


def test_the_same_centre_named_twice_is_one_reference() -> None:
    resolved = resolve_references("A [[C1]] then A again [[C1]].", reference_map(["aaa"]))

    assert resolved.feature_ids == ("aaa",)
    assert resolved.payload["unresolved_references"] == 0


def test_an_answer_with_no_markers_resolves_to_nothing_rather_than_guessing() -> None:
    # The old behaviour matched names as strings; naming a centre without its marker must now
    # simply produce no reference instead of a fuzzy guess.
    resolved = resolve_references("Seven centres could not be assessed.", reference_map(["aaa"]))

    assert resolved.feature_ids == ()
    assert resolved.text == "Seven centres could not be assessed."


def test_stripping_a_marker_does_not_leave_stray_spacing() -> None:
    resolved = resolve_references(
        "Centre one [[C1]], centre two [[C2]] .", reference_map(["a", "b"])
    )

    assert resolved.text == "Centre one, centre two."


def test_empty_and_missing_text_are_safe() -> None:
    assert resolve_references("", reference_map(["a"])).feature_ids == ()
    assert resolve_references(None, reference_map(["a"])).text == ""
