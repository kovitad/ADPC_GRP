"""The planner's district summary as a Word document (ADR-0033).

Pure rendering: every fact arrives already gathered and screened by ``api/planning_summary.py``.
The wording follows what the Planning panel says and the rules behind it: "not exposed under
this scenario" (never "safe"), "N/A" for a centre the flood layer cannot assess, registered
village population (ADR-0027), sensitivity as a relative index (ADR-0030), no Global Risk risk
levels (ADR-0014), and Global Risk's map as an unverified link (ADR-0031).
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# Covers Thai and Latin; Word falls back sensibly where it is missing.
FONT = "Leelawadee UI"
INK = RGBColor(0x1C, 0x2A, 0x33)
MUTED = RGBColor(0x5B, 0x6B, 0x74)
WARN = RGBColor(0x8A, 0x53, 0x00)
TABLE_STYLE = "Table Grid"
MAX_TABLE_ROWS = 1000

STATUS_LABELS = {
    "potentially_exposed": "Potentially exposed",
    "not_exposed_under_scenario": "Not exposed under this scenario",
    "unable_to_assess": "N/A",
    "not_assessed": "Not assessed",
}


def _set_font(style_or_run: Any, size: float | None = None) -> None:
    font = style_or_run.font
    font.name = FONT
    if size:
        font.size = Pt(size)
    element = style_or_run.element
    rpr = element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(fonts)
    # w:cs is the slot Word uses for Thai; without it Thai names can fall back to boxes.
    for slot in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(slot), FONT)


def _styles(document: Any) -> None:
    for name, size in (("Normal", 10.5), ("Heading 1", 16), ("Heading 2", 13),
                       ("Heading 3", 11.5), ("Title", 22), ("Caption", 9)):
        style = document.styles[name]
        _set_font(style, size)
    document.styles["Normal"].font.color.rgb = INK
    for section in document.sections:
        section.left_margin = section.right_margin = Cm(2)
        section.top_margin = section.bottom_margin = Cm(1.8)


def _para(document: Any, text: str, *, bold: bool = False, color: RGBColor | None = None,
          size: float | None = None, style: str | None = None) -> Any:
    paragraph = document.add_paragraph(style=style)
    run = paragraph.add_run(text)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color
    if size:
        run.font.size = Pt(size)
    return paragraph


def _note(document: Any, text: str) -> None:
    _para(document, text, color=MUTED, size=9)


def _warn(document: Any, text: str) -> None:
    _para(document, text, color=WARN, size=9.5)


def _bullets(document: Any, items: list[str]) -> None:
    for item in items:
        document.add_paragraph(str(item), style="List Bullet")


def _table(document: Any, header: list[str], rows: list[list[Any]]) -> None:
    table = document.add_table(rows=1, cols=len(header))
    table.style = TABLE_STYLE
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for cell, text in zip(table.rows[0].cells, header, strict=True):
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        run.font.size = Pt(9)
    for row in rows[:MAX_TABLE_ROWS]:
        cells = table.add_row().cells
        for cell, value in zip(cells, row, strict=True):
            cell.text = ""
            run = cell.paragraphs[0].add_run("" if value is None else str(value))
            run.font.size = Pt(9)
    if len(rows) > MAX_TABLE_ROWS:
        _note(document, f"Showing the first {MAX_TABLE_ROWS:,} of {len(rows):,} rows; the CSV "
                        "download has them all.")


def _number(value: Any) -> str:
    if value is None:
        return "not recorded"
    if isinstance(value, float):
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _area_name(area: dict[str, Any]) -> str:
    level = "District" if area.get("admin_level") == "district" else "Sub-district"
    name = f"{area.get('name', '')} {level}".strip()
    if area.get("name_th"):
        name += f" ({area['name_th']})"
    return name


def render_summary(facts: dict[str, Any]) -> bytes:
    document = Document()
    _styles(document)
    area = facts["area"]
    province = area.get("province_name") or ""
    if area.get("province_name_th"):
        province += f" ({area['province_name_th']})"

    document.add_paragraph(f"Flood preparedness summary: {_area_name(area)}", style="Title")
    _para(document, ", ".join(p for p in (province, area.get("country_name") or "") if p),
          size=12)
    _note(document, f"{facts['hub']} · prepared by {facts['prepared_by']} · "
                    f"{facts['generated_at']} (Bangkok) · SERVIR Global Risk Platform (GRP)")
    if facts.get("synthetic"):
        _warn(document, "SYNTHETIC TEST DATA: invented inputs for software testing only. Do not "
                        "use for planning.")
    _warn(document, "Screening information for preparedness planning. It is not a report of "
                    "current flooding and does not certify that any place is safe.")

    # 1. At a glance
    document.add_heading("1. At a glance", level=1)
    centres = facts["centres"]
    glance: list[list[Any]] = [["Evacuation centres in the data", _number(centres["total"])]]
    summary = centres.get("summary")
    if summary:
        glance += [
            [f"Potentially exposed ({centres['scenario']})",
             _number(summary.get("potentially_exposed"))],
            ["Not exposed under this scenario", _number(summary.get("not_exposed_under_scenario"))],
            ["N/A (flood layer has no value at the centre)",
             _number(summary.get("unable_to_assess"))],
        ]
    people = facts.get("people") or {}
    population = people.get("population")
    if population:
        glance.append(
            ["Registered village population", _number(population.get("total_population"))]
        )
    exposure = people.get("flood_exposure")
    if exposure:
        glance.append([
            f"Registered people in villages inside the RP{exposure.get('return_period_years')} "
            "modelled flood extent",
            _number(exposure.get("people_in_zone")),
        ])
    for item in facts.get("supporting") or []:
        glance.append([item["title"], _number(item["count"])])
    _table(document, ["Item", "Value"], glance)

    # 2. Map
    document.add_heading("2. Map", level=1)
    picture = (facts.get("map") or {}).get("png")
    if picture:
        document.add_picture(BytesIO(picture), width=Cm(16.5))
        document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        _note(document, "No map picture was included with this download.")
    _para(document, (facts.get("map") or {}).get("caption") or "", style="Caption")

    # 3. Evacuation centres
    document.add_heading("3. Evacuation centres", level=1)
    _note(document, centres["source_line"])
    if centres["total"] == 0:
        _warn(document, centres.get("gap_note") or "The current shelter data has no records in "
                        "this area. This is a gap in the data, not a finding that it has no "
                        "shelters.")
    if summary:
        _para(document, f"Assessment {centres['assessment_id']} · {centres['scenario']} · "
                        f"method {centres['method']}", size=9.5)
    moveable = [row for row in centres["rows"]
                if row.get("status") == "not_exposed_under_scenario"]
    if summary:
        document.add_heading("Where people could move", level=2)
        if moveable:
            _para(document, f"{len(moveable):,} centre(s) are not exposed under this scenario. "
                            "Check access routes, capacity and current conditions before use.")
            _bullets(document, [
                f"{row['name']}" + (f" · {row['subdistrict']}" if row.get("subdistrict") else "")
                + (f" · capacity {row['capacity']}" if row.get("capacity") else "")
                for row in moveable[:60]
            ])
        else:
            _para(document, "No centre in this area is identified as not exposed under this "
                            "scenario. Plan for moving people to neighbouring areas.")
    indicator_titles = centres.get("indicator_titles") or {}
    header = ["Centre", "Sub-district", "Village", "Capacity", "Status", "Flood depth (m)"]
    header += list(indicator_titles.values())
    rows = []
    for row in centres["rows"]:
        values = [
            row.get("name"), row.get("subdistrict"), row.get("village"),
            row.get("capacity") if row.get("capacity") not in (None, "") else "unknown",
            STATUS_LABELS.get(row.get("status"), row.get("status")),
            "" if row.get("depth_m") is None else f"{row['depth_m']:.2f}",
        ]
        for key in indicator_titles:
            value = (row.get("indicators") or {}).get(key)
            values.append("" if value is None else f"{value:.2f}")
        rows.append(values)
    if rows:
        document.add_heading("All centres", level=2)
        _table(document, header, rows)
    if indicator_titles:
        _note(document, "Sensitivity values are the sub-district's relative index, 0 to 1. They "
                        "are not a number of people and are not used in the assessment.")

    # 4. People
    document.add_heading("4. People", level=1)
    if population:
        _table(document, ["Registered village population", "Value"], [
            ["People", _number(population.get("total_population"))],
            ["Male", _number(population.get("male"))],
            ["Female", _number(population.get("female"))],
            ["Households", _number(population.get("households"))],
            ["Villages with a count", f"{_number(population.get('counted_village_count'))} of "
                                      f"{_number(population.get('village_count'))}"],
        ])
        _note(document, "Registered population from the village register, not a census and not a "
                        "count of vulnerable people.")
    else:
        _note(document, "No population record for this area.")
    if exposure:
        document.add_heading(f"Villages inside the RP{exposure.get('return_period_years')} "
                             "modelled flood extent", level=2)
        _table(document, ["Item", "Value"], [
            ["Villages", _number(exposure.get("villages_in_zone"))],
            ["Registered people", _number(exposure.get("people_in_zone"))],
            ["Households", _number(exposure.get("households_in_zone"))],
        ])
        if exposure.get("caveat"):
            _note(document, exposure["caveat"])
    _note(document, "Children, older people and people with disabilities: no headcount exists "
                    "in the data. Sensitivity maps show where they are relatively more sensitive; "
                    "the disability layer is withheld until its classes are explained.")

    # 5. Global Risk evidence
    document.add_heading("5. Global Risk evidence", level=1)
    evidence = facts.get("global_risk")
    if not evidence:
        _note(document, "No Global Risk evidence has been gathered for this area in the last "
                        "30 days. Ask about this district in Planning to add it.")
    else:
        _para(document, f"{evidence['place']} · evidence pack {evidence['pack_id']} · gathered "
                        f"{evidence['assembled_at']} · {evidence['status']}", size=9.5)
        if evidence.get("question"):
            _note(document, f"Question: {evidence['question']}")
        if evidence.get("source_note"):
            _warn(document, evidence["source_note"])
        if evidence.get("stats"):
            document.add_heading("What Global Risk adds for this district", level=2)
            _para(document, "GRP's own data covers evacuation centres. Global Risk also counts "
                            "schools, hospitals, buildings and roads inside its 100-year flood "
                            "hazard layer. \"In flood hazard\" means flood hazard class 1 or "
                            "higher (1 = up to 0.5 m, 5 = over 2 m); it is not a report of "
                            "current flooding.", size=9.5)
            _table(document, ["Item", "In flood hazard", "Total", "Unit", "By depth class",
                              "What it means"], evidence["stats"])
            if all(row[1] == 0 for row in evidence["stats"]):
                _note(document, "Global Risk found none of these in its flood hazard layer for "
                                "this district. That is a result, not missing data.")
        if evidence.get("brief"):
            document.add_heading("Brief", level=2)
            for line in str(evidence["brief"]).splitlines():
                text = line.strip()
                if not text:
                    continue
                if text.startswith("#"):
                    document.add_heading(text.lstrip("#").strip(), level=3)
                elif text[:2] in {"- ", "* "}:
                    document.add_paragraph(text[2:].replace("**", ""), style="List Bullet")
                else:
                    document.add_paragraph(text.replace("**", ""))
        if evidence.get("receipt_id"):
            _para(document, f"Public receipt {evidence['receipt_id']}: "
                            f"{evidence.get('receipt_url') or ''}", size=9.5)
        if evidence.get("map_link"):
            _para(document, f"Global Risk map: {evidence['map_link']}", size=9.5)
            _note(document, "Global Risk's own view of this receipt. GRP could not confirm which "
                            "layer its colours show (flood depth or vulnerability-weighted risk).")
        if evidence.get("citations"):
            document.add_heading("Global Risk sources", level=2)
            _table(document, ["#", "Title", "Source", "Validation", "Retrieval"],
                   evidence["citations"])
        if evidence.get("gaps"):
            document.add_heading("Gaps Global Risk declared", level=2)
            _bullets(document, evidence["gaps"])

    # 6. Limits
    document.add_heading("6. What this cannot tell you", level=1)
    _bullets(document, facts.get("limits") or [])

    # 7. Sources
    document.add_heading("7. Sources and versions", level=1)
    _table(document, ["Role", "Title", "Provider", "Version"], facts.get("sources") or [])
    _note(document, "Generated by GRP from the data versions above. Numbers are copied from the "
                    "stored records; nothing in this document was estimated for it.")

    out = BytesIO()
    document.save(out)
    return out.getvalue()
