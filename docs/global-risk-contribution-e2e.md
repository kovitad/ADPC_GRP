# Contributing GRP's data to Global Risk: end-to-end test and gaps

Status: test preparation, 29 September 2026. Nothing has been submitted. The kit to hand over is
`.local/data-out/google-drive-upload/`, with the tester's guide inside it. The files are prepared
by `scripts/prepare_global_risk_contributions.py` into `.local/data-out/` (git-ignored), one
folder per `.local/data-in/` folder.

## The path a dataset takes

1. **Prepare.** The script converts each source into the form Global Risk accepts:
   - point layers become GeoJSON with contact fields removed;
   - rasters become EPSG:4326, classed 1–5;
   - a population grid stays as raw counts.

   It writes `manifest.yaml`, `manifest.json` and `TEST.md` beside each file, and checks every
   manifest and point file with GRP's own rules (`core/contribution_rules.py`).
2. **Host.** Upload the file to Google Drive and share it with "Anyone with the link". Use the
   direct-download form of the link.
3. **Submit.** Two ways:
   - GRP's Share data page (ADR-0032), which checks the file first;
   - Claude Desktop or Cowork with the SERVIR connector, using `contribute_submit`.

   Global Risk auto-approves, so the layer is public to every user at once.
4. **Global Risk uses it.** `assemble_pack` counts every point layer against the hazard, beside
   OpenStreetMap schools, hospitals, buildings and roads. It sums a `population_` grid. A
   `vulnerability_` raster only enters risk levels through a weights contribution.
5. **GRP shows it.** In Planning, "Add Global Risk context" gathers a fresh pack for the selected
   district. The evidence card and the Word summary (ADR-0033) then list the new layer's counts.
   Evidence gathered *before* the contribution does not have it, so ask again.

## What each engine computes

| | GRP | Global Risk |
|---|---|---|
| District shape | DOPA polygon (`Thailand_District_Boundaries`) | OpenStreetMap polygon |
| Flood layer | JRC RP100 depth tiles, full resolution, metres | `hazard_flood`, "derived from JRC GLOFAS v2.1", classes 0–5 |
| Exposed means | depth > 0 at the point | class ≥ 1 at the point |
| No value at a point | "N/A — unable to assess" | class 0, counted as not exposed |
| Result | every centre by name, with status and depth | counts: N of M, by class and by risk level |
| Population | registered village population (ADR-0027) | sum of a `population_` count grid |
| Vulnerable people | relative sensitivity, display only (ADR-0030) | weighted into risk levels when weights say so |

## GRP's own numbers for the test districts

From `.local/data-out/compare/district_comparison.md`:

| District | DOPA area | Centres (in flood) | Volunteer centres (in flood) | Villages (in flood) | People in villages in flood |
|---|---:|---:|---:|---:|---:|
| Samko, Ang Thong | 89 km² | 12 (8) | 4 (4) | 33 (25) | 12,633 of 16,571 |
| Tha Pla, Uttaradit | 1,154 km² | 13 (0) | 10 (2) | 76 (8) | 3,927 of 38,316 |
| Ban Khok, Uttaradit | 994 km² | 7 (0) | 5 (0) | 28 (0) | 0 of 14,364 |
| Bang Bua Thong, Nonthaburi | 118 km² | 1 (1) | 8 (8) | 137 (135) | 281,905 of 286,516 |
| Bang Kapi, Bangkok | 28 km² | 0 | 0 | 1 (0) | 0 of 325 |

Global Risk's answers of 28 September used the test layer (the same 10,303 centres):
- Samko: 12 of 12 centres in flood, by class 1: 2, 2: 4, 3: 2, 4: 4.
- Tha Pla: 0 of 16, over a 1,784 km² polygon.
- Ban Khok: 0 of 7, over a 1,013 km² polygon.

## Gaps to be aware of when combining the results

### The two engines count different ground and different water

