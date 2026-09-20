# ruff: noqa: E501
"""Generate the editable multi-page draw.io architecture handoff for ADR-0013."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "GRP_Evacuation_Decision_Agent_and_Data_Architecture.drawio"

BLUE = "#1769AA"
NAVY = "#17365D"
GREEN = "#4E8A57"
AMBER = "#C48A00"
PURPLE = "#704A8E"
RED = "#B33A3A"
GREY = "#60727B"


@dataclass
class Box:
    id: str
    label: str
    x: int
    y: int
    w: int
    h: int
    fill: str = "#F5F9FD"
    stroke: str = BLUE
    shape: str = "rounded=1"
    parent: str = "1"


class Page:
    def __init__(self, name: str, width: int = 1900, height: int = 1200):
        self.diagram = ET.Element("diagram", {"name": name, "id": name.lower().replace(" ", "-")})
        self.model = ET.SubElement(
            self.diagram,
            "mxGraphModel",
            {
                "dx": "1600",
                "dy": "900",
                "grid": "1",
                "gridSize": "10",
                "guides": "1",
                "tooltips": "1",
                "connect": "1",
                "arrows": "1",
                "fold": "1",
                "page": "1",
                "pageScale": "1",
                "pageWidth": str(width),
                "pageHeight": str(height),
                "math": "0",
                "shadow": "0",
            },
        )
        self.root = ET.SubElement(self.model, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})

    def box(self, box: Box, *, font_size: int = 14, bold: bool = False, dashed: bool = False) -> None:
        style = (
            f"{box.shape};whiteSpace=wrap;html=1;fillColor={box.fill};strokeColor={box.stroke};"
            f"fontColor=#172B34;fontSize={font_size};align=center;verticalAlign=middle;spacing=8;"
            f"fontStyle={1 if bold else 0};dashed={1 if dashed else 0};"
        )
        cell = ET.SubElement(
            self.root,
            "mxCell",
            {"id": box.id, "value": box.label, "style": style, "vertex": "1", "parent": box.parent},
        )
        ET.SubElement(
            cell,
            "mxGeometry",
            {"x": str(box.x), "y": str(box.y), "width": str(box.w), "height": str(box.h), "as": "geometry"},
        )

    def container(self, id_: str, label: str, x: int, y: int, w: int, h: int, fill: str, stroke: str) -> None:
        self.box(
            Box(
                id_,
                label,
                x,
                y,
                w,
                h,
                fill,
                stroke,
                "swimlane;horizontal=1;startSize=38;rounded=1;collapsible=0",
            ),
            font_size=16,
            bold=True,
        )

    def note(self, id_: str, label: str, x: int, y: int, w: int, h: int, fill: str = "#FFF4D6") -> None:
        self.box(Box(id_, label, x, y, w, h, fill, AMBER, "shape=note;whiteSpace=wrap;html=1"), font_size=12)

    def edge(
        self,
        id_: str,
        source: str,
        target: str,
        label: str = "",
        *,
        color: str = GREY,
        dashed: bool = False,
    ) -> None:
        style = (
            f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;"
            f"endArrow=block;endFill=1;strokeWidth=2;strokeColor={color};"
            f"dashed={1 if dashed else 0};fontSize=11;labelBackgroundColor=#FFFFFF;"
        )
        cell = ET.SubElement(
            self.root,
            "mxCell",
            {
                "id": id_,
                "value": label,
                "style": style,
                "edge": "1",
                "parent": "1",
                "source": source,
                "target": target,
            },
        )
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    def title(self, id_: str, text: str, subtitle: str) -> None:
        self.box(Box(id_, f"<b>{text}</b><br><font color='#60727B'>{subtitle}</font>", 30, 20, 1800, 70, "#FFFFFF", "#FFFFFF", "text;html=1;strokeColor=none;fillColor=none"), font_size=24)


def context_page() -> Page:
    p = Page("1 Context and trust boundaries", 1900, 1100)
    p.title("title", "Evacuation Preparedness Decision Platform", "Bounded AI orchestration; candidate movement options plus a traceable investment case")
    p.box(Box("planner", "<b>Planner / Hub reviewer</b><br>Confirms purpose, AOI and scenario<br>Reviews candidates, gaps and publication", 60, 420, 250, 150, "#DCEAF7", BLUE), bold=True)
    p.container("grp", "ADPC GRP trust boundary", 390, 120, 1040, 820, "#F7FBFE", BLUE)
    p.box(Box("web", "<b>Planning web</b><br>Purpose and AOI<br>Coverage matrix<br>Map and review", 440, 230, 210, 150, "#DCEAF7", BLUE), bold=True)
    p.box(Box("api", "<b>FastAPI</b><br>Sessions / CSRF<br>Role and Hub policy<br>Typed APIs", 720, 230, 210, 150, "#DCEAF7", BLUE), bold=True)
    p.box(Box("orch", "<b>Bounded decision orchestrator</b><br>Fixed task plans<br>Tool budgets<br>Evidence normalization", 1000, 210, 260, 190, "#FFF4D6", AMBER), bold=True)
    p.box(Box("db", "<b>PostgreSQL + PostGIS</b><br>Areas and versions<br>Jobs and locked results<br>Package revisions / audit", 710, 500, 260, 180, "#E7F2E8", GREEN, "shape=cylinder"), bold=True)
    p.box(Box("queue", "<b>Leased job queues</b><br>Assessment<br>Evidence package<br>Export", 1030, 500, 220, 160, "#FFF4D6", AMBER), bold=True)
    p.box(Box("worker", "<b>Workers</b><br>GIS and comparison<br>Evidence gathering<br>PDF/map export", 1010, 750, 260, 150, "#FFF4D6", AMBER), bold=True)
    p.box(Box("store", "<b>Managed storage</b><br>Originals / COGs<br>Previews / exports<br>Immutable keys", 540, 750, 260, 150, "#E7F2E8", GREEN, "shape=folder"), bold=True)
    p.box(Box("ai", "<b>AI gateway</b><br>Allowance / usage<br>Prompt versions<br>Langfuse best effort", 1300, 470, 100, 180, "#F0E8F7", PURPLE), bold=True)
    p.container("sig", "SIG trust boundary", 1510, 180, 330, 600, "#FAF7FC", PURPLE)
    p.box(Box("mcp", "<b>SIG MCP</b><br>Generic screening pack<br>Citations and trace", 1550, 300, 250, 130, "#F0E8F7", PURPLE), bold=True)
    p.box(Box("gate", "<b>Grounding gate</b><br>Exact reviewed draft", 1550, 500, 250, 110, "#F0E8F7", PURPLE), bold=True)
    p.box(Box("receipt", "<b>Receipt-bound map</b><br>Explicit public action", 1550, 670, 250, 90, "#F0E8F7", PURPLE), bold=True)
    p.note("guard", "Candidate does not mean certified safe. Local GRP results, display-only baseline facts and SIG screening remain separately labelled.", 420, 960, 1380, 90)
    for args in [
        ("e1", "planner", "web", "question / review"), ("e2", "web", "api", "HTTPS JSON"),
        ("e3", "api", "orch", "authorized intent"), ("e4", "orch", "db", "local context"),
        ("e5", "orch", "queue", "durable work"), ("e6", "queue", "worker", "leased jobs"),
        ("e7", "worker", "db", "immutable results"), ("e8", "worker", "store", "files / exports"),
        ("e9", "orch", "ai", "validated envelope"), ("e10", "orch", "mcp", "allow-listed call"),
        ("e11", "mcp", "gate", "publish only after review"), ("e12", "gate", "receipt", "approved"),
    ]:
        p.edge(*args)
    return p


def agent_page() -> Page:
    p = Page("2 Bounded agent workflow", 2000, 1300)
    p.title("title", "Bounded AI-agent workflow", "Deterministic policy controls tools; AI routes and explains but never calculates GIS or invents missing evidence")
    boxes = [
        Box("q", "<b>1. Planner request</b><br>movement options or investment case", 60, 170, 250, 110, "#DCEAF7", BLUE),
        Box("auth", "<b>2. Access gate</b><br>session, role, Hub, allowance", 380, 170, 230, 110, "#DCEAF7", BLUE),
        Box("intent", "<b>3. Intent proposal</b><br>enum + AOI + scenario only", 680, 170, 240, 110, "#F0E8F7", PURPLE),
        Box("confirm", "<b>4. AOI confirmation</b><br>district/sub-district must resolve uniquely", 990, 160, 280, 130, "#FFF4D6", AMBER),
        Box("coverage", "<b>5. Coverage matrix</b><br>available / partial / missing / blocked", 1350, 160, 300, 130, "#E7F2E8", GREEN),
        Box("plan", "<b>6. Fixed task plan</b><br>server chooses allow-listed tools and budgets", 1710, 150, 250, 150, "#FFF4D6", AMBER),
        Box("local", "<b>Local branch</b><br>resolve compatible inputs<br>read locked result or queue assessment", 260, 450, 330, 170, "#E7F2E8", GREEN),
        Box("sig", "<b>SIG branch</b><br>only when complementary evidence is needed<br>timeout / retry / circuit breaker", 780, 450, 350, 170, "#F0E8F7", PURPLE),
        Box("gap", "<b>Typed gaps</b><br>readiness block, missing source,<br>timeout, refusal or incompatible scope", 1320, 450, 330, 170, "#FBE5E5", RED),
        Box("env", "<b>7. Evidence envelope v1</b><br>facts + sources + versions + scope + units + disclosure + gaps", 610, 760, 760, 150, "#FFF4D6", AMBER),
        Box("validate", "<b>8. Deterministic validation</b><br>schema, provenance, compatibility, privacy, required sections", 230, 1030, 360, 150, "#DCEAF7", BLUE),
        Box("compose", "<b>9. AI composition</b><br>cited explanation from envelope only", 720, 1030, 300, 150, "#F0E8F7", PURPLE),
        Box("claims", "<b>10. Claim checker</b><br>citations, prohibited claims,<br>no invented numbers or safety", 1130, 1030, 320, 150, "#DCEAF7", BLUE),
        Box("revision", "<b>11. Immutable package revision</b><br>review → private export<br>or explicit SIG publication", 1570, 1020, 350, 170, "#E7F2E8", GREEN),
    ]
    for box in boxes:
        p.box(box, bold=True)
    for args in [
        ("e1", "q", "auth", ""), ("e2", "auth", "intent", ""), ("e3", "intent", "confirm", "proposal only"),
        ("e4", "confirm", "coverage", "confirmed"), ("e5", "coverage", "plan", ""),
        ("e6", "plan", "local", "if local needed"), ("e7", "plan", "sig", "if SIG needed"),
        ("e8", "plan", "gap", "blocked dimension"), ("e9", "local", "env", "normalized facts"),
        ("e10", "sig", "env", "screening facts"), ("e11", "gap", "env", "explicit gaps"),
        ("e12", "env", "validate", ""), ("e13", "validate", "compose", "valid subset"),
        ("e14", "compose", "claims", "draft"), ("e15", "claims", "revision", "pass"),
    ]:
        p.edge(*args)
    p.note("rules", "Tool allow-list: area.resolve • coverage.build • catalog.resolve_inputs • assessment.get/queue • sig.screen • evidence.validate • package.compose • export.queue • publish.sig", 80, 1230, 1840, 55)
    return p


def data_page() -> Page:
    p = Page("3 Data and lineage", 2100, 1300)
    p.title("title", "Data architecture and lineage", "Immutable source versions feed pinned assessments; normalized evidence feeds immutable decision-package revisions")
    p.container("library", "Versioned data library", 50, 140, 600, 1000, "#F7FBFE", BLUE)
    p.container("assessment", "Assessment domain", 750, 140, 550, 1000, "#F8FCF8", GREEN)
    p.container("package", "Decision-package domain (proposed)", 1400, 140, 650, 1000, "#FFFCF4", AMBER)
    for box in [
        Box("dataset", "<b>dataset</b><br>category, owner, provider, Hub", 110, 240, 220, 110),
        Box("version", "<b>dataset_version</b><br>readiness, checksum, scenario,<br>current/display-only", 370, 230, 230, 130, "#E7F2E8", GREEN),
        Box("file", "<b>dataset_file</b><br>role, immutable key,<br>checksum, bytes", 100, 470, 220, 120),
        Box("boundary", "<b>boundary</b><br>admin level/code, parent,<br>full + simplified PostGIS geometry", 370, 460, 230, 140),
        Box("feature", "<b>feature</b><br>evacuation centre point<br>attributes + membership", 100, 700, 220, 130),
        Box("selection", "<b>hub_dataset_selection</b><br>accepted category override<br>scenario key", 370, 700, 230, 130),
        Box("import", "<b>data_import_job</b><br>lease, fence, manifest,<br>validation report", 230, 930, 250, 130, "#FFF4D6", AMBER),
        Box("method", "<b>method</b><br>versioned scientific rules<br>requirements / reason codes", 810, 260, 230, 130, "#DCEAF7", BLUE),
        Box("assess", "<b>assessment</b><br>Hub, boundary, method,<br>pinned input IDs + SHA-256", 1040, 470, 220, 140, "#E7F2E8", GREEN),
        Box("af", "<b>assessment_feature</b><br>status, reason,<br>depth and approved metrics", 810, 710, 230, 140, "#E7F2E8", GREEN),
        Box("audit", "<b>audit_event + usage</b><br>support reference, actor,<br>action and result", 1040, 930, 220, 120, "#EEF1F4", GREY),
        Box("pkg", "<b>decision_package</b><br>Hub, creator, AOI, purpose,<br>scenario and workflow state", 1460, 230, 250, 140, "#FFF4D6", AMBER),
        Box("rev", "<b>decision_package_revision</b><br>immutable envelope/narrative hashes<br>assessment link / sharing state", 1750, 220, 250, 160, "#FFF4D6", AMBER),
        Box("ev", "<b>evidence_item</b><br>source kind/ref, scope, unit,<br>denominator, readiness, disclosure", 1450, 500, 270, 160, "#DCEAF7", BLUE),
        Box("gap", "<b>evidence_gap</b><br>dimension, status, reason,<br>blocking flag and owner", 1760, 500, 230, 150, "#FBE5E5", RED),
        Box("intervention", "<b>intervention_option</b><br>approved category, rationale,<br>evidence keys, reviewed cost", 1450, 760, 270, 160, "#E7F2E8", GREEN),
        Box("export", "<b>package_export</b><br>leased job, template,<br>private managed file", 1760, 770, 230, 140, "#E7F2E8", GREEN),
        Box("sigev", "<b>Normalized SIG evidence</b><br>approved fields and citations only<br>no token / unrestricted response", 1570, 990, 310, 120, "#F0E8F7", PURPLE),
    ]:
        p.box(box, bold=True)
    for args in [
        ("e1", "dataset", "version", "1:N"), ("e2", "version", "file", "1:N"),
        ("e3", "version", "boundary", "collection"), ("e4", "version", "feature", "provides"),
        ("e5", "selection", "version", "chooses"), ("e6", "import", "version", "publishes"),
        ("e7", "boundary", "assess", "scopes"), ("e8", "version", "assess", "pins"),
        ("e9", "method", "assess", "applies"), ("e10", "assess", "af", "classifies"),
        ("e11", "assess", "rev", "locked result"), ("e12", "pkg", "rev", "1:N"),
        ("e13", "rev", "ev", "1:N"), ("e14", "rev", "gap", "1:N"),
        ("e15", "rev", "intervention", "1:N"), ("e16", "rev", "export", "1:N"),
        ("e17", "version", "ev", "catalog provenance"), ("e18", "sigev", "ev", "normalizes"),
        ("e19", "af", "ev", "result facts"), ("e20", "audit", "pkg", "traces"),
    ]:
        p.edge(*args)
    p.note("immut", "Immutability boundary: dataset versions, successful assessments and package revisions are append-only. New evidence creates a new revision; it never edits an old result.", 120, 1160, 1880, 80)
    return p


def deployment_page() -> Page:
    p = Page("4 Current Ubuntu VM deployment", 2000, 1200)
    p.title("title", "Deployment on the current Ubuntu VM", "Keep the modular monolith; add process types and durable records before considering microservices")
    p.container("internet", "Public / external", 40, 150, 350, 850, "#FAF7FC", PURPLE)
    p.container("host", "Ubuntu 22.04 / 24.04 VM — /srv/grp", 440, 120, 1480, 980, "#F7FBFE", BLUE)
    p.box(Box("browser", "<b>Planner browser</b><br>HTTPS only", 100, 280, 230, 100, "#DCEAF7", BLUE), bold=True)
    p.box(Box("servir", "<b>SERVIR/SIG</b><br>OIDC + MCP + receipt", 90, 520, 250, 130, "#F0E8F7", PURPLE), bold=True)
    p.box(Box("llm", "<b>LLM / Langfuse</b><br>outbound HTTPS", 100, 760, 230, 120, "#F0E8F7", PURPLE), bold=True)
    p.box(Box("caddy", "<b>Host Caddy</b><br>80/443, TLS, headers<br>static /srv/grp/app/web<br>/api → 127.0.0.1:8000", 500, 220, 280, 180, "#DCEAF7", BLUE), bold=True)
    p.box(Box("api", "<b>grp-api container</b><br>FastAPI + orchestrator<br>loopback 127.0.0.1:8000<br>read-only root filesystem", 860, 210, 290, 190, "#DCEAF7", BLUE), bold=True)
    p.box(Box("worker", "<b>grp-worker container</b><br>assessment + import now<br>package/export task types next<br>WORKER_CONCURRENCY=1", 1230, 210, 300, 190, "#FFF4D6", AMBER), bold=True)
    p.box(Box("db", "<b>PostGIS 16 container</b><br>metadata, vectors, leases,<br>results, package revisions<br>named volume grp_db", 1600, 210, 260, 190, "#E7F2E8", GREEN, "shape=cylinder"), bold=True)
    p.box(Box("data", "<b>/srv/grp/data</b><br>UID/GID 10001, mode 0750<br>managed originals, COGs,<br>previews and private exports", 880, 570, 300, 190, "#E7F2E8", GREEN, "shape=folder"), bold=True)
    p.box(Box("secrets", "<b>/srv/grp/secrets</b><br>root:root 0600<br>database URL, session key,<br>OIDC/SIG/AI/Langfuse secrets", 1250, 570, 300, 190, "#FBE5E5", RED, "shape=folder"), bold=True)
    p.box(Box("release", "<b>/srv/grp/app + releases</b><br>clean checkout / image reference<br>release manifest and Caddy backups", 500, 570, 300, 190, "#EEF1F4", GREY, "shape=folder"), bold=True)
    p.box(Box("backup", "<b>Backup / restore</b><br>PostgreSQL + managed data together<br>off-host copy and restore drill required", 1580, 570, 290, 190, "#FFF4D6", AMBER), bold=True)
    p.note("deploy", "Preferred staging deployment: build/test and publish a versioned GHCR image in CI; bootstrap with --deploy-mode image; run Alembic once; then start API and worker. Do not copy local .env or tokens.", 520, 880, 1320, 100)
    p.note("scale", "Before a second API replica: move SIG token, answer/evidence cache and rate-limit state out of process. Scale workers first; add separate queues/processes for package and export jobs when measured load requires it.", 520, 1000, 1320, 80, "#E7F2E8")
    for args in [
        ("e1", "browser", "caddy", "HTTPS 443"), ("e2", "caddy", "api", "/api reverse proxy"),
        ("e3", "api", "db", "transactions / queue"), ("e4", "db", "worker", "SKIP LOCKED leases"),
        ("e5", "worker", "data", "read/write immutable keys"), ("e6", "api", "secrets", "read-only mount"),
        ("e7", "worker", "secrets", "read-only mount"), ("e8", "api", "servir", "OIDC / MCP"),
        ("e9", "api", "llm", "AI gateway"), ("e10", "release", "caddy", "static web"),
        ("e11", "db", "backup", "coordinated backup"), ("e12", "data", "backup", "coordinated backup"),
    ]:
        p.edge(*args)
    return p


def roadmap_page() -> Page:
    p = Page("5 Implementation and technology", 2100, 1300)
    p.title("title", "Implementation roadmap and technology stack", "Deliver decision value incrementally without fabricating unavailable science or splitting into premature microservices")
    phases = [
        ("a", "<b>Phase A — contracts and honest UX</b><br>AOI API • evidence envelope • coverage matrix<br>input resolver • separate GRP/SIG sections", 80, 180, BLUE, "#DCEAF7"),
        ("b", "<b>Phase B — sub-district catalogue</b><br>7,436 polygons • parent links • qualified search<br>unsupported until explicitly activated", 560, 180, GREEN, "#E7F2E8"),
        ("c", "<b>Phase C — durable package</b><br>package/revision/evidence/gap tables<br>leased worker • SSE • partial failure", 1040, 180, AMBER, "#FFF4D6"),
        ("d", "<b>Phase D — real movement screening</b><br>DEP-05 • pilot area approval • real locked result<br>candidate does not mean safe", 1520, 180, RED, "#FBE5E5"),
        ("e", "<b>Phase E — vulnerability and suitability</b><br>approved population • capacity • accessibility<br>services and route methods", 560, 480, PURPLE, "#F0E8F7"),
        ("f", "<b>Phase F — investment and comparison</b><br>approved costs/interventions • multiple RPs<br>DEP-12 private brief and map exports", 1040, 480, GREEN, "#E7F2E8"),
    ]
    for id_, label, x, y, stroke, fill in phases:
        p.box(Box(id_, label, x, y, 420, 180, fill, stroke), bold=True)
    for n, (s, t) in enumerate([("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("e", "f")], 1):
        p.edge(f"phase{n}", s, t)
    p.container("stack", "Current and recommended technology", 80, 750, 900, 430, "#F7FBFE", BLUE)
    p.container("done", "Definition of done / non-negotiable controls", 1060, 750, 960, 430, "#FFFCF4", AMBER)
    p.box(Box("stack1", "<b>Web</b><br>Static HTML/CSS/JS + Leaflet<br>split planning.js into area/config/package/map modules<br>SSE with polling fallback", 130, 840, 360, 260, "#DCEAF7", BLUE), bold=True)
    p.box(Box("stack2", "<b>Backend</b><br>Python 3.12 • FastAPI • Pydantic • SQLAlchemy<br>PostgreSQL 16 + PostGIS • Alembic<br>rasterio • pyogrio • shapely<br>Docker Compose • Caddy • managed storage protocol", 540, 840, 390, 260, "#E7F2E8", GREEN), bold=True)
    p.box(Box("done1", "<b>Every number</b><br>Evidence key • source/version • scope • unit • denominator<br><br><b>Every job</b><br>Idempotency • lease/fence • trace • typed failure<br><br><b>Every route</b><br>x-grp-access • CSRF where mutating • fail-closed Hub scope", 1110, 830, 410, 300, "#FFF4D6", AMBER), bold=True)
    p.box(Box("done2", "<b>Never</b><br>LLM SQL/filesystem access<br>arbitrary MCP calls<br>preview PNG as assessment input<br>NoData interpreted without DEP-05<br>candidate called safe<br>invented capacity/population/cost/ROI<br>private Hub evidence sent to SIG", 1570, 830, 400, 300, "#FBE5E5", RED), bold=True)
    return p


def build() -> Path:
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": "2026-09-20T00:00:00.000Z",
            "agent": "ADPC GRP architecture generator",
            "version": "24.7.17",
            "type": "device",
            "compressed": "false",
        },
    )
    for page in [context_page(), agent_page(), data_page(), deployment_page(), roadmap_page()]:
        mxfile.append(page.diagram)
    ET.indent(mxfile, space="  ")
    OUTPUT.write_text(ET.tostring(mxfile, encoding="unicode", xml_declaration=True), encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    print(build())
