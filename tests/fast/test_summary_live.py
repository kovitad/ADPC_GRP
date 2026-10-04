"""The district summary's live section, in English and Thai (ADR-0056, summary amendment)."""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime

import pytest
from docx import Document

import core.flood_evidence.summary_live as summary_live
from core.flood_evidence.planner_answer import NO_WARNINGS
from core.summary_docx import render_summary

NOW = datetime(2026, 10, 4, 7, 20, tzinfo=UTC)
PICTURE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
FACTS = [
    {"id": "S", "kind": "situation", "active_incidents": 2, "conflicting_incidents": 0,
     "incidents_by_confidence": {"conflicting": 0, "low": 1, "medium": 1, "high": 0}},
    {"id": "C", "kind": "changes", "window_minutes": 60, "new_incidents": 1,
     "incidents_grew": 0, "no_longer_reported": 1},
    {"id": "I1", "kind": "incident", "roads": ["Chalong Krung Road"], "confidence": "low",
     "reports": 2, "deepest_reported_cm": 20, "newest_evidence_bangkok": "14:05"},
    {"id": "I2", "kind": "incident", "roads": ["Luang Phaeng Road"], "confidence": "medium",
     "reports": 3, "deepest_reported_cm": None, "newest_evidence_bangkok": "14:10"},
    {"id": "F1", "kind": "facility", "name": "วัดหนองจอก", "facility_type": "evacuation_centre",
     "flooding_reported_within_m": 90, "source": "DDPM evacuation centre (GRP data library)"},
    {"id": "L", "kind": "limits", "incidents_not_listed": 0},
]
ROAD = {"type": "LineString", "coordinates": [[100.75, 13.72], [100.751, 13.72]]}


def _camera(camera_id: str, provider: str, distance: int) -> dict:
    return {"camera_id": camera_id, "provider": provider, "provider_camera_id": camera_id[-4:],
            "name": f"Camera {camera_id}", "viewer_url": None, "placeholder": False,
            "source_label": "BMA traffic", "distance_m": distance}


@pytest.fixture
def stored(monkeypatch):
    monkeypatch.setattr(summary_live, "live_facts", lambda *_a, **_k: {
        "available": True, "district_code": "1011", "district_name": "Lat Krabang",
        "district_name_th": "ลาดกระบัง", "rolled_up_from": None, "facts": FACTS,
        "labels": {"I1": "inc-1", "I2": "inc-2", "F1": "ddpm:1"}, "as_of": NOW.isoformat()})
    monkeypatch.setattr(summary_live, "list_incidents", lambda *_a: {"incidents": [
        {"incident_id": "inc-1", "road_keys": ["a" * 16]},
        {"incident_id": "inc-2", "road_keys": ["b" * 16]},
    ]})
    monkeypatch.setattr(summary_live, "current_roads", lambda *_a, **_k: {
        "features": [{"properties": {"id": k * 16}, "geometry": ROAD} for k in "ab"],
        "snapshot_retrieved_at": "2026-10-04T07:10:00+00:00"})
    monkeypatch.setattr(summary_live, "camera_registry", lambda _pilot: ())
    monkeypatch.setattr(summary_live, "nearby_cameras", lambda *_a: [
        _camera("bmatraffic:1362", "BMA_TRAFFIC", 120), _camera("itic:9", "ITIC", 50)])


def test_the_live_section_gathers_incidents_facilities_and_one_camera_per_incident(stored) -> None:
    fetched = []

    def frame(camera_id):
        fetched.append(camera_id)
        return PICTURE, NOW

    live = summary_live.live_section(None, "adpc", "1011", "district", NOW, get_frame=frame)
    assert live["available"] and live["as_of"] == "04 Oct 2026 14:10"
    assert [i["id"] for i in live["incidents"]] == ["I1", "I2"]
    assert live["facilities"][0]["facility_type"] == "evacuation_centre"
    first, second = live["cameras"]
    assert first["picture"] == PICTURE and first["credit"] == summary_live.CAMERA_CREDIT
    # A camera already used for one incident is not repeated for the next.
    assert second["name"] == "Camera itic:9" and second["picture"] is None
    assert fetched == ["1362"]


def test_a_camera_that_does_not_answer_is_listed_without_a_picture(stored) -> None:
    def broken(_camera_id):
        raise RuntimeError("no picture")

    live = summary_live.live_section(None, "adpc", "1011", "district", NOW, get_frame=broken)
    assert live["cameras"][0]["picture"] is None
    assert live["cameras"][0]["picture_note"] == "camera did not answer"


def _text(docx_bytes: bytes) -> str:
    document = Document(io.BytesIO(docx_bytes))
    return "\n".join([p.text for p in document.paragraphs]
                     + [c.text for t in document.tables for r in t.rows for c in r.cells])


def _facts(live: dict) -> dict:
    return {"generated_at": "04 Oct 2026 14:20", "prepared_by": "Planner", "hub": "ADPC Hub",
            "area": {"name": "LAT KRABANG", "name_th": "ลาดกระบัง", "admin_level": "district",
                     "province_name": "BANGKOK"},
            "centres": {"total": 0, "rows": [], "gap_note": "No centres.",
                        "source_line": "Shelters"},
            "live": live, "limits": [], "sources": []}


def test_the_english_summary_has_the_live_section_after_global_risk_with_a_picture(stored) -> None:
    live = summary_live.live_section(None, "adpc", "1011", "district", NOW,
                                     get_frame=lambda _c: (PICTURE, NOW))
    out = render_summary(_facts(live), "en")
    text = _text(out)
    assert text.index("5. Global Risk evidence") < text.index("6. Live reported flooding")
    assert text.index("6. Live reported flooding") < text.index("7. What this cannot tell you")
    assert "As of 04 Oct 2026 14:10, Bangkok time" in text and "not a warning" in text
    assert "DDPM evacuation centre" in text and "Chalong Krung Road" in text
    assert NO_WARNINGS["en"] in text and NO_WARNINGS["th"] in text
    assert "officer" not in text.lower()
    assert len(Document(io.BytesIO(out)).inline_shapes) == 1


def test_the_thai_summary_translates_fixed_text_and_keeps_the_rules(stored) -> None:
    live = summary_live.live_section(None, "adpc", "1011", "district", NOW,
                                     get_frame=lambda _c: (PICTURE, NOW))
    text = _text(render_summary(_facts(live), "th"))
    assert "สรุปการเตรียมความพร้อมรับมือน้ำท่วม" in text
    assert "6. รายงานน้ำท่วมแบบสด" in text and "ศูนย์พักพิง ปภ." in text
    assert NO_WARNINGS["th"] in text
    assert "1. At a glance" not in text


def test_outside_bangkok_the_live_section_is_one_plain_line() -> None:
    text = _text(render_summary(_facts({"available": False, "reason": "outside_coverage"}), "en"))
    assert "6. Live reported flooding" in text and "covers Bangkok only" in text
