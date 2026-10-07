const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, ShadingType, BorderStyle, ImageRun, LevelFormat, Header, Footer, PageNumber,
  PageBreak, TableOfContents,
} = require("docx");

const FONT = "Arial";
const W = 9026; // A4 content width in DXA with 1-inch margins
const BORDER = { style: BorderStyle.SINGLE, size: 4, color: "BFC5CC" };
const BORDERS = { top: BORDER, bottom: BORDER, left: BORDER, right: BORDER };

const run = (text, opts = {}) => new TextRun({ text, font: FONT, ...opts });
const p = (text, opts = {}) => new Paragraph({
  spacing: { after: 120, line: 300 }, ...opts,
  children: Array.isArray(text) ? text : [run(text)],
});
const rich = (parts, opts = {}) => p(parts.map((x) => (typeof x === "string" ? run(x) : run(x.t, x))), opts);
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [run(text)] });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [run(text)] });
const h3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [run(text)] });
const bullet = (text, level = 0) => new Paragraph({
  numbering: { reference: "bullets", level }, spacing: { after: 60, line: 288 },
  children: Array.isArray(text) ? text.map((x) => (typeof x === "string" ? run(x) : run(x.t, x))) : [run(text)],
});
const bullets = (items) => items.map((x) => bullet(x));
const numbered = (items) => items.map((x) => new Paragraph({
  numbering: { reference: "numbers", level: 0 }, spacing: { after: 60, line: 288 },
  children: typeof x === "string" ? [run(x)] : x.map((y) => (typeof y === "string" ? run(y) : run(y.t, y))),
}));

function table(header, rows, widths, opts = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cell = (text, isHead, fill) => new TableCell({
    borders: BORDERS,
    width: { size: 0, type: WidthType.DXA },
    shading: fill ? { fill, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 70, bottom: 70, left: 110, right: 110 },
    children: String(text).split("\n").map((line) => new Paragraph({
      spacing: { after: 30, line: 260 },
      children: [run(line, { bold: isHead, size: isHead ? 19 : 18, color: isHead ? "FFFFFF" : "1F2937" })],
    })),
  });
  const mk = (cells, isHead, fill) => new TableRow({
    tableHeader: isHead,
    children: cells.map((c, i) => {
      const tc = cell(c, isHead, isHead ? "1F4E79" : (opts.zebra && fill ? "F3F6F9" : undefined));
      tc.options = tc.options || {};
      return new TableCell({
        borders: BORDERS,
        width: { size: widths[i], type: WidthType.DXA },
        shading: isHead ? { fill: "1F4E79", type: ShadingType.CLEAR, color: "auto" }
          : (opts.zebra && fill ? { fill: "F3F6F9", type: ShadingType.CLEAR, color: "auto" } : undefined),
        margins: { top: 70, bottom: 70, left: 110, right: 110 },
        children: String(c).split("\n").map((line) => new Paragraph({
          spacing: { after: 30, line: 260 },
          children: [run(line, { bold: isHead, size: isHead ? 19 : 18, color: isHead ? "FFFFFF" : "1F2937" })],
        })),
      });
    }),
  });
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: [mk(header, true), ...rows.map((r, i) => mk(r, false, i % 2 === 1))],
  });
}
const gap = () => new Paragraph({ spacing: { after: 80 }, children: [] });

function callout(title, lines, fill = "EAF2FB", edge = "2E75B6") {
  return new Table({
    width: { size: W, type: WidthType.DXA },
    columnWidths: [W],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: W, type: WidthType.DXA },
      shading: { fill, type: ShadingType.CLEAR, color: "auto" },
      borders: { top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
        bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
        right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
        left: { style: BorderStyle.SINGLE, size: 24, color: edge } },
      margins: { top: 120, bottom: 120, left: 200, right: 160 },
      children: [
        new Paragraph({ spacing: { after: 80 }, children: [run(title, { bold: true, color: "1F4E79" })] }),
        ...lines.map((l) => new Paragraph({ spacing: { after: 60, line: 280 },
          children: Array.isArray(l) ? l.map((x) => (typeof x === "string" ? run(x) : run(x.t, x))) : [run(l)] })),
      ],
    })] })],
  });
}

function image(file, widthPx, heightPx, maxWidthPt = 451) {
  const scale = maxWidthPt / widthPx;
  return new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 80, after: 80 },
    children: [new ImageRun({ type: "png", data: fs.readFileSync(file),
      transformation: { width: Math.round(widthPx * scale), height: Math.round(heightPx * scale) },
      altText: { title: file, description: file, name: file } })],
  });
}
const caption = (text) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
  children: [run(text, { italics: true, size: 18, color: "4B5563" })] });

// ------------------------------------------------------------------ content
const children = [];