1. **Different district polygons.** For Tha Pla, Global Risk's polygon is 1,784 km², and GRP's
   DOPA polygon is 1,154 km². So Global Risk counts 16 centres where GRP counts 13. A difference
   in any count may come from the boundary alone.
   - *Do:* read the polygon area in each Global Risk answer before comparing.
   - *Needs from Global Risk:* accepting a boundary. There is no boundary contribution kind yet
     (runbook section 10).
2. **Different flood layers.** In Samko, GRP finds 8 of 12 centres in flood, and Global Risk says
   12 of 12, with a different split by class, on the same points. Global Risk's layer is a
   derived, reclassed product, not GRP's tiles.
   - *Test:* contribute `hazard_flood_thailand_rp100` (GRP's tiles, classed) and ask with that
     layer. If the counts then match, the difference is the raster. If they don't, it is the
     sampling.
3. **Depth-class edges disagree.** The runbook puts class 4 at 1.5–2.5 m and class 5 above
   2.5 m. Global Risk's live answers say 1.5–2 m and above 2 m. The prepared flood file uses the
   live legend.
   - *Needs from Global Risk:* one legend.
4. **"No data" becomes "not exposed".** The JRC tiles store dry ground and missing data as the
   same value (-9999). GRP reports such a centre as "unable to assess". GRP's stored Ban Khok
   assessment has all 7 centres "unable to assess", where Global Risk said "0 of 7 exposed".
   GRP's stored Samko assessment (8 potentially exposed, 4 unable to assess) matches the
   comparison table. Global Risk's class 0
   counts it as not exposed. The same centre can read "N/A" in GRP and "not exposed" in Global
   Risk.
   - *Do:* never present Global Risk's unexposed count as "safe".
5. **Counts only, no names.** Global Risk returns "N of M". It never says which centres, so a
   difference cannot be traced to particular centres. GRP names every centre.

### What Global Risk adds, and what only looks new

6. **Genuinely new for planners.** Global Risk adds:
   - OpenStreetMap schools, hospitals, buildings and roads in the flood hazard;
   - a flood-zone headcount once a population grid lands;
   - risk levels (hazard crossed with weighted vulnerability), which GRP does not show
     (ADR-0014).
7. **GRP's data echoed back.** These are GRP's own data counted by another engine:
   - evacuation centres;
   - early-warning towers;
   - volunteer centres;
   - villages;
   - the village headcount grid.

   The overlay is new for the towers and volunteer centres, because GRP never checks them against
   flood depth. The data itself is not.
8. **Fixed 29 September: the Word summary labels GRP's data as GRP's.** `api/planning_summary.py`
   now matches exact layer names: the prepared GRP layers (`GRP_ORIGIN_LAYERS`) plus the Hub's
   approved `sig_contribution` names. Their rows read "GRP's own data, counted again by Global
   Risk". The list is needed because a contribution made from Claude Desktop never reaches
   `sig_contribution`. Each row keeps its layer name, so the test layer and
   `evacuation_centres_ddpm` show as two rows while both exist. Another agency's layer that
   merely contains "evacuation" is no longer taken for GRP's. The summary also names Global
   Risk's flood layer and polygon area.
   - *Keep in step:* a new GRP layer name contributed to Global Risk must be added to
     `GRP_ORIGIN_LAYERS`.
9. **Double counting until the test layer goes.** `evacuation_centres_th_test`
   (`c66ade79bc2605ac`) holds the same 10,303 centres. With `evacuation_centres_ddpm` beside it,
   every answer counts them twice. Only a Global Risk reviewer can withdraw an approved layer; our
   account is not a reviewer.

### People

10. **Global Risk does not add up people from points.** It counts villages. A headcount needs a
    `population_` grid. The prepared grid sums the village register into ~1 km pixels (56.6
    million people), so a flood edge takes a village's people all or none.
    - It is the same register GRP reports, not a second opinion. WorldPop would be the
      independent alternative.
11. **No vulnerable-people headcount anywhere.** Global Risk does not yet multiply a
    vulnerable-share layer by a headcount (runbook section 10). GRP's sensitivity is a relative
    index, not a count.
12. **Bangkok has almost no village records.** Bang Kapi has one village with 325 people, so any
    headcount from the register undercounts Bangkok badly, in both engines.

### Vulnerability and weights

13. **Weights are a scoring decision.**
    - Contributing the child and elderly sensitivity rasters does nothing until a weights
      contribution names them.
    - Weights for hazard `flood` change every user's Thailand risk levels. The prepared example
      targets `flood_thailand` only, which needs the Thailand flood layer first.
    - GRP keeps sensitivity display-only (ADR-0030) and does not show Global Risk risk levels
      (ADR-0014). The owner decides whether to weight it at all.
14. **The disability raster is withheld.** Its values are 1, 2 and 255, and nobody has said what
    they mean.

### Provenance and quality carried into every answer

15. **Licence and vintage are unconfirmed.** Every manifest says `license: unstated` and
    `vintage: 2026-09`, and every Global Risk answer will cite them that way.
16. **Auto-approved means unreviewed and public.** Every citation says "auto-approved — no human
    reviewed this layer".
17. **Known source defects travel with the data:**
    - 1,599 shelters share a coordinate with another record;
    - 650 villages have male + female ≠ total, so they are left without population;
    - 80 villages have projected coordinates and are left out.

### Plumbing

18. **Tables are invisible to GRP.** A table (the sub-district population) reaches Global Risk's
    `feeds_query` only. GRP never calls `feeds_query`, and exposure counts never use tables.
19. **Stale evidence.** GRP reuses a Global Risk pack for an hour (`PACK_REUSE_SECONDS`), and
    "Add Global Risk context" does not force a new one. After a contribution lands, the card
    says "reused, no new Global Risk lookup"; click "Gather again from Global Risk" before
    downloading the summary. The summary uses the latest evidence for the district.
20. **File hosting.** Google Drive puts a virus-scan page in front of files over about 100 MB.
    Every prepared file is under that; check the sizes in each folder.

21. **The summary uses only the downloader's own evidence.** Evidence is stored per GRP user and
    Hub, and a planner role is needed. Answers from Claude Desktop never reach GRP. Whoever
    downloads the summary must gather Global Risk context under their own GRP sign-in after the
    layer lands.
22. **GRP always asks about hazard `flood`.** `api/planning.py` calls `assemble_pack` with
    `hazard: "flood"`, so a contributed `hazard_flood_thailand_rp100` appears in Claude's answers
    but never in GRP's evidence or Word summary. There is no hazard picker; none was added.
23. **A population count's shape is unknown.** No Global Risk pack with a `population_` grid has
    been seen yet. The summary keeps any count it cannot tabulate as a row that points to the
    brief, instead of dropping it. When the grid lands, gather evidence once in GRP and read the raw pack from `planning_sig_pack.pack` for that user and place. Then teach `global_risk_stats` its shape.

24. **A contribution cannot be updated.** Global Risk's main runbook
    (`https://servirplatform.sig-gis.com/runbook/`, section 14) says "Contributions never overwrite
    existing entries". Removal is a server command run by the Global Risk team
    (`remove-raster <layer>`, `remove-feed <dataset>`), or `contribute_review` by a reviewer. It
    stops future use, and receipts made while the layer was live stay replayable. A corrected file
    therefore means asking for removal first, then one new submit. Not yet observed: whether a
    repeated layer name is declined or kept beside the first. `contribute_submit` has no
    contribution-ID field; the ID is only for `contribute_status` and for asking for removal.

## Combining the two for a planner

- **GRP answers "which centre, and is it usable":** named centres, status, depth, and "N/A"
  where the flood layer has no value.
- **Global Risk answers "what else is in the water":** schools, hospitals, buildings, roads,
  warning towers and volunteer centres by depth class, and a headcount once a grid lands.
- **Never add the two centre counts together.** Show each with its polygon and flood layer named.
- **Before the Word summary is trusted after these contributions,** withdraw the test layer
  (gap 9) and gather fresh evidence (gap 19).
