"""What the shared SERVIR SIG service actually returned on 23 September 2026.

These fixtures were captured from https://servirplatform.sig-gis.com/mcp, not written by
hand, so they are the first evidence in this repository of the real contract. They exist to
stop three assumptions being carried forward untested: that SIG's area for a Thai district
matches GRP's, that the flood risk recipe is unknown to us, and that a vulnerable-people
layer has to be contributed before it can be weighted.
"""

import json
import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sig"
SECRET_PATTERN = re.compile(
    r"Bearer\s|access_token|refresh_token|client_secret|session=|Cookie", re.IGNORECASE
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_recorded_fixtures_carry_no_credentials() -> None:
    """A recorded response is committed; it must never carry what authorized the call."""

    for path in FIXTURES.glob("*.json"):
        assert not SECRET_PATTERN.search(path.read_text(encoding="utf-8")), path


def test_sig_resolves_a_thai_district_as_a_real_admin_boundary() -> None:
    place = _load("resolve_place_time_mueang_nan.json")["place"]

    assert place["is_admin_boundary"] is True
    assert "admin boundary" in place["how"]
    # SIG derives this area from OpenStreetMap, not from GRP's imported districts. Any count
    # GRP reconciles against SIG must account for the difference rather than assume equality.
    assert place["area_km2"] == 1095


def test_the_live_flood_recipe_is_known_and_well_formed() -> None:
    picker = _load("risk_weights_flood.json")["weights_picker"]
    recipe = picker["recipes"]["flood"]

    assert round(sum(recipe.values()), 6) == 1.0
    assert set(recipe) <= set(picker["available_layers"])
    # ADR-0015 lets GRP show one explicitly declared SIG risk layer. The formula behind it is
    # recorded here so a declared layer can be checked rather than trusted.
    assert picker["crossing_rule"] == "clip(round(hazard * V / class_max), 1, class_max)"


def test_sig_already_carries_age_disaggregated_vulnerability_layers() -> None:
    """DEP-07 asks which layer means 'vulnerable people'. SIG publishes candidates already."""

    layers = set(_load("risk_weights_flood.json")["weights_picker"]["available_layers"])

    assert {"vulnerability_F_above60", "vulnerability_M_above60"} <= layers
    assert {"vulnerability_F_infant", "vulnerability_M_infant"} <= layers
    # None of them is in the flood recipe today, so elderly and infants currently carry no
    # weight in any SIG flood risk level.
    assert not layers & set(_load("risk_weights_flood.json")["weights_picker"]["recipes"]["flood"]) & {
        "vulnerability_F_above60",
        "vulnerability_M_above60",
        "vulnerability_F_infant",
        "vulnerability_M_infant",
    }