// Cover
children.push(
  new Paragraph({ spacing: { before: 2400, after: 200 }, children: [run("SERVIR Global Risk Platform (GRP) · ADPC", { size: 22, color: "4B5563" })] }),
  new Paragraph({ spacing: { after: 240 }, children: [run("GRP Live Flood Intelligence", { bold: true, size: 56, color: "1F4E79" })] }),
  new Paragraph({ spacing: { after: 480 }, children: [run("Live evidence, early-warning context, river outlook, consolidated reports and a history archive: why, and the proposed architecture", { size: 28, color: "374151" })] }),
  new Paragraph({ border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: "1F4E79", space: 1 } }, children: [] }),
  p([run("Proposal for the development team · Version 1.1 (draft for review) · 4 October 2026 · corrects the Bangkok DDPM shelter count", { size: 20 })], { spacing: { before: 240, after: 80 } }),
  p([run("Based on the exploratory pilot of 2–4 October 2026 (branch pilot/river-watch-and-bangkok-flood). Everything marked “built” was built and tested in that repository; everything marked “proposed” is not built.", { size: 20, color: "4B5563" })]),
  p([run("Status: for discussion. No data has been sent to Global Risk, and nothing in this document is a flood warning.", { size: 20, color: "9A3412", bold: true })]),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ spacing: { after: 200 }, children: [run("Contents", { bold: true, size: 32, color: "1F4E79" })] }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
);

// 1 Executive summary
children.push(
  h1("1. Executive summary"),
  callout("In one line", ["Turn scattered live flood signals and a free global river forecast into one evidence-backed picture that DDPM planners can use now, that planners elsewhere can query through Global Risk, and that keeps a clean history for future models and insurance products."]),
  gap(),
  p("GRP today answers pre-season questions well: which evacuation centres sit inside a 100-year flood scenario, who lives nearby, and what the national baseline holds. It could not say where flooding is happening now, what may happen in the coming days, or keep a history of real events. Over two days of exploratory work we built and tested the missing pieces for Bangkok and wrote the plans for the rest."),
  h3("What is already built and tested"),
  ...bullets([
    "Live flood evidence for all 50 Bangkok districts: incidents with a confidence word, freshness, district codes and facilities with flooding reported nearby (first whole-city run: 123 active incidents across 21 districts).",
    "The Planner now shows “Reported flooding on roads (live, not a flood map)” and answers “is it flooding now?” from computed facts, always ending with an owner-approved sentence that GRP issues no warnings.",
    "DDPM’s evacuation centres are checked for nearby flooding alongside OpenStreetMap schools, hospitals and clinics.",
    "A daily research archive keeps model-relevant history with no personal data (first day: 2.9 MB, about 30 times smaller than the raw data).",
    "A GEOGLOWS seven-day river-flow card (display only) for two exploratory reaches near Bang Bua Thong.",
  ]),
  h3("What we propose next"),
  ...bullets([
    "A live feed endpoint so Global Risk can serve Bangkok flood incidents and a 50-district summary to any MCP client, tested first as a staged (private) contribution.",
    "Consolidated reports for DDPM planners across four horizons: pre-season, days ahead, live shift and after-action.",
    "A river outlook that names affected districts, once a hydrologist confirms the reaches.",
    "Operational hardening: a public HTTPS host, archive backup, and a reviewed path towards partner and insurance use.",
  ]),
  h3("Key numbers (4 October 2026)"),
  table(["Measure", "Value"], [
    ["Bangkok districts covered", "50 (was 4)"],
    ["Active incidents, first whole-city runs", "123 across 21 districts; 145 at 06:47 UTC, all with district codes"],
    ["Facilities checked for nearby flooding", "1,067 in Bangkok (707 schools, 183 hospitals, 177 clinics). DDPM\u2019s delivery has no Bangkok evacuation centres"],
    ["Live cameras in the registry", "1,413 (view only)"],
    ["Archive size, first day", "2.9 MB (17,493 road states, 4,316 reports, 158 incidents, 2 officer labels)"],
    ["Automated tests", "1,086 passing, 2 skipped"],
  ], [4200, 4826], { zebra: true }),
);

