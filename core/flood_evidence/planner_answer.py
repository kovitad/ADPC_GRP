"""Live reported flooding in Planner answers for Bangkok (ADR-0056, step 3).

The facts are the pilot's own labelled bundle (``build_facts``) for the area's district, with
officer judgements removed (decision D2 is open). Rain stays in, as labelled context (D7,
4 October 2026). AI may only word these facts behind the pilot's gate (ADR-0043); the computed
answer is always available. Every answer ends with fixed, owner-approved text saying GRP issues
no warnings (D8, 4 October 2026). Nothing here touches an assessment, and live answers are never
cached.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.flood_evidence.answer import computed_answer
from core.flood_evidence.areas import COVERAGE_NAME, all_areas, in_pilot
from core.flood_evidence.briefing import build_facts
from core.flood_evidence.config import PilotConfig, pilot_config
from core.flood_evidence.situation import current_roads

PILOT_ID = "bangkok"
WINDOW_MINUTES = 60
BANGKOK = timezone(timedelta(hours=7))  # no daylight saving
# D8, approved by the Product Owner on 4 October 2026. Never written by the model.
NO_WARNINGS = {
    "en": "GRP does not issue flood warnings. For official warnings, follow the Thai "
          "Meteorological Department (TMD), the Department of Disaster Prevention and Mitigation "
          "(DDPM) and the Bangkok Metropolitan Administration (BMA).",
    "th": "GRP ไม่ได้ออกประกาศเตือนภัยน้ำท่วม โปรดติดตามประกาศเตือนภัยอย่างเป็นทางการจาก"
          "กรมอุตุนิยมวิทยา กรมป้องกันและบรรเทาสาธารณภัย (ปภ.) และกรุงเทพมหานคร (กทม.)",
}
LABEL = ("Live reported flooding (Floodboard, grouped by GRP), as of {time} Bangkok time. "
         "Not a flood map, not a warning, and not part of any assessment.")
THAI = re.compile(r"[฀-๿]")


def language(message: str) -> str:
    return "th" if THAI.search(message or "") else "en"


def in_live_area(admin_code: str | None) -> bool:
    """Whether live reported flooding covers this GRP district or sub-district (ADR-0057)."""

    config = pilot_config(PILOT_ID)
    return config is not None and in_pilot(config, admin_code)


def _without_officer_judgements(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Officer checks change no computed value, but they are internal until D2 is decided."""

    out = []
    for fact in facts:
        fact = dict(fact)
        fact.pop("officer_check", None)
        fact.pop("officer_checks", None)
        fact.pop("facilities_access_confirmed_cut", None)
        if fact.get("access") == "access_disrupted_confirmed":
            fact.pop("access")
        out.append(fact)
    return out


def _road_names(session: Session, config: PilotConfig, now: datetime) -> dict[str, str]:
    names = {}
    for feature in current_roads(session, config, now, include_all=True)["features"]:
        p = feature["properties"]
        names[p["id"]] = p.get("name_en") or p.get("name") or ""
    return names


def live_facts(session: Session, hub_code: str, admin_code: str, admin_level: str,
               now: datetime | None = None) -> dict[str, Any]:
    """The facts a Planner answer may use for a pilot area, or why there are none."""

    config = pilot_config(PILOT_ID)
    if config is None or not in_pilot(config, admin_code):
        return {"available": False, "reason": "outside_coverage"}
    if hub_code.strip().lower() not in config.hubs:
        return {"available": False, "reason": "hub_not_enabled"}
    district = str(admin_code)[:4]
    if district not in (config.demo_corridor.get("areas") or []):
        return {"available": False, "reason": "outside_coverage"}
    now = now or datetime.now(UTC)
    bundle = build_facts(session, config, district, now - timedelta(minutes=WINDOW_MINUTES), now,
                         _road_names(session, config, now))
    names = {a["admin_code"]: (a["name"], a.get("name_th")) for a in all_areas(config.base_id)}
    name_en, name_th = names.get(district, (district, None))
    return {
        "available": True, "district_code": district, "district_name": name_en,
        "district_name_th": name_th,
        "rolled_up_from": str(admin_code) if admin_level == "subdistrict" else None,
        "facts": _without_officer_judgements(bundle["facts"]),
        # Fact label to the incident or facility it describes (for cameras and reports).
        "labels": {label: info.get("ref") for label, info in bundle["labels"].items()},
        "as_of": now.isoformat(),
    }


def unavailable_answer(reason: str, lang: str) -> str:
    text = {
        "en": {"outside_coverage": f"Live reported flooding covers {COVERAGE_NAME['en']} only.",
               "hub_not_enabled": "Live reported flooding is not enabled for this Hub."},
        "th": {"outside_coverage": f"ข้อมูลรายงานน้ำท่วมแบบสดครอบคลุมเฉพาะ{COVERAGE_NAME['th']}",
               "hub_not_enabled": "ยังไม่ได้เปิดข้อมูลรายงานน้ำท่วมแบบสดสำหรับ Hub นี้"},
    }[lang][reason]
    return f"{text}\n\n{NO_WARNINGS[lang]}"


def computed_planner_answer(live: dict[str, Any], lang: str) -> str:
    """The fully computed answer, with the area named and the fixed no-warnings text."""

    head = {
        "en": "{name}: live reported flooding.",
        "th": "{name}: รายงานน้ำท่วมแบบสด",
    }[lang].format(name=live["district_name_th"] if lang == "th" and live["district_name_th"]
                   else live["district_name"])
    if live["rolled_up_from"]:
        head += {"en": " Shown for the whole district, not only the selected sub-district.",
                 "th": " แสดงทั้งเขต ไม่ใช่เฉพาะแขวงที่เลือก"}[lang]
    return f"{head}\n{computed_answer(live['facts'], lang)}\n\n{NO_WARNINGS[lang]}"


def label_for(live: dict[str, Any]) -> str:
    when = datetime.fromisoformat(live["as_of"]).astimezone(BANGKOK)
    return LABEL.format(time=when.strftime("%d %b %H:%M"))
