# Live flood evidence in the Planner for Bangkok: plan

Status: plan, 4 October 2026. Nothing built. The Product Owner asked whether the pilot-tab data can
reach the Planner during a Bangkok assessment: a current flood layer on the map, and the AI
answering early-warning questions. They also asked whether to do this or the Global Risk live feed
first.

## Recommendation: the Planner first, the feed in parallel

- **Nothing blocks the Planner work.** The data is already in GRP, and the users are our own
  planners.
- **The live feed waits on others:** a public host, and the Global Risk maintainers (the 6-hour
  cache and empty lists).
- **Both use the same fact builder,** so the Planner work also builds most of feed step 1.

## What the Planner can honestly show today

| Question a planner asks | Source | Coverage today | Honest answer |
| --- | --- | --- | --- |
| Where is flooding reported now? | Floodboard incidents and roads | all 50 Bangkok districts | yes, with confidence words and times |
| Which evacuation centres have flooding reported nearby? | the exposure engine | OSM facilities only today; DDPM shelters need step 4 | after step 4; DDPM's delivery has no Bangkok centres (the 8 points found were misplaced records), so OSM facilities answer this in Bangkok |
| Is it raining, and will it in 30 minutes? | Longdo (ADR-0049) | 4 districts plus the busiest incidents | partly; most districts have no rain record |
| Will the river rise in the next days? | GEOGLOWS (ADR-0036) | 2 exploratory reaches near Bang Bua Thong, **outside Bangkok**; Hub Admins only | not for Bangkok today |
| Is there a warning? | none | GRP issues no warnings | **never**. The AI describes current conditions and points to official channels in fixed, approved wording |

## Rules the plan keeps

1. **Live data never enters an assessment.**
   - An assessment is locked and reproducible. The live layer and live answers are context with
     a timestamp, kept out of the stored result and its receipt.
   - If the district Word document ever includes live data, it is a separate section marked "as
     of HH:MM, not part of the assessment".
2. **Name the layer for what it is:** "Reported flooding on roads (live, not a flood map)".
   - It has its own legend, kept visibly apart from the RP100 scenario.
   - Floodboard rates roads; it does not give a flood extent.
3. **No stale live answers.** The Planner caches answers by message, place and layers. When live
   facts are included, the cache key adds the incident run's `snapshot_at`. This is tested.
4. **No warnings.**
   - The AI may say "flooding is reported on these roads as of 14:20, medium confidence".
   - It may not say "warning", "expect flooding" or "safe".
   - The sentence pointing to official warning channels is fixed text, approved by the owner, not
     model output.
5. **Sub-districts roll up.** A sub-district (for example `103005`) shows its parent district's
   live facts, and the page says so. Clipping to the sub-district outline can come later.
6. **No GIS in requests.** District codes are computed once per incident in the worker (step 1).

## Steps

**Step 0, owner, now**
- Send the three drafts (Floodboard credit, Global Risk maintainer questions, the BMA addition).
  They take the longest.
- Decide D2 and D7 (below).

**Step 1, district codes on incidents** (small; everything below uses it)
- `update_incidents` stores `district_codes` (every district the incident's roads touch) in the
  summary.
- The Planner filter, the feed and the archive read it instead of approximating.
- Tests: an incident across a border lists both districts; a replay behaves the same.

**Step 2, the live layer on the Planner map** (Bangkok boundaries only)
- A switch: "Reported flooding on roads (live)".
  - Roads are coloured by freshness, and incidents by confidence word.
  - It shows the time of the last snapshot, a "not a flood map" note and the Floodboard credit.
- Data comes from the existing stored snapshot, through a new `protected` Planner route or the
  pilot route with Planner access. Either way it gets `x-grp-access` and a permission-matrix
  entry.
- It never shows officer checks unless D2 allows it.

**Step 3, live facts in Planner answers**
- When the selected area is in Bangkok, a deterministic "live" block joins the evidence:
  - incident counts and confidence;
  - the top incidents (capped as in `MAX_INCIDENTS`);
  - facilities with flooding reported nearby;
  - rain where tracked;
  - times and gaps.
- The AI words it behind the existing gate (ADR-0043); the number check applies.
- The cache key includes `snapshot_at`. Early-warning questions get current conditions plus the
  fixed "no warnings" text.

**Step 4, DDPM shelters in the exposure run**
- The exposure engine also assesses the DDPM evacuation centres inside the demo area, from the
  active baseline version, beside OSM facilities.
- The Planner can then answer "which evacuation centres have flooding reported nearby right now".
- DDPM's delivery has no Bangkok centres; the 8 points first found were misplaced records and are left out (correction, 4 October 2026).

**Step 5, the feed endpoint** (Global Risk step 1)
- It uses the same fact builder. Submission still waits for the host and the maintainers.

ADR-0056 records steps 1-4 (Planner access to live pilot data and the layer naming). ADR-0052
stays reserved for the feed, and ADR-0054 for the camera check.

## Decisions for the owner

- **D2 (from the reports design), widened.** Who sees what? Planners would see live incidents and
  facilities. Should they also see officer checks? And is the Bangkok live view for DDPM central,
  BMA, or both?
- **D7. Rain and River Watch for Planners.**
  - Should rain context open to Planners?
  - River Watch is Hub Admin-only (ADR-0036), and its reaches are outside Bangkok. Opening it to
    Planners is an access change that needs an ADR.
  - Recommendation: rain yes; River Watch only after reaches are confirmed (D3).
- **D8. The fixed "official warnings" sentence.** Approve the exact Thai and English wording, and
  name the official channels: TMD, DDPM, BMA.