// 2 Problem solution benefit
children.push(
  h1("2. Problem, solution and benefit"),
  p("Each row is a problem we saw in practice, what the proposal does about it, and who benefits."),
  table(["Problem", "Solution", "Benefit"], [
    ["P1. No picture of flooding now. GRP only knew the 100-year scenario.", "Ingest Floodboard’s open live exports; group evidence into incidents with a confidence word and freshness.", "Planners see where flooding is reported now, how sure we are, and how old the evidence is."],
    ["P2. Information is scattered. Sensors, citizen reports, cameras and news live in different systems; officers combine them in their heads.", "One observation model with lineage; counts independent source families once (no double counting of Traffy inside Floodboard).", "A shared, evidence-linked interpretation instead of a dozen dashboards."],
    ["P3. No days-ahead outlook.", "GEOGLOWS seven-day river-flow forecast, shown as a trend with its uncertainty band.", "Riverine provinces get an anticipatory signal days before flooding, honestly labelled."],
    ["P4. Answers can be wrong or inconsistent. A model can invent numbers; different pages can disagree.", "One computed fact bundle per area, time window and audience; AI only words the facts behind a gate that refuses unknown numbers.", "Every number is traceable and the same on the map, in answers, in reports and in the feed."],
    ["P5. Planners elsewhere cannot use what one Hub knows.", "A live feed contributed to Global Risk as a text manifest; data is pulled live through MCP.", "Regional analysts and other Hubs can ask about Bangkok flooding with evidence attached."],
    ["P6. History disappears. Retention deletes raw data after 7–14 days; models and insurers need event history.", "A daily research archive of state changes, labels and rule versions, written before retention runs.", "Data scientists can train and validate models; future partner products have a trustworthy record."],
    ["P7. Privacy and licence risk. Reports quote people; some sources forbid redistribution.", "No report text, links or names are stored or archived; each source’s licence travels with the data; restricted sources stay internal.", "Safe to share summaries; lower legal risk; easier approvals."],
    ["P8. People may treat estimates as warnings.", "Fixed wording: “reported flooding nearby”, never “flooded”; no warnings; official channels named.", "Clear responsibility: GRP supports decisions, official agencies warn."],
  ], [2900, 3263, 2863], { zebra: true }),
);

// 3 Why live data
children.push(
  h1("3. Why live data and “early-warning context”"),
  h2("3.1 What we mean"),
  p("“Early-warning context” means the evidence a planner needs in the hours and days before and during a flood: where flooding is reported now, how fast it is changing, what rain is falling, and what the rivers are expected to do. It does not mean issuing warnings. Warnings are the job of the Thai Meteorological Department (TMD), DDPM and, in Bangkok, the BMA. Every live answer in GRP ends with that statement, in fixed wording approved by the Product Owner."),
  h2("3.2 Why now"),
  ...bullets([
    "The Bangkok specification (v0.3) identifies the real gap as “lack of a shared, current, evidence-linked interpretation of what the data means for a decision”, not lack of data.",
    "Development cannot wait for rain: the pilot keeps captured data and can replay any period through the same engines.",
    "Live evidence joins directly to the national baseline: GRP and the pilot use the same administrative codes (for example Chatuchak 1030, sub-district 103005), so incidents link to DDPM shelters and population without manual matching.",
  ]),
  h2("3.3 Sources we evaluated"),
  table(["Source", "Finding", "Decision"], [
    ["Floodboard roads and reports", "Public, no key, CC BY 4.0. Road ratings for about 5,000 segments; reports from Traffy, crowd and BMA sensors; reports cover only the last ~24 hours.", "Primary live source. Captured continuously so history is kept."],
    ["BMA water levels (data.go.th)", "The dataset holds only a data dictionary; licence not specified.", "Not usable. BMA asked for access."],
    ["floodbangkok.bangkok.go.th", "No documented API.", "Not reverse-engineered."],
    ["BMA camera list, bmatraffic, iTIC/Longdo", "Camera locations and live views available; redistribution terms not given.", "View only inside GRP; permission requested from BMA; nothing redistributed."],
    ["Longdo events and rain radar", "Useful context; redistribution terms not stated.", "Context only, internal; never in public feeds."],
    ["OpenStreetMap", "Schools, hospitals, clinics; ODbL.", "Facility layer with credit."],
    ["DDPM baseline (GRP data library)", "Shelters, villages, boundaries, RP100. No Bangkok evacuation centres: the delivery names 75 provinces; 309 records nationwide have coordinates in a different province from the one recorded.", "Joined by code; read from the database, never copied into the code repository."],
  ], [2300, 3800, 2926], { zebra: true }),
);

// 4 Why GEOGLOWS
children.push(
  h1("4. Why GEOGLOWS"),
  p("GEOGLOWS publishes a free, global, daily seven-day river-discharge forecast for every modelled river reach, with an ensemble band. It is the only days-ahead source GRP holds today."),
  h2("4.1 Why it matters"),
  ...bullets([
    "It gives a days-ahead horizon that live reports cannot: rising river flow upstream of Bangkok is visible before streets flood.",
    "It covers the riverine provinces where flooding is driven by the river: the Chao Phraya, Nonthaburi (Bang Bua Thong), Pathum Thani and Ayutthaya.",
    "It is free, open and consistent across countries, so the same card works for every SERVIR Hub.",
    "Its daily summary is the easiest first live contribution to Global Risk: it changes once a day and is never empty (see section 9).",
  ]),
  h2("4.2 Honest limits"),
  table(["Limit", "Consequence"], [
    ["It models rivers, not drains. Bangkok road flooding is mostly rain and drainage.", "Never presented as forecasting Bangkok street flooding."],
    ["No “high” threshold: the upstream return-period service fails.", "Reports say rising, steady or falling; never “warning” or “above normal”. Any threshold is a scientific-method change needing an ADR and approval."],
    ["The two reaches near Bang Bua Thong came from a nearest-river lookup.", "Labelled exploratory until a hydrologist confirms reaches and the districts each affects."],
    ["Discharge is not depth.", "Depth maps (HAND, Phase B) need local terrain, a rating curve and hydraulic review."],
  ], [4300, 4726], { zebra: true }),
  h2("4.3 What GRP adds on top of GEOGLOWS"),
  p("GEOGLOWS is already global. GRP’s value is local: a confirmed map from each reach to the districts, shelters and people it affects, joined to the DDPM baseline, so a planner reads “river flow at this reach is rising; these districts and these evacuation centres lie along it”."),
);

