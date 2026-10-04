# Reports for DDPM planners from GRP, Global Risk and GEOGLOWS: analysis and design

Status: design only, 4 October 2026. No code, nothing sent or submitted. Written at the Product
Owner's request: "how all of this contributed data can produce good reports for the ปภ planner,
including the data from GEOGLOWS, also insurance companies in the future".

## 1. Summary

- **One fact bundle, many outputs.** Every report is built from one computed **fact bundle**
  for an area, a time window and an audience. The Word document, the MCP answer, the Global Risk
  feed and the page all read the same bundle, so a number is the same everywhere it appears.
  AI may only word the facts, behind the existing groundedness gate (ADR-0043).
- **Four reports, one per planning horizon.** DDPM planners work on four horizons:
  - before the season (months);
  - ahead of an event (days);
  - during an event (hours);
  - after it.

  GRP already covers the first and the last fairly well. Live response exists only for Bangkok.
  The "days ahead" report is mostly missing, and GEOGLOWS is the natural source for it, within
  strict limits.
- **The two platforms have different jobs.**
  - **GRP** is the Hub's own system. It holds the detailed and sensitive data and makes the
    official-use reports.
  - **Global Risk** is the exchange. It takes summaries, so planners elsewhere can ask through
    MCP, and it gives back regional layers (JRC return periods, OSM assets, documents).
- **Insurance must not be built yet.** But two things decided now cannot be undone later:
  history is being deleted today (ADR-0045), and incident records must pin their rule version.
  Section 8.

## 2. What we have, verified on 4 October 2026

| Fact | Evidence |
| --- | --- |
| GRP and the flood pilot use the same administrative codes | Chatuchak is `1030` in the GRP `boundary` table and in the pilot outlines; its sub-districts are `1030xx` |
| National baseline | 77 provinces, 928 districts, 7,436 sub-districts; 10,303 shelters, 8,199 volunteer centres, 1,533 early-warning resources, 80,397 villages; RP100 depth and three vulnerability rasters (handover) |
| DDPM baseline inside Bangkok is thin | 8 evacuation centres and 55 volunteer centres in the current versions; no village points |
| Live Bangkok picture | 123 active incidents across 21 districts, snapshot of 03:24 UTC; 1,067 OSM facilities (ADR-0053) |
| GEOGLOWS | a 7-day discharge forecast for 2 exploratory reaches near Bang Bua Thong; no return-period thresholds, because the upstream service fails (ADR-0036) |
| Global Risk | risk pack with JRC RP10-500 flood layers, OSM assets, 3 vulnerability layers, receipts and a groundedness gate. Contributed feeds are cached for 6 hours, and an empty feed counts as a failure (feed plan, source read) |

**Inferred, to confirm with DDPM.** The thin Bangkok baseline suggests BMA, not DDPM, holds most
local preparedness data for the capital. For Bangkok, DDPM's role is probably national
coordination. This design does not depend on that being right, but it changes who the Bangkok
live report is for (decision D2).

## 3. Who reads what

| Reader | Needs | Where it lives |
| --- | --- | --- |
| DDPM provincial planner | pre-season plan for their province and districts; shelters, population, gaps | GRP (Word document, page) |
| DDPM central operations | days-ahead watch across provinces; live situation where available | GRP |
| BMA or a city operator (to confirm) | live incidents, facilities, cameras, officer checks | GRP flood page |
| Planners elsewhere, regional analysts | a summary they can ask about through MCP | Global Risk (feeds, briefs) |
| Insurers (future) | event history, exposure totals, an audit trail | a separate partner channel, not public feeds (section 8) |

## 4. The four reports

For each report: what it is for, the facts it uses, what exists, what is missing, and where it
lives. DDPM has its own report formats. **We do not invent their fields.** Decision D1 asks for
samples, and the fact bundle is designed so it can fill whatever template comes back.

### 4.1 Pre-season preparedness (months ahead)

- **Purpose:** before the rainy season, show per province and district where people could go,
  which places a flood scenario reaches, and where data or capacity is missing.
- **Facts used:**
  - shelters, with capacity and supporting unit (ADR-0024);
  - each shelter's state under RP100, or JRC RP10-500 as external screening (ADR-0023);
  - registered village population and the villages inside the flood extent (ADR-0027);
  - sensitivity indicators as a relative index, never a count (ADR-0030);
  - volunteer centres and early-warning resources counted by area (ADR-0020);
  - Global Risk evidence with its receipt.
- **Exists:** almost all of it. The district summary Word document (ADR-0033) already has these
  sections.
- **Missing:**
  - a **province roll-up** across districts;
  - an **early-warning coverage gap** view (villages with no early-warning resource within a set
    distance; the distance must be agreed, not invented);
  - a "changes since last season" section;
  - DDPM's own template (D1).
- **Lives in:** GRP. A province summary could be contributed to Global Risk later as a table.

