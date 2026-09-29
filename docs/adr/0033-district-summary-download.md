# ADR-0033: Planners download a district's whole summary as one Word document

## Status

Accepted on 28 September 2026 at the Product Owner's request: "download all summary in one
docx including any information that might be useful for them, and picture, the table of
statistics".

## Context

The Planning page spreads a district's information across the chat, the map, the evidence panel's
tabs and the Global Risk evidence. A planner needs it in one document to brief others, often
offline. The page already downloads the brief (.md), the evidence pack (.json), the trace (.txt),
the evidence table (.csv) and the Global Risk map link (.html).

Constraints: web requests do no GIS work (AGENTS.md), so the server cannot clip rasters for a map.
The stored flood-depth preview is about 1.9 km per pixel. On a phone the map is hidden while the
chat shows.

## Decision

1. **`POST /api/v1/planning/summary.docx`** takes only `hub_code`, `boundary_id`, an optional
   `assessment_id`, and a map picture. Every fact is read on the server through the functions the
   page already uses: `area_profile`, `assessment_result`, `map_layers`, `dataset_features` and
   `centre_indicator_values`. The document therefore says what the panel says.
2. **Sections:**
   1. At a glance: centres, the result counts, registered population, people inside the flood
      extent, supporting points.
   2. Map.
   3. Evacuation centres: source, where people could move, and every centre with its status,
      depth and sensitivity values.
   4. People: registered village population and villages inside the flood extent, with their
      caveats.
   5. Global Risk evidence: status, statistics, brief, receipt, map link, sources and gaps.
   6. What this cannot tell you.
   7. Sources and versions.
3. **Wording rules carried over:**
   - A centre is "not exposed under this scenario", never "safe"; "N/A" for a centre the flood
     layer cannot assess.
   - Population is "registered village population" (ADR-0027); there is no vulnerable-person
     headcount.
   - Sensitivity is a relative index, not a count, and is never sorted or scored (ADR-0030).
     Values are read through `centre_indicator_values`, so the ADR-0030 guard test still holds.
   - Global Risk risk fields (`at_risk`, `by_risk`) are not tabulated (ADR-0014), and its map is
     labelled unverified (ADR-0031).
   - A synthetic banner appears when the data is synthetic, and the data-gap text when there are
     no centres.
   - Volunteer contact fields never appear: `dataset_features` does not return them.
4. **Only this district's evidence.** The Global Risk section uses the person's own latest stored
   evidence whose requested place is this boundary's canonical place, or its parent district's for
   a sub-district. An assessment of another district is ignored.
5. **The map picture is drawn by the browser from data**, not captured from the live map. It is a
   fixed 1600×1000 canvas fitted to the district. It draws:
   - OpenStreetMap tiles loaded with CORS; if they fail, it draws without a base map and without
     the credit;
   - the flood preview, cropped and not smoothed;
   - the district outline, with the outside dimmed;
   - centres coloured by status;
   - a title, a legend and the OpenStreetMap credit.

   The server accepts only a PNG under 6 MB and 4000 px. The caption says the flood preview is
   about 1.9 km per pixel, and that each centre's status comes from the full-resolution layer.
6. **`GET /api/v1/planning/summary/centres.csv`** gives the full centre table: UTF-8 with a BOM for
   Excel, and cells starting `= + - @` prefixed so a spreadsheet does not run them as formulas.
7. Thai text uses Leelawadee UI in the complex-script font slot (`w:cs`), so Word does not show
   boxes. The file name has an ASCII form and a `filename*` form.
8. `python-docx` becomes a runtime dependency.

9. **Amended 29 September 2026:** the Global Risk section opens with "What Global Risk adds for
   this district". It gives plain names, counts by depth class and whether each row is new to GRP. The
   evacuation-centre row is marked as GRP's own test upload echoed back, not an independent check.
   Each Global Risk answer in the chat now says whether it went into the selected district's
   summary, and offers to select the right district when it did not.

## Consequences

- One click gives a planner a document to share. It copies stored numbers and estimates nothing.
- The map's flood layer is coarse. A sharp district flood map needs a worker job that clips the
  full-resolution raster; that is a follow-up, not part of this decision.
- The Global Risk brief is included as the planner saw it, with its status. A deterministic
  summary is marked "not publishable".

## Verification

- `tests/golden/test_planning_map.py`: the .docx has every section, the synthetic banner, the
  Thai font slot, one picture, and no risk or contact fields. A non-PNG picture is refused. The CSV
  has a BOM and neutralises formulas.
- `tests/fast/test_planning_summary.py`: a newer Bang Phli evidence record is not used for Bang
  Kapi, and risk fields are left out.
- The permission matrix lists both routes.
- On the desktop stack, generated from the real database: Mueang Amnat Charoen (Thai centre names,
  sensitivity, population, the planner's Global Risk evidence) and Bang Kapi (no centres, no
  evidence).
- The canvas map was drawn in a throwaway page with real OpenStreetMap tiles: not tainted,
  3.3 MB. Word opening the file and the in-page button are **not yet checked by the owner**.