// 5 What the pilot proved
children.push(
  h1("5. What the pilot proved"),
  table(["Capability", "Evidence", "Record"], [
    ["Floodboard evidence with lineage, freshness and replay", "Captured since 3 Oct; replay runs the same engines", "ADR-0038, 0044"],
    ["Incidents with identity and confidence words", "123 active across 21 districts on the first whole-city run", "ADR-0041, 0053"],
    ["District codes computed once in the worker", "145 of 145 active incidents coded; border incidents list both districts", "ADR-0056 step 1"],
    ["Facilities with flooding reported nearby", "1,067 OSM facilities; DDPM centres join wherever correct records fall in the area", "ADR-0040, 0056 step 4"],
    ["Planner live layer", "Lat Krabang 21 incidents, 112 roads; sub-districts roll up; outside Bangkok refused", "ADR-0056 step 2"],
    ["Planner live answers with gate and fixed no-warnings text", "Computed answer for Lat Krabang checked on real data", "ADR-0056 step 3"],
    ["Cameras beside incidents (view only)", "1,413 cameras; in-page pictures checked by the owner", "ADR-0046 to 0051"],
    ["Daily research archive without personal data", "First day 2.9 MB; scan found no links or provider IDs", "ADR-0055"],
    ["GEOGLOWS River Watch card", "Seven-day trend for two exploratory reaches", "ADR-0036"],
  ], [3200, 3900, 1926], { zebra: true }),
  gap(),
  callout("Not yet verified", [
    "An AI-worded live answer in a signed-in browser; DDPM centre exposure rows after the latest rebuild; the Planner live layer seen in a browser by a planner.",
  ], "FFF7ED", "C2410C"),
);

// 6 Architecture
children.push(
  h1("6. Proposed architecture"),
  image("arch.png", 2259, 1780),
  caption("Figure 1. Sources feed one evidence engine in the worker; one fact bundle feeds every output."),
  h2("6.1 Layers"),
  table(["Layer", "Responsibility", "Where (today)"], [
    ["Sources", "Fetch on a schedule; keep raw bytes with SHA-256, time and licence.", "Worker pulls; backup capture process"],
    ["Evidence engine", "Observation model, freshness bands, incidents, exposure, district codes. All spatial work happens here, never in a web request.", "core/flood_evidence (worker)"],
    ["Fact bundle", "Labelled facts for one area, time window and audience; officer and restricted fields filtered by audience.", "build_facts, planner_answer"],
    ["Outputs", "Planner map and answers, DDPM reports, live feed, research archive, future partner export.", "api/maps.py, api/planning.py, archive.py"],
    ["Exchange", "Global Risk serves contributed feeds and briefs through MCP; GRP reads regional layers back as labelled external evidence.", "Global Risk platform"],
  ], [1900, 4600, 2526], { zebra: true }),
  h2("6.2 Design principles"),
  ...bullets([
    [{ t: "Computed, not written. ", bold: true }, "Every number comes from tested code; AI only words facts and a gate refuses unknown numbers or banned wording."],
    [{ t: "No GIS in web requests. ", bold: true }, "Requests read stored results, so a slow source never slows a page."],
    [{ t: "Evidence, not verdicts. ", bold: true }, "Confidence is a word with reasons; “reported nearby”, never “flooded”; no warnings."],
    [{ t: "Live never changes an assessment. ", bold: true }, "Assessments stay locked and reproducible; live data is context with a timestamp."],
    [{ t: "Licences travel with data. ", bold: true }, "Restricted sources stay internal; public outputs carry credits."],
    [{ t: "Versions are pinned. ", bold: true }, "Every derived row carries its rule version, so history stays comparable."],
    [{ t: "Fail closed. ", bold: true }, "Unknown areas, Hubs or malformed sources are refused with a plain reason."],
  ]),
  h2("6.3 Roles of GRP and Global Risk"),
  table(["", "GRP (Hub system)", "Global Risk (exchange)"], [
    ["Holds", "Detailed, sensitive and licensed data; officer checks; DDPM baseline", "Manifests and public summaries; regional hazard layers; documents"],
    ["Users", "DDPM planners, Hub operators", "Planners and analysts anywhere, through MCP"],
    ["Output", "Reports, Planner answers, archive", "feeds_query, risk briefs with receipts"],
    ["Data flow", "Sends public-fit summaries", "Returns regional evidence, labelled as external and never merged into GRP counts"],
  ], [1700, 3663, 3663], { zebra: true }),
);