### 4.2 Days ahead (anticipatory watch)

- **Purpose:** 1 to 7 days before possible flooding, show where to pay attention and what to
  check.
- **Facts used:**
  - **GEOGLOWS river trend** (rise, steady or fall) and the forecast peak with its band, per
    confirmed reach, with the run time and freshness (ADR-0036);
  - **rain now and in the next 30 minutes** for the live pilot (Longdo; context only, ADR-0049);
  - for each **confirmed reach**, the districts and sub-districts along it, their shelters and
    their registered population, from the national baseline.
- **Exists:** the GEOGLOWS card for 2 exploratory reaches; the baseline data; the code join.
- **Missing, in order of importance:**
  1. **A hydrologist-confirmed map from reaches to districts.** This is GRP's real added value:
     GEOGLOWS is global, but which districts a reach affects is local knowledge. Without it no
     report may name an area as affected (D3).
  2. **A "high" threshold.** GEOGLOWS return periods fail upstream. Making our own thresholds
     (for example from GEOGLOWS's retrospective record) is a **scientific-method change**. It
     needs an ADR and scientific approval (AGENTS.md: golden values need approval). Until then
     the report says "rising/steady/falling" and never "warning" or "above normal".
  3. **Longer rain forecasts.** Longdo gives 30 minutes. A days-ahead rain source is an open gap
     (CHIRPS-style forecasts are declared gaps on Global Risk too).
- **Honest limit.** GEOGLOWS models rivers. Bangkok's road flooding is mostly from rain and
  drainage. **GEOGLOWS must never be presented as forecasting Bangkok street incidents.** It is
  river context for the Chao Phraya and the provinces upstream, such as Nonthaburi, Pathum Thani
  and Ayutthaya, where riverine flooding is the main concern.
- **Lives in:** GRP. A daily GEOGLOWS summary per confirmed reach is also the **easiest first
  contribution to Global Risk**: it changes once a day, so the 6-hour cache does no harm, and it
  is never empty (D4). The GEOGLOWS licence must be confirmed first.

### 4.3 Live situation (hours)

- **Purpose:** during flooding, show what is happening now, how sure we are, what changed, and
  which facilities and roads to check. The report is made per shift or on demand.
- **Facts used:**
  - incidents with confidence words and reasons, and their lifecycle events (ADR-0041);
  - facilities with flooding reported nearby, and access under review (ADR-0040);
  - officer checks, time-bound (ADR-0042);
  - cameras near each incident; the planned camera check (water, partial water or dry) once
    BMA permits it;
  - what changed since the last report (slice 7a);
  - per district, the **DDPM baseline joined by code**: shelters and volunteer centres in the
    districts with active incidents. Bangkok has few, which the report says plainly.
- **Exists:** all of it for Bangkok, on the page and in grounded answers. No downloadable shift
  report yet.
- **Missing:**
  - a **shift report** (Word or PDF) built from the fact bundle, with "since last report"
    sections;
  - **a source for other cities.** Floodboard covers Bangkok; before offering this elsewhere,
    check whether any similar open source exists for another city (D5).
- **Lives in:** GRP for the full report. The **districts summary feed** goes to Global Risk (feed
  plan): counts and confidence words only, Bangkok only.

### 4.4 After the event (after-action)

- **Purpose:** what happened, when, where and for how long; which facilities were affected and
  for how long; what the officers saw; where the evidence disagreed.
- **Facts used:** replay over the saved captures (ADR-0044); incident events; the officer review
  history; facility exposure over time.
- **Exists:** replay runs the same engines over saved data.
- **Missing:**
  - an **event summary** (timeline, peak incident count, longest-lasting incidents, facilities
    with the longest nearby flooding);
  - **retention.** Raw downloads are deleted after 14 days and facility states after 7
    (ADR-0045), so an event older than a week cannot be fully rebuilt (D6).
- **Lives in:** GRP. An event footprint could later be contributed to Global Risk, for example as
  a vector or a table.

## 5. The fact bundle

One bundle per **(area, time window, audience)**. It extends the existing slice 7a bundle
(`build_facts`) beyond the live pilot.

```text
FactBundle
  area:      admin codes (province, district or sub-district), from the GRP boundary table
  window:    from, to, and as_of (evidence time) kept apart from run_at (computed time)
  audience:  ddpm_internal | partner | public   # controls which facts may appear
  facts[]:   {id, kind, value, unit, source_id, source_version, rule_version,
              evidence_class, freshness, caveat}
  sources[]: {source_id, licence, credit, retrieved_at, sha256}
  gaps[]:    what is missing, in plain words (never left silent)
```

Rules:

- **Computed, not written.** Every number comes from code that tests can check. AI only words
  the facts, and the gate refuses a number that is not in the bundle (ADR-0043).
- **The audience filters facts, never changes them.**
  - `public` drops officer checks, contact fields, camera data without terms, Longdo content and
    anything under DDPM terms;
  - `partner` is set per agreement;
  - an omitted fact is listed in `gaps` as "not shown to this audience".
- **Wording rules travel with the facts:**
  - "not exposed under this scenario", never "safe";
  - "flooding reported nearby", never "flooded";
  - confidence is a word, never a percentage;
  - population is "registered village population";
  - sensitivity is a relative index;
  - a river trend is never a warning.
- **Versions are pinned.** Every fact carries its source version and rule version (for example
  `IncidentGrouping v0.1`), so a report can be rebuilt and compared later.

Outputs from one bundle:

| Output | For | Status |
| --- | --- | --- |
| Page panels | operators and planners | exists |
| Word document | DDPM briefings, offline | exists for districts (ADR-0033); province, shift and event versions are new |
| Grounded answer | questions on the page or through MCP | exists for the pilot (ADR-0043) |
| Global Risk feed or table | planners elsewhere | planned (feed plan) |
| Partner export | insurers, research (future) | not designed for build; section 8 |

## 6. Which data flows where

```text
              GRP (Hub-owned, detailed)                  Global Risk (exchange, MCP)
  DDPM baseline ──┐                                 ┌── JRC RP10-500, OSM assets, corpus
  Floodboard  ────┤  fact bundles ── reports ──┐    │
  GEOGLOWS    ────┤  (per area, window,        ├──► │ contributed feeds:
  Longdo (ctx)────┤   audience)                │    │  1. GEOGLOWS daily reach summary (D4)
  Officer checks ─┘                            │    │  2. Bangkok districts live
                                               │    │  3. Bangkok incidents live
                                               └──► │ later: province tables, event footprints
                         ◄── risk briefs, receipts ──┘
```

- **Into Global Risk:** summaries only, public-fit, with licences recorded. Never DDPM-sensitive
  records, officer checks, contacts or camera data without terms.
- **From Global Risk:** regional layers and briefs come back as **labelled external evidence**.
  They are never merged into GRP counts (ADR-0023, ADR-0028).

## 7. Order of work

1. **Bangkok live feed, step 1** (endpoint, already planned). It also builds the first piece of
   the fact bundle.
2. **Shift report** for the live pilot, from the same bundle. This is the first new report.
3. **GEOGLOWS daily reach summary** as a contribution candidate, once reaches are confirmed (D3)
   and the licence is checked (D4).
4. **Province pre-season roll-up**, once DDPM samples arrive (D1).
5. **Event summary**, once retention is decided (D6).

## 8. Insurance (future): what to decide now

Insurers would want event history, exposure totals and an audit trail. None of that should be
built now, but these points cannot be fixed later:

- **History is being deleted.** Raw downloads go after 14 days and facility states after 7
  (ADR-0045). Without an event archive, past events cannot be rebuilt. Decide now: keep a compact
  event archive (incident footprints, timelines and rule versions, without raw report data), or
  accept the loss (D6).
- **Rule versions.** Incident grouping is `v0.1` and will change. Every archived record must
  carry its rule version, or old and new events are not comparable.
- **Audit trail.** Global Risk receipts keep only "records via URL", not the fetched rows. An
  auditable trail has to come from GRP, with hashes of what was cited.
- **Licences for commercial use:**

  | Source | Commercial use |
  | --- | --- |
  | Floodboard | CC BY 4.0: allowed with credit |
  | OSM | ODbL: a derived database must stay open (share-alike) |
  | DDPM baseline | needs DDPM's permission |
  | GEOGLOWS | to confirm |
  | Longdo, BMA, cameras | excluded |

- **What the data cannot be:**
  - Crowd and agency reports are **not a payout trigger**. A trigger needs an independent
    measured value, such as an official water level, which we do not have.
  - No report states a **loss**.
- **Channel.** Insurers would need a separate partner channel with an agreement, not the public
  Global Risk feeds.

## 9. Decisions for the owner

- **D1. DDPM samples.** Can you get one DDPM situation report and one pre-season plan (any
  province)? The province and shift reports should follow them rather than our guess.
- **D2. The Bangkok live report's reader.** Is it DDPM central, BMA, or both? This decides the
  wording, and what the `ddpm_internal` audience may see.
- **D3. River reaches.** Who confirms which GEOGLOWS reaches matter, and which districts each
  affects? A hydrologist at ADPC or RID? Until then GEOGLOWS stays "exploratory".
- **D4. First Global Risk contribution.** Should the GEOGLOWS daily summary go first? It changes
  daily and is never empty, so it avoids both feed problems. The Bangkok districts feed would go
  second. Either needs the GEOGLOWS licence checked.
- **D5. Other cities.** Should we look for a Floodboard-like open source outside Bangkok, or keep
  live response Bangkok-only for now?
- **D6. Event archive.** Start a compact event archive now (incidents, timelines, rule versions,
  no raw report data), or keep the 7/14-day retention and accept that past events cannot be
  rebuilt?
