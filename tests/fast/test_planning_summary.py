"""ADR-0033: the district summary carries only this district's Global Risk evidence."""

from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.planning_summary import _global_risk
from core.access_models import AppUser, Base, Hub
from core.assessment_models import Boundary
from core.planning_memory_models import PlanningChatMessage
from grpcli.admin import assign_member, bootstrap_platform_admin, ensure_hub


def _boundary(name: str, code: str, province: str) -> Boundary:
    return Boundary(
        admin_code=code, admin_level="district", name=name, province_name=province,
        country_name="Thailand",
        geom={"type": "Polygon", "coordinates": [[[100, 13], [101, 13], [101, 14], [100, 13]]]},
        source="Thailand hierarchy delivery", edition="2025-10", geometry_sha256="a" * 64,
        is_supported=True,
    )


def _evidence(requested: str, **extra) -> dict:
    return {
        "answer": "## In short\\n3 of 9 schools [1]",
        "answer_source": "draft",
        "map_link": "https://sig.example/?embed=hazard_map&receipt_id=r1",
        "map_link_verified": False,
        "evidence": {
            "pack_id": f"pack-{requested[:4]}",
            "assembled_at": "2026-09-28T03:00:00+00:00",
            "area": {"requested": requested, "sig_place": requested.split(",")[0]},
            "summary": {"sources": 3, "pulled_live": 0, "computed": 3, "declared_gaps": 1},
            "stats": {"counts": {
                "schools": {"exposed": 3, "total": 9, "at_risk": 2, "by_risk": {"1": 2}},
                "roads": {"exposed_km": 1.5, "total_km": 10.0},
            }},
            "citations": [{"n": 1, "title": "schools vs flood", "source": "OSM"}],
            "gaps": ["vintages unknown"],
            "receipt": {"receipt_id": "r1", "public_url": "https://sig.example/r/r1"},
            **extra,
        },
    }


def test_only_this_districts_evidence_is_used_and_risk_fields_are_left_out() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        bootstrap_platform_admin(session, "owner@example.test")
        ensure_hub(session, actor_email="owner@example.test", code="adpc", name="ADPC Hub")
        assign_member(session, actor_email="owner@example.test", email="planner@example.test",
                      hub_code="adpc", role="planner")
        user = session.scalar(select(AppUser).where(AppUser.email == "planner@example.test"))
        hub = session.scalar(select(Hub).where(Hub.code == "adpc"))
        bang_kapi = _boundary("BANG KAPI", "1006", "BANGKOK")
        session.add(bang_kapi)
        # Bang Phli is newer, so a "latest evidence" shortcut would pick it.
        for requested, when in (
            ("BANG KAPI District, BANGKOK, Thailand", datetime(2026, 9, 28, 3)),
            ("BANG PHLI District, SAMUT PRAKAN, Thailand", datetime(2026, 9, 28, 4)),
        ):
            session.add(PlanningChatMessage(
                user_id=user.id, hub_id=hub.id, role="assistant", kind="evidence",
                text="", question=f"About {requested}", payload=_evidence(requested),
                created_at=when,
            ))
        session.commit()

        found = _global_risk(session, SimpleNamespace(user_id=user.id), hub.id, bang_kapi)

    assert found is not None
    assert found["place"] == "BANG KAPI District"
    assert found["question"] == "About BANG KAPI District, BANGKOK, Thailand"
    assert found["stats"] == [["schools", 3, 9, "count"], ["roads", 1.5, 10.0, "km"]]
    assert "receipt r1" in found["status"]
    assert found["map_link"].endswith("receipt_id=r1")
    assert found["source_note"] and "not a report of current flooding" in found["source_note"]