// 7 Reports
children.push(
  h1("7. Consolidated reports for planners"),
  image("horizons.png", 1904, 246),
  caption("Figure 2. Four planning horizons, one fact bundle."),
  table(["Report", "Reader", "Facts", "Status"], [
    ["Pre-season preparedness (months)", "DDPM provincial planner", "Shelters and capacity, RP100 / JRC scenarios, registered population, sensitivity indicators, warning resources", "District Word report built; province roll-up and DDPM template missing"],
    ["Days ahead (anticipatory)", "DDPM central operations", "GEOGLOWS trend and peak per confirmed reach; districts, shelters and population along it; rain context", "Mostly missing; needs confirmed reaches"],
    ["Live shift report (hours)", "Operators, DDPM central, BMA (to confirm)", "Incidents and confidence, what changed, facilities nearby, officer checks, DDPM shelters", "On page and in answers; downloadable report missing"],
    ["After-action (after the event)", "Planners, data scientists", "Timeline, peak counts, longest incidents, facility durations, disagreements", "Replay and archive built; summary missing"],
  ], [2000, 1800, 3226, 2000], { zebra: true }),
  h2("7.1 The fact bundle"),
  p("One bundle per area (admin code), time window (from, to, evidence time kept apart from computed time) and audience (DDPM internal, partner, public). Each fact carries its source, version, rule version, freshness and caveat. Missing data is listed as a gap, never left silent. The audience filters facts but never changes them."),
  h2("7.2 Insurance (future)"),
  p("Insurers would want event histories, exposure totals and an audit trail. We do not propose building this now, but some things cannot be fixed later and are already in place or proposed:"),
  ...bullets([
    "History is kept day by day (section 8) with pinned rule versions.",
    "A GRP-side audit trail is needed: Global Risk receipts keep only “records via URL”, not the fetched rows.",
    "Commercial-use licences must be confirmed: OSM share-alike for derived databases, DDPM permission, GEOGLOWS terms.",
    "Crowd and agency reports are not a payout trigger, and no report states a loss.",
    "Insurers need a separate partner channel with an agreement, not public feeds.",
  ]),
);

// 8 Archive
children.push(
  h1("8. History archive for modelling"),
  p("Retention removes raw downloads after 14 days and per-snapshot facility states after 7 days. Labels (officer checks, later camera checks and sensors) are the scarcest data a model needs. The archive keeps only what a model needs, day by day from go-live, before retention removes anything."),
  table(["Table", "One row per", "Why a model needs it"], [
    ["road_state", "change of a road segment’s state (valid_from, valid_to)", "the main signal; full time series rebuilt from changes"],
    ["road_geometry", "segment geometry seen that day", "joins without repeating geometry"],
    ["report", "report state; salted hash key; no text, link or ID", "point evidence and timing"],
    ["incident, incident_event, incident_run", "incident and each lifecycle change", "event targets: start, duration, size, merges"],
    ["facility_exposure", "change of a facility’s state", "impact layer"],
    ["label", "officer check with a stable pseudonym", "ground truth"],
    ["weather", "rain now and in 30 minutes per scope", "predictor (internal research only)"],
    ["context", "archive day", "configuration and source versions for reproducibility"],
  ], [2500, 3500, 3026], { zebra: true }),
  h2("8.1 Rules"),
  ...bullets([
    "No personal data: report text, links, provider IDs and officer names never enter the archive; the backup capture is cleaned the same way.",
    "Written once per finished UTC day, never overwritten; replays are never archived.",
    "Every row carries its rule version; the manifest records row counts, SHA-256, fetch counts and licences.",
    "Gzipped JSON Lines, readable by Python, pandas, DuckDB and QGIS without new dependencies; GeoParquet can be added later.",
    "Missing evidence is not a “dry” label; the data card documents biases (busy areas, daytime, main roads).",
  ]),
  h2("8.2 Operations"),
  p("The worker archives finished days every hour before retention. A manual command (python -m grpcli.flood_pilot archive) backfills. Storage is local today; the proposal moves it to the Ubuntu host with one external backup and read-only access for ADPC data scientists."),
);

