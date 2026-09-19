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
        "SERVIR Global Risk Platform — Local data-library implementation — 19 September 2026"
    )


def add_diagram(document: Document, path: Path, caption: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run().add_picture(str(path), width=Inches(6.8))
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

    document = Document()
    configure(document)
    document.core_properties.title = "GRP local data-library implementation and backlog"
    document.core_properties.subject = (
        "Local GIS data handling, validation, architecture and delivery plan"
    )
    document.core_properties.author = "ADPC GRP project"

    title = document.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("GRP local data library\nImplementation, verification and backlog")
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        "Detailed technical handover • 19 September 2026 • Branch codex/sig-embedded-flood-map"
    )
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor.from_string(BLUE)
    document.add_paragraph()
    add_callout(
        document,
        "Current position",
        "The accepted Data Science delivery is visible in Source data and District preview. The data-library schema and safe import-job foundation are implemented and migrated locally. No baseline files have been promoted into the managed data library yet, and no real flood assessment is enabled.",
        LIGHT_GREEN,
    )

    document.add_heading("1. Executive summary", level=1)
    document.add_paragraph(
        "GRP will keep a versioned platform baseline and allow a Hub to replace selected categories with reviewed local versions. SIG remains an optional screening and evidence service; GRP remains the authority for deterministic GIS assessments and immutable results. The first implementation imports known files already mounted read-only on Docker Desktop. It deliberately avoids re-uploading 2.1 GB through a browser and excludes the large vulnerability rasters."
    )
    add_bullets(
        document,
        [
            "Baseline now: Thailand district boundaries, DDPM shelters and six RP100 flood-depth tiles.",
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
                "Migration 0008",
                "Built and applied",
                "Adds readiness, import jobs, manifests, boundary collection links and Hub selections.",
            ],
            [
                "Import-job controls",
                "Foundation built",
                "Idempotent request, renewable lease, fencing attempt and one-time finalization.",
            ],
            [
                "Managed staging and loaders",
                "Next",
                "No baseline version is promoted until this is complete.",
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
    document.add_heading("5.1 Migration 0008 implemented so far", level=2)
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
        ],
    )
    document.add_heading("5.2 Required next database behavior", level=2)
    add_bullets(
        document,
        [
            "PostGIS geometry and spatial indexes for full and simplified boundary geometry.",
            "Job-scoped staging tables or equivalent non-selectable staging records.",
            "Atomic selection update with one current Hub/category/scenario binding.",
            "Method compatibility records for category, hazard, return period, units, required fields and NoData policy.",
            "PostgreSQL concurrency test proving that two workers cannot promote one import twice.",
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
                "One logical version in waiting-for-method state.",
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
                "Explicit release step; migration 0008 tested from empty PostGIS.",
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
                "Leave import page, receive completion, inspect findings, verify persistence after container rebuild.",
            ],
            [
                "Recovery",
                "Restore database and managed storage together and reopen an old pinned result.",
            ],
        ],
    )
    document.add_paragraph(
        "Current automated status at publication: 269 tests pass, Ruff passes, migration 0008 succeeds on a fresh PostGIS 16 database, and the local Docker database is at migration head with a green health endpoint."
    )

    document.add_heading("12. Ordered implementation backlog", level=1)
    add_table(
        document,
        ["Order", "Work item", "Completion condition"],
        [
            ["1", "Data model and migration", "Done: migration 0008 and domain records exist."],
            [
                "2",
                "Safe import queue",
                "Foundation done; add PostgreSQL two-worker processor test.",
            ],
            [
                "3",
                "Managed staging and atomic promotion",
                "Failure leaves no selectable version or orphaned final key.",
            ],
            [
                "4",
                "Boundary collection loader",
                "All 928 imported with provenance; reviewed subset marked supported.",
            ],
            [
                "5",
                "Shelter loader",
                "10,303 points imported; geometric membership and 1,139 mismatch report reproduced.",
            ],
            [
                "6",
                "RP100 logical manifest",
                "Six checksummed tiles appear as one waiting-for-method version.",
            ],
            [
                "7",
                "Data library API",
                "Admin-only import/status/accept/read routes pass permission matrix.",
            ],
            [
                "8",
                "Data library UI",
                "Admin starts baseline import and receives cross-page completion notice.",
            ],
            [
                "9",
                "Docker acceptance",
                "Data persists across rebuild; measured time, memory and disk recorded.",
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
            "docs/thailand-dataset-inventory.md",
            "docs/thailand-dataset-ingestion-plan.md",
            "docs/dataset-proof-results.md",
            "docs/backlog.md and handovers.md",
        ],
    )

    document.add_section(WD_SECTION.NEW_PAGE)
    document.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    build()
