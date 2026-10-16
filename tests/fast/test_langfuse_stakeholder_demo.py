"""Static safety contract for the optional synthetic Langfuse demonstration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/langfuse_demo/stakeholder_demo_v1.yaml"
SCRIPT = ROOT / "scripts/langfuse_stakeholder_demo.py"


def test_demo_fixture_cannot_be_mistaken_for_a_scientific_golden() -> None:
    text = FIXTURE.read_text(encoding="utf-8")

    assert "synthetic_demo: true" in text
    assert "approved_for_operations: false" in text
    assert text.count("  - id: demo-") == 6
    assert text.count("SYNTHETIC FIXTURE") == 6
    assert "must never be used for planning" in text


def test_demo_runner_fails_closed_on_missing_synthetic_markers() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'dataset.get("synthetic_demo") is True' in text
    assert 'dataset.get("approved_for_operations") is False' in text
    assert 'choices=("validate", "sync", "dashboard", "run", "all")' in text
    assert 'os.environ.setdefault("LANGFUSE_HOST"' in text
    assert "LANGFUSE_SECRET_KEY" in text
    assert "print(os.environ" not in text