// 9 Live feed and MCP
children.push(
  h1("9. Live feed to Global Risk and MCP testing"),
  h2("9.1 The standard we follow"),
  p("Global Risk registers a contributed live feed as a short declarative manifest (adapter generic_json, residency external call-out). The platform fetches the URL at query time; only the manifest is submitted, once. The USGS earthquake feed already works this way. We confirmed this in the platform source code (SERVIR-AI/global-platform, commit a8a43c2)."),
  h2("9.2 Proposed endpoint"),
  table(["Item", "Design"], [
    ["Route", "GET /api/v1/pilot/flood/{pilot_id}/feed.json; protected until a public host exists, then public with a rate limit"],
    ["Source", "Latest stored worker run only; no work in the request; replay IDs never resolve (404)"],
    ["records", "One per open incident: confidence word and reasons, source families, districts, road names, centre and box, deepest depth and report count (Floodboard sources only), facilities nearby by type, first seen, last evidence, valid_until"],
    ["districts", "All 50 districts always, least concern first: active and receding counts, worst confidence, facilities nearby, as_of, valid_until"],
    ["Left out", "Report text, names, officer checks, camera links and IDs, Longdo content, rain"],
    ["Caching", "Deterministic body, ETag and 304; Cache-Control 60 seconds"],
  ], [1800, 7226], { zebra: true }),
  h2("9.3 What the platform code showed"),
  table(["Finding", "Design response"], [
    ["generic_json feeds are cached for 6 hours (built for monthly indices).", "Every record carries valid_until; ask maintainers for a per-feed cache time."],
    ["An empty record list is treated as a failure (stale copy served; submission refused).", "Submit the districts feed first (never empty); incidents on a flooding day; ask for empty_ok."],
    ["Unknown manifest fields are refused; the URL must be public and anonymous.", "Drafts trimmed; a public HTTPS host is required."],
    ["A staged submission is visible only to us and reviewers; withdrawing frees the name.", "Test privately, withdraw if wrong, then go live."],
    ["Risk briefs cite feeds by hazard, not by place; they read only 3 records.", "usage_notes start “Bangkok only”; worst districts published last so they are the ones returned."],
  ], [4300, 4726], { zebra: true }),
  h2("9.4 Test plan (live on Global Risk and through MCP)"),
  ...numbered([
    "Local: build the endpoint with tests (shape, 50 districts, no restricted fields, replay 404, ETag).",
    "Host: deploy on the Ubuntu server over HTTPS; switch the route to public; check from outside.",
    "Staged: submit the districts manifest; call feeds_query(\"bangkok_flood_districts_live\", {limit: 50}); confirm counts match GRP; withdraw and fix if needed.",
    "Incidents: submit the incidents manifest on a day with flooding; check records, confidence words and valid_until.",
    "MCP scenarios: ask an MCP client “which Bangkok districts have active flooding now?”; run a Global Risk flood brief for Bangkok and confirm it cites the feed with its usage notes; check the receipt and record what it can and cannot replay.",
    "Go live only after reviewer approval and the owner’s explicit yes.",
  ]),
);

// 10 Security
children.push(
  h1("10. Security, privacy and licensing"),
  ...bullets([
    "Report text, links, photos and provider IDs are never stored for display or archived; the backup capture hashes IDs and text and drops links.",
    "Officer checks are internal; Planner answers remove them until decision D2.",
    "Volunteer contact fields stay excluded from every API response.",
    "Restricted sources (Longdo, BMA cameras, bmatraffic) stay internal; public outputs only carry sources that allow redistribution, with credit.",
    "DDPM baseline data stays out of Git and is read from the database.",
    "Every new route declares x-grp-access and is covered by the permission matrix test.",
    "Secrets stay in protected files; nothing is sent to an external service without the owner’s approval at that moment.",
  ]),
);

