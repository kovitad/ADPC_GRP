# ruff: noqa: E501
"""Build the detailed Word handover for the local GRP data-library implementation.

This documentation utility is not part of the GRP runtime. Install python-docx to regenerate it:
    python -m pip install python-docx
    python tools/build_data_library_design_doc.py
Graphviz `dot` must be available for the embedded diagrams.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
OUTPUT = DOCS / "GRP_Local_Data_Library_Implementation_and_Backlog.docx"
BLUE = "1769AA"
NAVY = "17365D"
GREEN = "4E8A57"
LIGHT_BLUE = "DCEAF7"
LIGHT_GREEN = "E7F2E8"
LIGHT_GREY = "EEF1F4"


def render_dot(name: str, source: str) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    dot_path = ASSETS / f"{name}.dot"
    png_path = ASSETS / f"{name}.png"
    dot_path.write_text(source, encoding="utf-8")
    subprocess.run(
        ["dot", "-Tpng", "-Gdpi=160", str(dot_path), "-o", str(png_path)],
        check=True,
    )
    dot_path.unlink()
    return png_path


def shade(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    element = OxmlElement("w:shd")
    element.set(qn("w:fill"), fill)
    properties.append(element)


def set_cell_text(cell, text: str, *, bold: bool = False, color: str | None = None) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run(text)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def add_table(document: Document, headers: list[str], rows: list[list[str]], widths=None) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = True
    for index, header in enumerate(headers):
        set_cell_text(table.rows[0].cells[index], header, bold=True, color="FFFFFF")
        shade(table.rows[0].cells[index], NAVY)
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for index, value in enumerate(values):
            set_cell_text(cells[index], str(value))
            if row_index % 2:
                shade(cells[index], "F6F8FA")
            if widths:
                cells[index].width = Inches(widths[index])
    document.add_paragraph()


def add_bullets(document: Document, items: list[str], level: int = 0) -> None:
    style = "List Bullet" if level == 0 else "List Bullet 2"
    for item in items:
        document.add_paragraph(item, style=style)


def add_numbered(document: Document, items: list[str]) -> None:
    for item in items:
        document.add_paragraph(item, style="List Number")


def add_callout(document: Document, title: str, text: str, fill: str = LIGHT_BLUE) -> None:
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    shade(table.cell(0, 0), fill)
    paragraph = table.cell(0, 0).paragraphs[0]
    run = paragraph.add_run(f"{title}: ")
    run.bold = True
    paragraph.add_run(text)
    document.add_paragraph()


def configure(document: Document) -> None:
    section = document.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.72)
    section.right_margin = Inches(0.72)
    styles = document.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(9.5)
    styles["Normal"].paragraph_format.space_after = Pt(5)
    for name, size, color in (
        ("Title", 28, NAVY),
        ("Heading 1", 18, NAVY),
        ("Heading 2", 13, BLUE),
        ("Heading 3", 11, GREEN),
    ):
        styles[name].font.name = "Aptos Display"
        styles[name].font.size = Pt(size)
        styles[name].font.color.rgb = RGBColor.from_string(color)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(
        "SERVIR Global Risk Platform — Evacuation decision and data architecture — 20 September 2026"
    )


def add_diagram(document: Document, path: Path, caption: str, *, width: float = 6.8) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run().add_picture(str(path), width=Inches(width))
    caption_p = document.add_paragraph(caption)
    caption_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_p.style = "Caption"


def build() -> None:
    architecture = render_dot(
        "data-library-local-architecture",
        r"""digraph G {
          graph [rankdir=LR, bgcolor="white", pad=0.2, nodesep=0.45, ranksep=0.65];
          node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10, color="#1769AA", fillcolor="#F5F9FD"];
          edge [fontname="Arial", fontsize=9, color="#4B6478"];
          subgraph cluster_host { label="Docker Desktop / later Ubuntu VM"; color="#AFC9DF"; style="rounded";
            web [label="Static web UI\nData library / Planning", fillcolor="#DCEAF7"];
            api [label="FastAPI\nAuth, permissions, queue, reads"];
            db [shape=cylinder, label="PostgreSQL + PostGIS\nMetadata, versions, jobs, vectors", fillcolor="#E7F2E8", color="#4E8A57"];
            worker [label="Import / GIS worker\nValidation, conversion, assessment", fillcolor="#FFF4D6", color="#C48A00"];
            store [shape=folder, label="Persistent managed storage\nOriginals, manifests, COGs, previews", fillcolor="#E7F2E8", color="#4E8A57"];
            web -> api [label="HTTPS / JSON"];
            api -> db [label="transactions"];
            db -> worker [label="leased jobs"];
            worker -> db [label="atomic promotion"];
            worker -> store [label="generated keys"];
          }
          source [shape=folder, label=".local/data-in\nAccepted source, read-only", fillcolor="#EEF1F4", color="#666666"];
          sig [label="SIG MCP\nOptional screening and receipts", fillcolor="#F0E8F7", color="#704A8E"];
          source -> worker [label="fingerprint + copy"];
          api -> sig [label="screening"];
          db -> sig [label="approved result fields only\n(no raw data)", style=dashed];
        }""",
    )
    workflow = render_dot(
        "data-library-import-workflow",
        r"""digraph G {
          graph [rankdir=TB, bgcolor="white", pad=0.2, nodesep=0.28, ranksep=0.38];
          node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10, color="#1769AA", fillcolor="#F5F9FD"];
          edge [fontname="Arial", fontsize=9, color="#4B6478"];
          select [label="Admin selects a known baseline category"];
          queue [label="API creates idempotent queued job"];
          claim [label="Worker claims lease + fencing attempt"];
          stage [label="Copy to job staging\nRecompute SHA-256"];
          validate [shape=diamond, label="All technical and\ncategory checks pass?", fillcolor="#FFF4D6", color="#C48A00"];
          fail [label="Needs correction\nSafe findings; nothing selectable", fillcolor="#FBE5E5", color="#B33A3A"];
          promote [label="Atomic promotion\nImmutable version + file manifest", fillcolor="#E7F2E8", color="#4E8A57"];
          ready [shape=diamond, label="Method compatible?", fillcolor="#FFF4D6", color="#C48A00"];
          waiting [label="Waiting for method\nFlood waits for DEP-05", fillcolor="#FFF4D6", color="#C48A00"];
          usable [label="Assessment-ready\nVisible exact version", fillcolor="#E7F2E8", color="#4E8A57"];
          select -> queue -> claim -> stage -> validate;
          validate -> fail [label="No"];
          validate -> promote [label="Yes"];
          promote -> ready;
          ready -> waiting [label="No"];
          ready -> usable [label="Yes"];
        }""",
    )
    data_model = render_dot(
        "data-library-database-model",
        r"""digraph G {
          graph [rankdir=LR, bgcolor="white", pad=0.2, nodesep=0.45, ranksep=0.65];
          node [shape=record, style="filled", fontname="Arial", fontsize=9, color="#1769AA", fillcolor="#F5F9FD"];
          edge [color="#4B6478", arrowsize=0.7];
          hub [label="{hub|id\lcode\lstatus\l}"];
          dataset [label="{dataset|id\lhub_id nullable\ltype\lowner_kind\lprovider\l}"];
          version [label="{dataset_version|id\ldataset_id\lreadiness\lsha256\lreturn_period\lis_current\limporter_version\l}", fillcolor="#E7F2E8", color="#4E8A57"];
          file [label="{dataset_file|version_id\lrole\lstorage_key\lsha256\lsize_bytes\l}"];
          importjob [label="{data_import_job|hub_id\lcategory\lstate/progress\lattempt/lease\lmanifest/report\lversion_id\l}", fillcolor="#FFF4D6", color="#C48A00"];
          selection [label="{hub_dataset_selection|hub_id\lcategory\lscenario_key\lversion_id\lselected_by\l}"];
          boundary [label="{boundary|admin_code\lcollection_version_id\lgeometry/checksum\lis_supported\l}"];
          feature [label="{feature|dataset_version_id\lname\llon/lat\lattributes\l}"];
          assessment [label="{assessment|hub_id\lboundary_id\lmethod_id\lpinned inputs\lstate/result\l}"];
          hub -> dataset;
          dataset -> version;
          version -> file;
          importjob -> version;
          hub -> selection;
          selection -> version;
          version -> boundary;
          version -> feature;
          boundary -> assessment;
          version -> assessment [label=" pinned"];
        }""",
    )

    agent_context = render_dot(
        "evacuation-agent-system-context",
        r"""digraph G {
          graph [rankdir=LR, bgcolor="white", pad=0.2, nodesep=0.35, ranksep=0.55];
          node [shape=box, style="rounded,filled", fontname="Arial", fontsize=9, color="#1769AA", fillcolor="#F5F9FD"];
          edge [fontname="Arial", fontsize=8, color="#4B6478"];
          planner [label="Planner / Hub reviewer\nConfirm AOI + scenario\nReview candidates and gaps", fillcolor="#DCEAF7"];
          subgraph cluster_grp { label="ADPC GRP trust boundary"; color="#1769AA"; style="rounded";
            web [label="Planning web\nPurpose, AOI, coverage, map"];
            api [label="FastAPI\nAuth, Hub policy, typed APIs"];
            orch [label="Bounded decision orchestrator\nFixed task plan + tool budgets", fillcolor="#FFF4D6", color="#C48A00"];
            local [label="Local evidence tools\nCatalog, PostGIS, locked results", fillcolor="#E7F2E8", color="#4E8A57"];
            queue [label="PostgreSQL leased queues\nAssessment / package / export", fillcolor="#FFF4D6", color="#C48A00"];
            workers [label="GIS + evidence + export workers", fillcolor="#FFF4D6", color="#C48A00"];
            db [shape=cylinder, label="PostgreSQL + PostGIS\nVersions, jobs, results, revisions", fillcolor="#E7F2E8", color="#4E8A57"];
            store [shape=folder, label="Managed storage\nCOGs, previews, private exports", fillcolor="#E7F2E8", color="#4E8A57"];
            aigw [label="AI gateway\nAllowance + usage + trace", fillcolor="#F0E8F7", color="#704A8E"];
            web -> api -> orch;
            orch -> local;
            local -> db;
            orch -> queue;
            queue -> workers;
            workers -> db;
            workers -> store;
            orch -> aigw [label="validated envelope"];
          }
          subgraph cluster_sig { label="SIG trust boundary"; color="#704A8E"; style="rounded";
            mcp [label="SIG MCP screening pack", fillcolor="#F0E8F7", color="#704A8E"];
            gate [label="Grounding gate", fillcolor="#F0E8F7", color="#704A8E"];
            receipt [label="Receipt-bound map", fillcolor="#F0E8F7", color="#704A8E"];
            mcp -> gate -> receipt;
          }
          planner -> web;
          orch -> mcp [label="only if complementary"];
          planner -> gate [label="explicit publish", style=dashed];
        }""",
    )
    agent_flow = render_dot(
        "evacuation-bounded-agent-flow",
        r"""digraph G {
          graph [rankdir=TB, bgcolor="white", pad=0.2, nodesep=0.25, ranksep=0.35];
          node [shape=box, style="rounded,filled", fontname="Arial", fontsize=9, color="#1769AA", fillcolor="#F5F9FD"];
          edge [fontname="Arial", fontsize=8, color="#4B6478"];
          q [label="Planner question / purpose"];
          auth [label="Session, role, Hub, allowance"];
          route [label="Intent proposal\n(enum + slots only)", fillcolor="#F0E8F7", color="#704A8E"];
          aoi [shape=diamond, label="AOI uniquely confirmed?", fillcolor="#FFF4D6", color="#C48A00"];
          ask [label="Ask planner to confirm"];
          cover [label="Evidence coverage matrix\navailable / partial / missing / blocked", fillcolor="#E7F2E8", color="#4E8A57"];
          plan [label="Deterministic task plan\nallow-listed tools + budgets", fillcolor="#FFF4D6", color="#C48A00"];
          local [label="Local branch\nlocked result or queued GIS job", fillcolor="#E7F2E8", color="#4E8A57"];
          sig [label="SIG branch\nMCP screening with timeout", fillcolor="#F0E8F7", color="#704A8E"];
          gaps [label="Typed gaps\nreadiness / missing / timeout / refusal", fillcolor="#FBE5E5", color="#B33A3A"];
          env [label="Typed evidence envelope\nfacts + scope + versions + units + disclosure", fillcolor="#FFF4D6", color="#C48A00"];
          valid [label="Schema + provenance + privacy checks"];
          compose [label="LLM composes cited draft only", fillcolor="#F0E8F7", color="#704A8E"];
          claims [label="Deterministic citation / claim checks"];
          rev [label="Immutable package revision\nreview → private export / explicit receipt", fillcolor="#E7F2E8", color="#4E8A57"];
          q -> auth -> route -> aoi;
          aoi -> ask [label="No"];
          aoi -> cover [label="Yes"];
          cover -> plan;
          plan -> local [label="if needed"];
          plan -> sig [label="if needed"];
          plan -> gaps [label="blocked"];
          local -> env;
          sig -> env;
          gaps -> env;
          env -> valid -> compose -> claims -> rev;
        }""",
    )
    decision_data = render_dot(
        "evacuation-decision-data-model",
        r"""digraph G {
          graph [rankdir=LR, bgcolor="white", pad=0.2, nodesep=0.3, ranksep=0.5];
          node [shape=record, style="filled", fontname="Arial", fontsize=8, color="#1769AA", fillcolor="#F5F9FD"];
          edge [fontname="Arial", fontsize=8, color="#4B6478", arrowsize=0.7];
          version [label="{dataset_version|readiness + checksum\lscenario + provenance\l}", fillcolor="#E7F2E8", color="#4E8A57"];
          boundary [label="{boundary|admin level + code\lparent + PostGIS geometry\l}"];
          method [label="{method|version + requirements\lreason codes\l}"];
          assessment [label="{assessment|Hub + boundary + method\lpinned versions + result\l}", fillcolor="#E7F2E8", color="#4E8A57"];
          af [label="{assessment_feature|centre status + reason\ldepth + approved metrics\l}"];
          package [label="{decision_package|Hub + creator + AOI\lpurpose + scenario + state\l}", fillcolor="#FFF4D6", color="#C48A00"];
          revision [label="{decision_package_revision|immutable envelope + narrative hashes\lassessment link + sharing state\l}", fillcolor="#FFF4D6", color="#C48A00"];
          evidence [label="{evidence_item|source/ref + scope\lunit + denominator + readiness\ldisclosure + checksum\l}"];
          gap [label="{evidence_gap|dimension + status + reason\lblocking + required owner\l}", fillcolor="#FBE5E5", color="#B33A3A"];
          intervention [label="{intervention_option|approved category + rationale\levidence keys + reviewed cost\l}"];
          export [label="{package_export|leased state + template\lprivate managed output\l}"];
          sig [label="{normalized SIG evidence|approved fields + citations only\l}", fillcolor="#F0E8F7", color="#704A8E"];
          version -> boundary;
          version -> assessment [label="pins"];
          boundary -> assessment;
          method -> assessment;
          assessment -> af;
          boundary -> package;
          package -> revision;
          assessment -> revision [label="optional locked result"];
          revision -> evidence;
          revision -> gap;
          revision -> intervention;
          revision -> export;
          version -> evidence [label="provenance"];
          af -> evidence [label="result facts"];
          sig -> evidence [label="normalizes"];
        }""",
    )
    vm_deployment = render_dot(
        "evacuation-ubuntu-vm-deployment",
        r"""digraph G {
          graph [rankdir=LR, bgcolor="white", pad=0.2, nodesep=0.35, ranksep=0.55];
          node [shape=box, style="rounded,filled", fontname="Arial", fontsize=9, color="#1769AA", fillcolor="#F5F9FD"];
          edge [fontname="Arial", fontsize=8, color="#4B6478"];
          browser [label="Planner browser"];
          servir [label="SERVIR OIDC / SIG MCP", fillcolor="#F0E8F7", color="#704A8E"];
          llm [label="LLM + Langfuse", fillcolor="#F0E8F7", color="#704A8E"];
          subgraph cluster_vm { label="Current Ubuntu VM /srv/grp"; color="#1769AA"; style="rounded";
            caddy [label="Host Caddy\nTLS + static web + /api proxy"];
            api [label="grp-api container\n127.0.0.1:8000\nread-only root"];
            worker [label="grp-worker container\nassessment/import now\npackage/export next", fillcolor="#FFF4D6", color="#C48A00"];
            db [shape=cylinder, label="PostGIS 16\nDocker named volume grp_db", fillcolor="#E7F2E8", color="#4E8A57"];
            data [shape=folder, label="/srv/grp/data\nUID 10001 / mode 0750\nmanaged files + exports", fillcolor="#E7F2E8", color="#4E8A57"];
            secrets [shape=folder, label="/srv/grp/secrets\nroot:root / mode 0600", fillcolor="#FBE5E5", color="#B33A3A"];
            releases [shape=folder, label="/srv/grp/app + releases\ncheckout/image + manifests"];
            caddy -> api [label="loopback"];
            api -> db;
            db -> worker [label="leased jobs"];
            worker -> data;
            api -> secrets [style=dashed];
            worker -> secrets [style=dashed];
            releases -> caddy [label="static web"];
          }
          browser -> caddy [label="HTTPS 443"];
          api -> servir [label="OIDC / MCP"];
          api -> llm [label="AI gateway"];
        }""",
    )

    document = Document()
    configure(document)
    document.core_properties.title = "GRP evacuation decision, AI-agent and data architecture"
    document.core_properties.subject = (
        "Evacuation preparedness decisions, bounded AI orchestration, local GIS data and VM deployment"
    )
    document.core_properties.author = "ADPC GRP project"

    title = document.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("GRP evacuation preparedness platform\nAI-agent, data, implementation and deployment architecture")
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        "Detailed technical handover • 20 September 2026 • Branch codex/sig-embedded-flood-map"
    )
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor.from_string(BLUE)
    document.add_paragraph()
    add_callout(
        document,
        "Current position",
        "The accepted Data Science delivery is visible in Source data, District preview, Data library and the Planning map. Managed staging, immutable manifests, fenced publication, 928 district boundaries, 10,303 DDPM evacuation centres and RP100 are implemented. ADR-0013 now makes the primary output an Evacuation Preparedness Decision Package: candidate movement options plus a traceable investment case. Real classification remains blocked by DEP-05; vulnerability, route, capacity and costs require approved sources and methods.",
        LIGHT_GREEN,
    )

    document.add_heading("1. Executive summary", level=1)
    document.add_paragraph(
        "GRP will keep a versioned platform baseline and allow a Hub to replace selected categories with reviewed local versions. SIG remains an optional screening and evidence service; GRP remains the authority for deterministic GIS assessments and immutable results. The first implementation imports known files already mounted read-only on Docker Desktop. It deliberately avoids re-uploading 2.1 GB through a browser and excludes the large vulnerability rasters."
    )
    add_bullets(
        document,
        [
            "Baseline now: 928 Thailand district boundaries, 10,303 DDPM shelters and six RP100 flood-depth tiles as one managed version.",
            "Deferred: child, elderly and disability vulnerability rasters; process separately on the deployment VM.",
            "Hub overrides are Hub-level accepted versions, not hidden per-user defaults.",
            "Every assessment pins exact IDs and checksums; replacements never change old results.",
            "Hub-local assessments remain private and are not eligible for SIG under the current policy.",
        ],
    )

    document.add_heading("2. Scope and status", level=1)
    add_table(
        document,
        ["Capability", "Status", "Meaning"],
        [
            [
                "Source data inspector",
                "Built",
                "Reads the delivered folder through a worker and reports blockers, problems and known setup work.",
            ],
            [
                "District preview",
                "Built",
                "Shows a district boundary, shelters and RP100 pixels without classifying shelters.",
            ],
            [
                "Data-library design",
                "Approved locally",
                "ADR-0008 authorizes the bounded Docker Desktop baseline implementation.",
            ],
            [
                "Migrations 0008–0010",
                "Built and tested",
                "Adds jobs, manifests, Hub selections, boundary lineage, indexed boundary geometry and shelter point membership.",
            ],
            [
                "Import-job controls",
                "Foundation built",
                "Idempotent request, renewable lease, fencing attempt and one-time finalization.",
            ],
            [
                "Managed baseline loaders",
                "Built and integration-tested",
                "Publishes 928 boundaries, 10,303 shelters and one six-tile RP100 version with immutable originals, COGs and a map preview.",
            ],
            [
                "Planning map controls",
                "Built for local validation",
                "Preview flood depth is opt-in. RP20/RP50 are disabled until imported; RP100 is available. A completed assessment opens its pinned red-tone flood picture and in-scope centres.",
            ],
            [
                "Real flood assessment",
                "Blocked",
                "DEP-05 must define NoData, modelled-area and permanent-water rules.",
            ],
            [
                "Vulnerability",
                "Deferred",
                "VM conversion plus DEP-07 scientific definition required.",
            ],
        ],
    )
    add_callout(
        document,
        "Important",
        "Accepted source data is not automatically assessment-ready. Technical validation, source acceptance, method compatibility and assessment readiness are separate states.",
    )

    document.add_heading("3. Local architecture", level=1)
    add_diagram(
        document,
        architecture,
        "Figure 1 — Local Docker Desktop architecture and the SIG trust boundary",
    )
    document.add_paragraph(
        "The source mount is read-only. A worker copies accepted files into generated keys under the persistent managed volume. Database and file storage must be restored as one coordinated version. Containers may be rebuilt without deleting imported versions."
    )

    document.add_heading("4. Import and verification workflow", level=1)
    add_diagram(document, workflow, "Figure 2 — Import state, validation and readiness flow")
    add_numbered(
        document,
        [
            "An Admin selects a known category from the accepted source folder.",
            "The API authorizes the Hub and creates one idempotent queued job in under one second.",
            "The import worker claims the job with a lease and attempt number. The attempt is a fencing token.",
            "The worker copies to job staging, recomputes checksums and renews the lease during long processing.",
            "GIS validation runs only in the worker. The API never imports rasterio, pyogrio or shapely.",
            "All records and files remain job-scoped until counts, geometry, manifests and invariants pass.",
            "One transaction promotes the immutable version. A failed or stale worker cannot expose a partial version.",
            "The shared top-bar job tracker notifies the Admin of success or a safe failure report.",
        ],
    )

    document.add_heading("5. Database design", level=1)
    add_diagram(document, data_model, "Figure 3 — Data-library records and assessment pinning")
    document.add_heading("5.1 Migrations 0008–0010 implemented so far", level=2)
    add_table(
        document,
        ["Record", "Purpose", "Important controls"],
        [
            [
                "data_import_job",
                "Queued import lifecycle",
                "Idempotency, state, progress, attempt, lease, manifest, safe report and promoted version.",
            ],
            [
                "dataset_file",
                "Immutable multi-file manifest",
                "Generated storage key, role, original name, size and SHA-256.",
            ],
            [
                "hub_dataset_selection",
                "Visible Hub default",
                "Unique Hub/category/scenario selection; avoids hidden personal defaults.",
            ],
            [
                "dataset_version readiness",
                "Separates technical and scientific state",
                "Eight explicit states from received through assessment-ready and retired.",
            ],
            [
                "boundary collection_version_id",
                "Pins boundary lineage",
                "Boundary feature points back to the immutable collection version.",
            ],
            [
                "feature boundary_id and geom_postgis",
                "Pins geometric shelter membership",
                "Every imported shelter points to the containing district and has an indexed EPSG:4326 point.",
            ],
        ],
    )
    document.add_heading("5.2 Required next database behavior", level=2)
    add_bullets(
        document,
        [
            "Import accepted RP20 and RP50 source versions before their Planning map options can become enabled.",
            "Atomic selection update with one current Hub/category/scenario binding.",
            "Method compatibility records for category, hazard, return period, units, required fields and NoData policy.",
            "Viewport or vector-tile delivery if measured browser performance makes the 10,303-point local preview unsuitable for staging.",
            "Shared cache/state before deploying more than one API process.",
        ],
    )

    document.add_heading("6. Category-specific checks", level=1)
    add_table(
        document,
        ["Category", "Selected files", "Checks", "Result after local import"],
        [
            [
                "District boundaries",
                "Same-stem SHP, SHX, DBF, PRJ; optional CPG",
                "Polygon type, EPSG:4326, ADMIN_ID2 uniqueness, Thai/English names, VERSION, valid geometry.",
                "Technically valid collection; only reviewed districts become supported.",
            ],
            [
                "Evacuation shelters",
                "Same-stem SHP, SHX, DBF, PRJ; optional CPG",
                "Point type, EPSG:4326, coordinate validity, safe name field, geometry-based district membership, mismatch report.",
                "Technically valid features; uncertain fields remain hidden.",
            ],
            [
                "RP100 flood",
                "Six TIF files",
                "One scenario, stable ordering, checksum, CRS, resolution, bounds, overlap/gaps, NoData and value range.",
                "One logical RP100 version in waiting-for-method state; RP20/RP50 unavailable. Importer v2 produces a sequential red depth display product.",
            ],
            [
                "Vulnerability",
                "Not selected locally",
                "Later VM script checks CRS, dimensions, values, NoData and declared population group using windowed reads.",
                "Visible as deferred; unavailable to assessments.",
            ],
        ],
    )

    document.add_heading("7. Storage and integrity", level=1)
    document.add_paragraph("Proposed managed layout:")
    paragraph = document.add_paragraph()
    paragraph.style = "No Spacing"
    run = paragraph.add_run(
        ".local/data-in/                    read-only source\n"
        "/srv/grp/data/imports/<job-id>/    quarantine and staging\n"
        "/srv/grp/data/datasets/<dataset>/<version>/manifest.json\n"
        "/srv/grp/data/datasets/<dataset>/<version>/original/...\n"
        "/srv/grp/data/datasets/<dataset>/<version>/working/..."
    )
    run.font.name = "Consolas"
    run.font.size = Pt(8.5)
    add_bullets(
        document,
        [
            "Never write to `.local/data-in` and never put source data into Git or the Docker image.",
            "Every accepted file has a full SHA-256; large source-folder inspection fingerprints are not sufficient for promotion.",
            "Storage keys are generated and opaque; user filenames are metadata only.",
            "A replacement creates a new version and new manifest. Old versions remain available to old assessment results.",
            "Database backup and file/object-storage backup must share a release/backup manifest.",
        ],
    )

    document.add_heading("8. Technology stack", level=1)
    add_table(
        document,
        ["Concern", "Current/recommended technology", "Reason and scale recommendation"],
        [
            [
                "API",
                "Python 3.12 and FastAPI",
                "Typed protected routes, current application boundary; add replicas only after shared state.",
            ],
            [
                "Metadata and jobs",
                "PostgreSQL 16",
                "Transactional versions, permissions and leased queues.",
            ],
            [
                "Spatial vectors",
                "PostGIS",
                "Indexed boundaries and shelter points; no embedding database required.",
            ],
            [
                "GIS processing",
                "rasterio, pyogrio and shapely in workers",
                "Windowed deterministic processing outside web requests.",
            ],
            [
                "Raster storage",
                "Original GeoTIFF plus COG working copy",
                "Efficient windows and overviews; add TiTiler only for measured national browsing.",
            ],
            [
                "File storage",
                "Local persistent storage protocol",
                "Appropriate locally; move to S3-compatible storage before multiple hosts.",
            ],
            [
                "Queue",
                "PostgreSQL SKIP LOCKED with leases",
                "Simple pilot operations; separate job classes before adding brokers.",
            ],
            [
                "Frontend",
                "Static HTML/CSS/JavaScript and Leaflet",
                "No build pipeline; existing shared job notifications.",
            ],
            [
                "Migrations",
                "Alembic, forward only",
                "Explicit release step; migrations 0008–0010 tested and local database upgraded through shelter point geometry.",
            ],
            [
                "External evidence",
                "SIG MCP",
                "Optional screening and receipts; never raw Hub data.",
            ],
        ],
    )

    document.add_heading("9. Local Docker resource recommendations", level=1)
    add_table(
        document,
        ["Control", "Recommendation"],
        [
            [
                "Worker concurrency",
                "One import worker locally; separate assessment/import job classes.",
            ],
            [
                "Raster processing",
                "One conversion at a time, block/window reads, never a full raster array.",
            ],
            ["GDAL cache", "256–512 MB."],
            [
                "Temporary disk",
                "Keep at least 10 GB free for this baseline; measure actual high-water mark.",
            ],
            ["Flood", "Six source files total about 113 MB and are practical locally."],
            [
                "Vulnerability",
                "Do not process locally in this slice; each compressed file is about 600 MB but expands to billions of pixels.",
            ],
            [
                "Docker cleanup",
                "Build cache may be pruned when disk is tight; never delete the GRP data or database volumes.",
            ],
            [
                "Package downloads",
                "Container pip uses a 300-second read timeout and ten retries because GIS wheels are large and the local connection is variable.",
            ],
        ],
    )

    document.add_heading("10. Security and governance", level=1)
    add_bullets(
        document,
        [
            "Platform Admin manages platform baseline versions; Hub Admin manages Hub-local candidates and selections.",
            "A Planner can select assessment-ready versions but cannot import, accept, replace or retire them.",
            "Another Hub receives 404 rather than confirmation that a dataset or import exists.",
            "Hub-local input makes the resulting assessment ineligible for SIG under the current policy.",
            "No raw data, private geometry, credentials or uploads enter logs, AI prompts or SIG evidence.",
            "Browser upload is deferred until extension/count/size limits, quarantine, content sniffing, malware policy and cleanup are approved.",
            "The same Hub Admin may upload and accept during MVP only if both actions are separately audited; production can add four-eyes approval.",
        ],
    )

    document.add_heading("11. Testing and verification", level=1)
    add_table(
        document,
        ["Layer", "Required evidence"],
        [
            [
                "Fast",
                "Readiness transitions, manifests, idempotency, lease renewal, stale-worker fencing and one-time finalization.",
            ],
            [
                "Contract",
                "Every route by role; cross-Hub denial; CSRF; Appendix D errors; x-grp-access classification.",
            ],
            [
                "PostgreSQL",
                "Migration from empty, PostGIS indexes, concurrent worker claim/promotion and atomic rollback.",
            ],
            [
                "Data",
                "Independent proof-tool counts compared with imported boundaries, shelters and sampled flood values.",
            ],
            [
                "Golden",
                "Signed Chiang Yuen result when delivered; never modify expected values to satisfy CI.",
            ],
            [
                "Browser",
                "Verify compact/wrapped navigation, opt-in preview checkbox, RP20/RP50 disabled state, RP100 red depth display, and that a completed assessment opens its pinned flood and in-boundary centres.",
            ],
            [
                "Recovery",
                "Restore database and managed storage together and reopen an old pinned result.",
            ],
        ],
    )
    document.add_paragraph(
        "Current automated status at publication: 302 repository tests pass (the two PostgreSQL-only tests skip outside their database job), both PostgreSQL tests pass in Docker, Ruff passes, migration 0010 is applied locally, and real imports contain 928 boundaries, 10,303 shelter points, six RP100 originals, six COGs and one display PNG."
    )

    document.add_heading("12. Ordered implementation backlog", level=1)
    add_table(
        document,
        ["Order", "Work item", "Completion condition"],
        [
            [
                "1",
                "Data model and migration",
                "Done: migrations 0008–0010 and domain records exist.",
            ],
            [
                "2",
                "Safe import queue",
                "Done: lease fencing and two-worker PostgreSQL publication test pass.",
            ],
            [
                "3",
                "Managed staging and atomic promotion",
                "Done: verified copy, immutable manifest, deterministic retry and rollback tests pass.",
            ],
            [
                "4",
                "Boundary collection loader",
                "Done: all 928 imported locally and visible with provenance and readiness in the Admin UI.",
            ],
            [
                "5",
                "Shelter loader",
                "Done: 10,303 points imported; geometric membership and 1,139 mismatch report reproduced.",
            ],
            [
                "6",
                "RP100 logical manifest",
                "Done: six originals, six COGs and one preview appear as one waiting-for-method version.",
            ],
            [
                "7",
                "Data library API",
                "Done for boundaries, shelters and RP100: protected read/start/status, Platform Admin write and audit.",
            ],
            [
                "8",
                "Data library and Planning UI",
                "Done locally: versions, counts, readiness, progress, map preview, opt-in flood checkbox and RP20/RP50/RP100 scenario configuration.",
            ],
            [
                "9",
                "Docker acceptance",
                "Persistence, API health, import duration and disk are recorded; signed-in visual acceptance remains.",
            ],
            [
                "10",
                "DEP-05 and method",
                "Data Science rule recorded in an approved method version.",
            ],
            [
                "11",
                "Real assessment",
                "One district matches proof tool and signed golden case when available.",
            ],
            [
                "12",
                "Hub shelter override",
                "New result pins override; old result remains byte-for-byte unchanged.",
            ],
            [
                "13",
                "Browser upload",
                "Security-reviewed quarantine reuses the same worker pipeline.",
            ],
            [
                "14",
                "VM vulnerability command",
                "One-raster-at-a-time COG conversion; no assessment activation before DEP-07.",
            ],
            [
                "15",
                "SIG result connection",
                "Platform-input result only; exact numbers, private/Hub-local items return 404.",
            ],
        ],
    )

    document.add_heading("13. Plan after the baseline import", level=1)
    add_numbered(
        document,
        [
            "Resolve DEP-05: NoData meaning, modelled-area mask and permanent-water handling.",
            "Create and approve a compatible method version.",
            "Run one real district and compare it with the independent proof tool and signed golden fixture.",
            "Prove a Hub shelter override without changing any historical result.",
            "Add security-reviewed browser upload using the proven import pipeline.",
            "Run the dedicated vulnerability conversion command on the deployment VM; wait for DEP-07 before use.",
            "Build one-page and map exports from the immutable result.",
            "Implement the protected SIG assessment_ref evidence contract for eligible platform-input results.",
            "Adopt S3-compatible storage and direct multipart upload only when multiple hosts or measured sizes require them.",
            "Complete load, restore, security, monitoring and incident rehearsals before pilot deployment.",
        ],
    )

    document.add_heading("14. Open dependencies and risks", level=1)
    add_table(
        document,
        ["Item", "Owner", "Impact"],
        [
            [
                "Flood NoData/mask/permanent-water rule (DEP-05)",
                "Scientific and Data Authority",
                "Blocks a real flood classification.",
            ],
            [
                "Shelter fields สถา and รอง (DEP-06)",
                "Data Science / DDPM",
                "Fields remain hidden until confirmed.",
            ],
            [
                "Vulnerability meaning (DEP-07)",
                "Scientific and Data Authority",
                "Blocks vulnerability assessment activation.",
            ],
            [
                "Signed Chiang Yuen fixture (DEP-04)",
                "Scientific and Data Authority",
                "Blocks formal Increment 1 acceptance.",
            ],
            [
                "SIG machine identity and assessment_ref",
                "SIG platform owner",
                "Blocks governed GRP-result evidence connection.",
            ],
            [
                "Upload security policy",
                "ADPC security",
                "Blocks browser upload and server rollout.",
            ],
            [
                "Lease renewal and concurrency",
                "Engineering",
                "Must be complete before long imports.",
            ],
            ["Shared rate limits/token state", "Engineering", "Blocks multiple API replicas."],
        ],
    )

    document.add_heading("15. Operational commands", level=1)
    for command in [
        "python -m pytest",
        "python -m ruff check .",
        "docker compose -f deploy/compose.desktop.yml ps",
        "docker compose -f deploy/compose.desktop.yml run --rm --no-deps migrate python -m alembic current --check-heads",
        "curl http://127.0.0.1:8000/api/v1/healthz",
    ]:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(command)
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)
        shade_paragraph = paragraph._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), LIGHT_GREY)
        shade_paragraph.append(shd)

    document.add_heading("16. Source documents", level=1)
    add_bullets(
        document,
        [
            "docs/baseline-data-library-implementation-plan.md",
            "docs/data-library-sig-assessment-design.md",
            "docs/data-library-solution-review.md",
            "docs/adr/0007-delivered-data-acceptance.md",
            "docs/adr/0008-baseline-and-hub-data-overrides.md",
            "docs/adr/0013-decision-first-evacuation-preparedness.md",
            "docs/evacuation-decision-agent-data-architecture.md",
            "docs/GRP_Evacuation_Decision_Agent_and_Data_Architecture.drawio",
            "docs/thailand-dataset-inventory.md",
            "docs/thailand-dataset-ingestion-plan.md",
            "docs/dataset-proof-results.md",
            "docs/backlog.md and handovers.md",
        ],
    )

    document.add_heading("17. Decision-first product architecture", level=1)
    document.add_paragraph(
        "ADR-0013 changes the center of gravity from a general flood chatbot to an Evacuation Preparedness Decision Package. The package links two outcomes: evidence-backed candidate movement options for vulnerable people, and a traceable preparedness investment case. Maximum result means maximum decision completeness and provenance, not maximum model output or tool calls."
    )
    add_diagram(
        document,
        agent_context,
        "Figure 4 — System context and trust boundaries for the bounded decision agent",
    )
    add_callout(
        document,
        "Safety language",
        "A center with lower mapped flood exposure is a candidate only. GRP does not certify safety without approved capacity, building, accessibility, route, service and multi-hazard evidence.",
        "FBE5E5",
    )
    add_table(
        document,
        ["Output section", "Required evidence", "Current readiness"],
        [
            ["Movement options", "Confirmed AOI/scenario, locked flood classification, center location; later capacity/accessibility/routes", "Synthetic only; real run waits for DEP-05 and pilot approval"],
            ["Vulnerable groups", "Authoritative population/indicator source, year, unit, denominator and approved aggregation method", "Blocked on DEP-07 and source semantics"],
            ["Investment gaps", "Coverage status for hazard, centers, capacity, accessibility, routes, vulnerable groups and costs", "Coverage contract can be built now; many dimensions remain missing"],
            ["Interventions", "Approved intervention categories tied to evidence gaps", "Template design required; AI cannot invent costs"],
            ["Brief and map", "Locked package revision, approved template and private export job", "Blocked on DEP-12"],
            ["Public SIG receipt", "Reviewed public subset, signed draft token and SIG gate", "Implemented for generic screening; package contract is future"],
        ],
    )

    document.add_heading("18. Bounded AI-agent design", level=1)
    add_diagram(
        document,
        agent_flow,
        "Figure 5 — Bounded orchestration from confirmed intent to immutable package revision",
        width=5.4,
    )
    document.add_paragraph(
        "The current platform is closest to an LLM-with-tools architecture. The target adds planning across multiple approved tools but deliberately does not give the model autonomous SQL, filesystem, GIS or MCP access. The model proposes an intent and structured slots; deterministic application code authorizes and executes a fixed task plan."
    )
    add_table(
        document,
        ["Component", "Allowed", "Prohibited"],
        [
            ["Intent router", "Propose movement_options, investment_case, explain_result, sig_screening or general; extract AOI/scenario proposal", "Execute a tool, authorize access or choose authoritative data"],
            ["Policy/task planner", "Choose a fixed workflow after Hub, AOI, scenario, readiness and disclosure checks", "Accept arbitrary model-authored tool names or arguments"],
            ["Local tools", "Read managed area/catalog/readiness/locked-result facts", "Run raster GIS in an HTTP handler or activate preview-only data"],
            ["SIG adapter", "Call reviewed MCP contracts with confirmed place and bounded question class", "Send raw/private Hub files or treat screening as a GRP result"],
            ["LLM composer", "Explain and structure only normalized cited evidence", "Invent capacity, population, costs, routes, benefits or safety claims"],
            ["Claim checker", "Check required headings, citations and prohibited language", "Replace scientific method approval"],
            ["Human reviewer", "Review interpretation, approved assumptions, private export and explicit publication", "Turn missing evidence into a fact"],
        ],
    )
    document.add_heading("18.1 Allow-listed tool contract", level=2)
    for command in [
        "area.resolve(query, allowed_levels)",
        "area.get(area_id)",
        "coverage.build(area_id, scenario, hub_id)",
        "catalog.resolve_inputs(area_id, scenario, hub_id)",
        "assessment.get_result(assessment_id)",
        "assessment.queue(resolved_input_token)",
        "sig.screen(confirmed_place, hazard, question_class)",
        "evidence.validate(envelope)",
        "package.compose(envelope, purpose)",
        "export.queue(package_revision_id, template_id)",
        "publish.sig(package_revision_id, reviewed_draft_token)",
    ]:
        paragraph = document.add_paragraph(style="List Bullet")
        run = paragraph.add_run(command)
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)

    document.add_heading("19. Evidence contract and coverage", level=1)
    document.add_paragraph(
        "Local GRP facts and SIG screening must be normalized before drafting. Do not append local figures to an already generated SIG answer. The evidence envelope is versioned as decision-evidence-v1 and carries confirmed area geometry fingerprint, scenario, coverage, GRP results, SIG screening, planner-approved assumptions, gaps, sources and disclosure policy."
    )
    add_table(
        document,
        ["Required fact metadata", "Purpose"],
        [
            ["Evidence ID and source kind", "Stable citation and separation of locked result, catalog fact, SIG screening and planner assumption"],
            ["Source/version/reference/checksum", "Reproducibility and immutable lineage"],
            ["Area and scenario scope", "Prevents district/sub-district or return-period mixing"],
            ["Timestamp/readiness/scientific status", "Shows currency and whether evidence can drive an assessment"],
            ["Unit and denominator", "Prevents ambiguous percentages, population totals and area values"],
            ["Disclosure classification", "Controls what may enter the LLM, export or public SIG path"],
        ],
    )
    add_table(
        document,
        ["Coverage dimension", "Example current state", "Required to become available"],
        [
            ["Hazard", "RP100 display available; assessment blocked", "DEP-05, compatible accepted version and approved method"],
            ["Center location", "10,303 managed points", "Scope to confirmed boundary/result"],
            ["Center capacity", "Source field meaning unconfirmed", "Accepted mapping and validation"],
            ["Accessibility/services", "Not in planner result", "Approved fields/source and method"],
            ["Route condition", "Missing", "Approved road/network and flood-route method"],
            ["Vulnerable groups/population", "Rasters deferred", "DEP-07, authoritative denominator and aggregation"],
            ["Intervention options", "Missing", "Approved intervention catalogue"],
            ["Cost assumptions", "Missing", "Authorized entry or approved cost catalogue; never model-generated"],
        ],
    )

    document.add_heading("20. Decision-package data architecture", level=1)
    add_diagram(
        document,
        decision_data,
        "Figure 6 — Existing immutable assessment records and proposed decision-package records",
    )
    add_table(
        document,
        ["Proposed record", "Role", "Key rules"],
        [
            ["decision_package", "Mutable workflow header scoped to Hub, creator, AOI, purpose and scenario", "States draft/gathering/ready_for_review/failed/archived; cross-Hub reads return 404"],
            ["decision_package_revision", "Immutable envelope and narrative revision", "Hashes envelope and narrative; optional locked assessment; new evidence creates a new revision"],
            ["evidence_item", "Normalized citable fact or grouped result", "Schema and size limited; source/scope/unit/denominator/readiness/disclosure/checksum required"],
            ["evidence_gap", "Missing/partial/blocked decision dimension", "Typed reason, blocking flag and required owner"],
            ["intervention_option", "Approved intervention category tied to evidence", "Cost stays null until authorized or sourced from approved catalogue"],
            ["package_export", "Leased private brief/map export", "Managed storage key; never rendered in web request"],
        ],
    )
    add_callout(
        document,
        "Immutability boundary",
        "Dataset versions, successful assessments and package revisions are append-only. The workflow header may advance state; a finalized result or revision is never edited in place.",
        LIGHT_GREEN,
    )

    document.add_heading("21. Developer API and module blueprint", level=1)
    add_table(
        document,
        ["API", "Access and behavior"],
        [
            ["GET /api/v1/areas", "Protected; searchable managed district/sub-district records with parent names and eligibility reason"],
            ["POST /api/v1/assessment-config/resolve", "Protected + CSRF; deterministic selected versions, alternatives, checks and signed resolution token"],
            ["POST /api/v1/decision-packages", "Protected + CSRF + idempotency; create Hub-scoped workflow"],
            ["POST /api/v1/decision-packages/{id}/gather", "Protected + CSRF + idempotency; enqueue durable evidence/package job"],
            ["GET /api/v1/decision-packages/{id}/coverage", "Protected; decision dimensions and typed reasons"],
            ["GET /api/v1/decision-packages/{id}/events", "Protected SSE with polling fallback; real job steps"],
            ["GET /api/v1/decision-packages/{id}/revisions/{revision}", "Protected; immutable review record"],
            ["POST /api/v1/decision-packages/{id}/exports", "Protected + CSRF + idempotency; private worker export"],
            ["POST /api/v1/decision-packages/{id}/publish-sig", "Protected + CSRF; exact reviewed public subset only"],
        ],
    )
    add_table(
        document,
        ["Module", "Responsibility"],
        [
            ["core/area_catalog.py", "AOI search, ambiguity and parent resolution"],
            ["core/input_resolution.py", "Compatible platform/Hub input selection and signed resolution"],
            ["core/evidence_models.py", "Pydantic envelope, fact, source, coverage and gap contracts"],
            ["core/evidence_policy.py", "Readiness, compatibility, privacy and disclosure rules"],
            ["core/decision_package_models.py", "SQLAlchemy package/revision/evidence/gap/intervention/export records"],
            ["core/decision_package_jobs.py", "Idempotent leased gathering and finalization"],
            ["core/intervention_rules.py", "Approved categories; no generated costs"],
            ["api/areas.py, assessment_config.py, decision_packages.py", "Thin authorization/validation/enqueue/read routes"],
            ["worker/decision_package_tasks.py, export_tasks.py", "Slow evidence, composition finalization and rendering"],
            ["web/planning-area.js, planning-config.js, planning-package.js, planning-map.js", "Split the current large planning.js before adding the workflow"],
        ],
    )

    document.add_heading("22. Technology and reliability", level=1)
    add_table(
        document,
        ["Layer", "Current/recommended technology", "Scale path"],
        [
            ["Browser", "Static HTML/CSS/JavaScript, Leaflet, accessible DOM construction", "Split modules; SSE with polling fallback; vendor external assets before staging"],
            ["API", "Python 3.12, FastAPI, Pydantic, SQLAlchemy", "Replicas only after shared token/cache/rate-limit state"],
            ["Authoritative data", "PostgreSQL 16 + PostGIS, Alembic forward migrations", "Retain transactions and spatial indexes"],
            ["Jobs", "PostgreSQL SKIP LOCKED leases, idempotency and fencing", "Separate assessment/package/export queues, then add worker processes"],
            ["GIS", "rasterio, pyogrio, shapely; COG working files", "TiTiler/rio-tiler only after measured national-browsing need"],
            ["Storage", "Existing replaceable storage protocol over /srv/grp/data", "S3-compatible storage without domain changes"],
            ["AI", "Existing gateway, allowance/usage, prompt versioning and Langfuse best effort", "No direct tools; validated envelope only"],
            ["External evidence", "Reviewed SIG MCP adapter, gate and receipt", "Contract fixtures, deadlines, retries and circuit breaker"],
            ["Edge", "Host Caddy TLS, headers, static files and loopback reverse proxy", "Keep API port non-public"],
        ],
    )
    add_bullets(
        document,
        [
            "Move combined evidence/package generation to a durable leased job before calling multiple slow tools.",
            "Publish real step events with SSE; retain polling when intermediaries block streams.",
            "Give each tool a deadline, bounded retry with jitter, cancellation and a SIG circuit breaker.",
            "Cache validated SIG evidence separately from prose and never broaden cache scope without a disclosure review.",
            "Return a labelled partial package when SIG or one local dimension fails; never fabricate the missing half.",
            "Before multiple API replicas, move SIG token, answer/evidence caches and rate-limit state out of process.",
        ],
    )

    document.add_heading("23. Deployment on the current Ubuntu VM", level=1)
    add_diagram(
        document,
        vm_deployment,
        "Figure 7 — Current Ubuntu VM deployment and proposed package/export worker responsibilities",
    )
    document.add_heading("23.1 Filesystem, containers and network", level=2)
    add_table(
        document,
        ["Item", "Required state"],
        [
            ["Supported host", "Ubuntu 22.04 or 24.04 with Docker Engine/Compose plugin and host Caddy"],
            ["/srv/grp/app", "Clean deployment checkout or release metadata; non-secret .env mode 0640"],
            ["/srv/grp/data", "Container UID/GID 10001, mode 0750; managed originals, COGs, previews and private exports"],
            ["/srv/grp/secrets", "root:root 0700 directory; each secret 0600; mounted read-only"],
            ["PostGIS", "postgis/postgis:16-3.4 on internal Docker network; named volume grp_db"],
            ["API", "Read-only root, no-new-privileges, dropped capabilities; only 127.0.0.1:8000 exposed"],
            ["Worker", "Same hardened image and internal network; managed data volume; no public port"],
            ["Caddy", "Public 80/443; TLS, security headers, static web and /api reverse proxy"],
            ["Firewall", "80/443 public; SSH restricted to approved CIDRs; database/API not publicly exposed"],
        ],
    )
    document.add_heading("23.2 Preferred release procedure", level=2)
    add_numbered(
        document,
        [
            "Run tests, Ruff, JavaScript checks, migration checks, secret scan and container build in CI.",
            "Publish a versioned immutable image to GHCR; record image digest and Git revision.",
            "Back up PostgreSQL and /srv/grp/data as one recovery point; verify free disk and backup completion.",
            "Run bootstrap-ubuntu.sh in image mode for the staging domain; never copy local .env or tokens.",
            "The bootstrap validates Compose, pulls the image, starts PostGIS, runs alembic upgrade head once, then starts API and worker.",
            "Check loopback /api/v1/healthz, public TLS, sign-in, role access, worker claim, storage write and a synthetic assessment.",
            "Record the release manifest and run the full signed-in browser checklist before promoting beyond staging.",
        ],
    )
    for command in [
        "sudo /srv/grp/app/deploy/bootstrap-ubuntu.sh --deploy-mode image --image ghcr.io/kovitad/adpc_grp:<version> --domain <staging-domain> --enable-ufw --ssh-allow-cidr <approved-cidr>",
        "sudo /srv/grp/app/deploy/bootstrap-ubuntu.sh --check-only",
        "docker compose --env-file /srv/grp/app/.env -f /srv/grp/app/deploy/compose.yml ps",
        "curl --fail https://<staging-domain>/api/v1/healthz",
        "docker compose --env-file /srv/grp/app/.env -f /srv/grp/app/deploy/compose.yml logs --tail=200 api worker",
    ]:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(command)
        run.font.name = "Consolas"
        run.font.size = Pt(8.0)
        properties = paragraph._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), LIGHT_GREY)
        properties.append(shd)
    add_callout(
        document,
        "Backup warning",
        "The database contains metadata and immutable references while /srv/grp/data contains the referenced bytes. Back up and restore them consistently; test restoration on an isolated host before claiming recovery readiness.",
        "FBE5E5",
    )

    document.add_heading("24. Implementation phases and acceptance", level=1)
    add_table(
        document,
        ["Phase", "Deliverable", "Exit condition"],
        [
            ["A — contracts and honest UX", "Managed AOI API, evidence envelope, coverage matrix, input resolver and separate GRP/SIG sections", "Synthetic flow works unchanged; unsupported real areas stop with typed reasons"],
            ["B — sub-district catalogue", "7,436 managed polygons, parent links and qualified Thai/English search", "Valid geometry and deterministic parent-qualified search; unsupported cannot run"],
            ["C — durable package", "Package/revision/evidence/gap tables, leased job, SSE and partial-failure handling", "Reproducible immutable revisions; SIG timeout yields useful labelled partial output"],
            ["D — real movement screening", "DEP-05 and pilot approval, compatible input activation and real locked classifications", "Authority-approved golden district reproduces exactly"],
            ["E — vulnerability and suitability", "Approved population, capacity, accessibility, services and route dimensions", "Each number/source/method passes an approved golden case"],
            ["F — investment and comparison", "Approved intervention/cost inputs, multiple return periods and DEP-12 exports", "Private brief/map matches locked revision; no AI-created figure"],
        ],
    )
    add_bullets(
        document,
        [
            "Every number has an evidence key, source/version, scope, unit and denominator.",
            "Every route declares x-grp-access; mutating routes require CSRF and idempotency; cross-Hub IDs fail closed.",
            "Every slow job is leased, fenced, idempotent, traceable and cancellable where practical.",
            "GIS remains outside request handlers.",
            "Candidate centers are never labelled safe.",
            "Fast, contract, PostgreSQL, golden, browser and relevant load tests pass.",
        ],
    )

    document.add_heading("25. Editable architecture source", level=1)
    document.add_paragraph(
        "The editable draw.io source is docs/GRP_Evacuation_Decision_Agent_and_Data_Architecture.drawio. It contains five pages: context/trust boundaries, bounded agent workflow, data/lineage, current Ubuntu VM deployment, and implementation/technology. Regenerate it with python tools/build_agent_architecture_drawio.py. The detailed Markdown blueprint is docs/evacuation-decision-agent-data-architecture.md."
    )

    document.add_section(WD_SECTION.NEW_PAGE)
    document.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    build()