// 11 Backlog
const backlogWidths = [900, 3700, 900, 2626, 900];
const epic = (title, rows) => [h3(title), table(["ID", "Story", "Priority", "Acceptance criteria", "Status"], rows, backlogWidths, { zebra: true }), gap()];
children.push(
  h1("11. Proposed backlog"),
  p("Priorities: Must (needed for the next milestone), Should (high value, next), Could (later). Status: Done, Ready (can start), Blocked (named dependency)."),
  ...epic("E1. Live feed to Global Risk", [
    ["E1-1", "As a regional analyst, I want Bangkok flood incidents and a district summary as feed.json so Global Risk can serve them.", "Must", "Records and 50 districts; valid_until per record; no restricted fields; replay 404; ETag; tests; ADR-0052", "Ready"],
    ["E1-2", "As the platform team, we need a public HTTPS host so Global Risk can fetch the feed.", "Must", "Permanent domain; route public with rate limit; reachable from outside", "Blocked: Ubuntu host"],
    ["E1-3", "Send maintainer questions on cache time, empty lists and receipts.", "Must", "Answers recorded in the feed plan", "Ready (drafted)"],
    ["E1-4", "Stage the districts manifest and verify with feeds_query.", "Must", "Counts match GRP; withdrawn and fixed if wrong; owner yes recorded", "Blocked: E1-1, E1-2"],
    ["E1-5", "Stage the incidents manifest on a flooding day.", "Should", "Records returned newest first with confidence and valid_until", "Blocked: E1-4"],
    ["E1-6", "Run the MCP test scenarios and record results.", "Should", "MCP answer, brief citation and receipt behaviour documented", "Blocked: E1-4"],
  ]),
  ...epic("E2. Planner live integration", [
    ["E2-1", "Steps 1–4: district codes, live layer, live answers, DDPM centres.", "Must", "Built and tested (ADR-0056)", "Done"],
    ["E2-2", "Browser acceptance by a signed-in planner (layer and AI-worded answer).", "Must", "Owner confirms layer, answer and no-warnings text", "Ready"],
    ["E2-3", "Decide and implement officer-check visibility for planners; neutral ordering.", "Should", "D2 recorded; order no longer leaks officer judgements", "Blocked: D2"],
    ["E2-4", "Live section in the district Word summary, marked “as of, not part of the assessment”.", "Could", "Separate section with time; assessment unchanged", "Ready"],
  ]),
  ...epic("E3. DDPM planner reports", [
    ["E3-1", "Obtain one DDPM situation report and one pre-season plan as templates.", "Must", "Samples in hand; fields mapped to facts", "Blocked: D1"],
    ["E3-2", "Generalise the fact bundle for any area, window and audience.", "Must", "Shared by Planner, feed and reports; audience filter tested", "Ready"],
    ["E3-3", "Live shift report (Word).", "Should", "Built from the bundle; “since last report” section", "Ready after E3-2"],
    ["E3-4", "Province pre-season roll-up.", "Should", "District sums with gaps stated", "Blocked: E3-1"],
    ["E3-5", "After-action event summary from the archive.", "Should", "Timeline, peaks, durations, disagreements", "Ready"],
  ]),
  ...epic("E4. River outlook (GEOGLOWS)", [
    ["E4-1", "Hydrologist confirms reaches and the districts each affects.", "Must", "Reviewed mapping file with reviewer and date", "Blocked: D3"],
    ["E4-2", "Daily reach summary; candidate first Global Risk contribution.", "Should", "Licence confirmed; manifest drafted; staged test", "Blocked: E4-1"],
    ["E4-3", "Threshold method with scientific approval.", "Could", "ADR and approval; golden values signed off", "Later"],
    ["E4-4", "HAND depth experiment (Phase B) with local data.", "Could", "Local terrain, rating curve and review", "Blocked: data"],
  ]),
  ...epic("E5. Research archive", [
    ["E5-1", "Daily archive and backfill.", "Must", "Built (ADR-0055); first day 2.9 MB", "Done"],
    ["E5-2", "External backup of the archive.", "Must", "Second copy off the laptop, restore tested", "Ready"],
    ["E5-3", "Move to the Ubuntu host; read-only access for ADPC data scientists.", "Should", "Access list; data card shared", "Blocked: host"],
    ["E5-4", "Alert when a finished day is not archived.", "Should", "Alert within 24 hours", "Ready"],
    ["E5-5", "Add GEOGLOWS runs and camera labels; optional GeoParquet copy.", "Could", "New tables with versions", "Later"],
  ]),
  ...epic("E6. Camera check (water, partial water, dry)", [
    ["E6-1", "BMA permission to analyse pictures and share the one-word result.", "Must", "Written permission", "Blocked: BMA"],
    ["E6-2", "Worker camera check through the AI gateway with caps and no stored pictures.", "Should", "Up to 2 cameras per active incident every 15 minutes; daily cap; tests", "Blocked: E6-1, model choice"],
  ]),
  ...epic("E7. Platform and governance", [
    ["E7-1", "Push the branch and open a reviewed pull request.", "Must", "PR lists behaviour, ADRs 0053–0056, validation, migrations (none)", "Ready"],
    ["E7-2", "First Ubuntu deployment run.", "Must", "Stack healthy on the host", "Ready"],
    ["E7-3", "Run the Floodboard capture as a service that survives reboot.", "Should", "Restarts automatically; cleaned reports", "Ready"],
    ["E7-4", "Send the Floodboard credit confirmation; build a licence register for commercial use.", "Should", "Replies recorded; register reviewed", "Ready (drafted)"],
  ]),
);

// 12 Roadmap
children.push(
  h1("12. Roadmap"),
  table(["Now (next 2 weeks)", "Next (weeks 3–6)", "Later"], [
    ["E2-2 browser acceptance\nE1-1 feed endpoint\nE1-3 maintainer questions\nE5-2 archive backup\nE7-1 pull request\nE7-2 Ubuntu deployment",
     "E1-2 public host, E1-4 staged test, E1-6 MCP tests\nE3-2 fact bundle, E3-3 shift report\nE4-1 confirmed reaches\nE5-3/E5-4 archive on the host",
     "E3-4 province roll-up, E3-5 after-action\nE4-2 GEOGLOWS contribution\nE6 camera check\nInsurance partner channel\nE4-3/E4-4 thresholds and HAND"],
  ], [3008, 3009, 3009]),
);

// 13 Decisions
children.push(
  h1("13. Decisions needed"),
  table(["ID", "Decision", "Unblocks"], [
    ["D1", "Obtain DDPM sample reports (situation report, pre-season plan)", "E3"],
    ["D2", "Who reads the Bangkok live report (DDPM central, BMA, both) and whether planners see officer checks", "E2-3, E3-3"],
    ["D3", "Who confirms GEOGLOWS reaches and districts (ADPC or RID hydrologist)", "E4"],
    ["D4", "First Global Risk contribution: GEOGLOWS daily summary or Bangkok districts", "E1, E4-2"],
    ["D5", "Look for a Floodboard-like source outside Bangkok, or stay Bangkok-only", "Scale"],
    ["Host", "Run the Ubuntu deployment and choose a permanent domain", "E1-2, E5-3"],
    ["Send", "Send the Floodboard note, maintainer questions and BMA addition (all drafted)", "E1, E6"],
    ["Model", "Camera-check model (the AI gateway uses an OpenAI-style provider today)", "E6-2"],
    ["Decided", "D7 rain in Planner answers (yes, as context); D8 fixed no-warnings wording (approved)", "Done"],
  ], [1100, 6000, 1926], { zebra: true }),
);

// 14 Risks
children.push(
  h1("14. Risks"),
  table(["Risk", "Mitigation"], [
    ["Readers treat estimates as warnings", "Fixed no-warnings text; confidence words; “reported nearby”; usage notes"],
    ["Licence breach", "Restricted sources excluded in code and tested; permission requests drafted"],
    ["Global Risk serves stale live data (6-hour cache)", "valid_until per record; maintainer request for per-feed cache"],
    ["A dry day breaks the incidents feed", "Districts feed first; empty_ok request"],
    ["A single laptop copy of the archive", "External backup (E5-2); move to host"],
    ["GEOGLOWS misread as street-flood forecast", "Labelled river context; confirmed reaches before naming districts"],
    ["Officer judgements leak to planners", "Fields removed; ordering fix with D2"],
    ["Rule changes make history incomparable", "Rule version on every archived row"],
  ], [3800, 5226], { zebra: true }),
);

// Appendix
children.push(
  h1("Appendix A. Records and documents"),
  table(["Record", "Subject"], [
    ["ADR-0036", "GEOGLOWS River Watch is display-only forecast evidence"],
    ["ADR-0038 to 0045", "Bangkok pilot: evidence, cameras, facilities, incidents, officer checks, grounded answers, replay, retention"],
    ["ADR-0046 to 0051", "Live camera sources and the local picture relay"],
    ["ADR-0052 (reserved)", "Live feed endpoint"],
    ["ADR-0053", "The pilot covers the whole city"],
    ["ADR-0054 (reserved)", "Camera check"],
    ["ADR-0055", "Research archive keeps model data day by day without personal data"],
    ["ADR-0056", "Live flood evidence reaches the Planner (steps 1–4)"],
    ["docs/pilot/2026-10-03_Global_Risk_Live_Feed_Plan.md", "Feed plan, platform source findings, test plan"],
    ["docs/pilot/2026-10-04_DDPM_Planner_Reports_Design.md", "Reports by horizon, fact bundle, insurance"],
    ["docs/pilot/2026-10-04_Flood_Research_Archive_Design.md", "Archive design"],
    ["docs/pilot/2026-10-04_Planner_Live_Flood_Integration_Plan.md", "Planner integration steps"],
    ["docs/data/flood_research_archive_datacard.md", "Data card for data scientists"],
    ["handovers.md (Section 0, 4 October)", "Roadmap input, developer detail, decisions"],
  ], [3800, 5226], { zebra: true }),
  h2("Glossary"),
  table(["Term", "Meaning"], [
    ["Incident", "A group of nearby road segments with flooding reported now, with its own identity over time"],
    ["Confidence word", "low, medium, high or conflicting, with reasons; never a probability"],
    ["Fact bundle", "The computed, labelled facts an output may use for one area, time window and audience"],
    ["Staged contribution", "A Global Risk submission visible only to the contributor and reviewers until approved"],
    ["MCP", "Model Context Protocol: how AI clients call Global Risk tools such as feeds_query"],
    ["HAND", "Height Above Nearest Drainage: a terrain method for approximate flood depth"],
    ["RP100", "The 100-year return-period flood scenario"],
  ], [2400, 6626], { zebra: true }),
);

// ------------------------------------------------------------------ document
const doc = new Document({
  creator: "GRP pilot team",
  title: "GRP Live Flood Intelligence: proposal",
  description: "Proposal for the development team",
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: FONT, color: "1F4E79" },
        paragraph: { spacing: { before: 120, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: FONT, color: "2E75B6" },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: FONT, color: "374151" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 540, hanging: 300 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 300 } } } },
      ] },
      { reference: "numbers", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 540, hanging: 360 } } } },
      ] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
      children: [run("GRP Live Flood Intelligence · Proposal v1.1 (draft)", { size: 16, color: "6B7280" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [run("Page ", { size: 16, color: "6B7280" }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: "6B7280" })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(process.argv[2] || "proposal.docx", buf);
  console.log("written", buf.length);
});
