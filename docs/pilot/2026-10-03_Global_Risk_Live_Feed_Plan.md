# Bangkok flood live feed to Global Risk: plan

Status: plan, revised on 4 October 2026 after the owner's decisions (end of this file). Nothing
has been submitted or registered. The endpoint is not built yet.

## Goal

Give planners anywhere a live, honest picture of flooding in **the whole of Bangkok** through
Global Risk's MCP tools. We send Global Risk **text only, once**: a short manifest. Global Risk
then fetches our feed live each time someone asks, so there is no repeated submission and no
cost per update.

Example question from any MCP client: "Which Bangkok districts have active flooding now, how
sure are we, and what do the cameras see?" Global Risk calls `feeds_query`, which pulls our feed.

## The standard Global Risk uses (read on 4 October 2026)

`platform_capabilities` lists every feed in one declarative shape. The closest match is the
contributed USGS earthquake feed:

```yaml
title: USGS M4.5+ earthquakes (past month, global)
source: USGS
validation: single-agency
residency: external call-out      # Global Risk fetches the URL at query time
cadence: continuous
adapter: generic_json
fetch:
  url: https://earthquake.usgs.gov/.../4.5_month.geojson
  records_path: features
  as_of_field: time
  fields: {magnitude: properties.mag, place: properties.place, time: properties.time}
pack: risk
hazards: [earthquake, tsunami]
usage_notes: "... NOT filtered to Southeast Asia ..."
contributed: true
```

What this means for us:

- **The manifest is the only thing we submit.** It is a small JSON text with these fields. Our
  data stays on our server and every query is a live pull.
- **The other option costs more.** `residency: platform-hosted copy` (used by
  `btb_station_rainfall`) stores a fixed file with its SHA-256. A live feed would then need a new
  submission and review for every update. We do not use it.
- **Review comes before going live.** `contribute_submit` now says a clean submission is
  **staged**. Only we and the reviewers can see it until a reviewer approves it. This gives us a
  safe test before anyone else sees it (ADR-0032 described auto-approval; the tool text now says
  otherwise, so we confirm this with the maintainers).
- **Global Risk must reach our URL.** Docker Desktop cannot be reached from outside, so a public
  HTTPS host is still the real blocker (Step 3).

## What the platform source code shows (read on 4 October 2026)

Source: <https://github.com/SERVIR-AI/global-platform>, commit `a8a43c2`. Files:
`apps/api/src/app/mcp/feeds.py`, `contrib/staging.py`, `contrib/feedspecs.py`,
`contrib/fetch_policy.py`, `mcp/climate_indices.py` and `risk/synthesis.py`.

**What works in our favour:**

- **The manifest rules are confirmed.** Required fields are `dataset`, `title`, `description`,
  `source`, `validation`, `residency`, `cadence`, `adapter` and `fetch` (`url`, `records_path`,
  `fields`). Optional fields are `usage_notes` (500 characters at most), `pack`, `countries`,
  `hazards`, `license` and `vintage`.
  - **Unknown fields are refused.** The `_status` line in our drafts must come out before
    submitting.
- **Staging is real.** A clean submission is stored as `pending` and served only to us and the
  reviewers. Approval writes `conf/feeds/<dataset>.yml`.
  - Withdrawing removes the staged row, so the **same name can be submitted again**. A name is
    spent only once it is approved.
- **The submission test is live.** The platform fetches our URL once when we submit. A dead URL
  or an empty record list is refused, not staged.
- **Values are read as-is.** `fields` values are dot paths into each record, so lists and nested
  objects pass through unchanged.
- **Records are sorted by `as_of_field`**, oldest first. The newest `limit` records are returned
  (12 by default). A risk brief asks for 3.
- **Risk briefs read contributed feeds automatically.** `risk/synthesis.py` cites every feed in
  the `risk` pack whose `hazards` include the hazard asked about. A flood question will cite our
  feed with no extra work.
- **The URL must be public.** `http` or `https` is fine, but it may not resolve to a private
  address, and it cannot carry credentials. The fetch sends no custom headers, so **the feed must
  be anonymous**. A token is not possible.

**Two problems we must design around:**

1. **A 6-hour cache.** `generic_json` goes through `climate_indices.cached`, whose TTL is 6
   hours, written for monthly climate indices. Global Risk can therefore serve our "live"
   incidents up to 6 hours old. It does say so: `stale_data.retrieved_at` is reported, but it is
   still old data.
   - We cannot fix this from our side, because unknown manifest fields are refused. **We ask the
     maintainers for a per-feed TTL** (question 1).
   - Meanwhile every record carries its own `valid_until`, mapped into `fields`. A reader then
     sees the record is stale even when it comes from cache.
2. **An empty list counts as a failure.** If `records` is empty, the adapter treats it as
   "upstream unavailable". It serves the last good copy marked stale, or declines.
   - On a dry day, Global Risk would show **old incidents** instead of "no flooding". The
     submission test would also refuse the feed.
   - So the **`districts` list (always 50 rows) is submitted first and is the main feed**. The
     incidents feed goes second, and we ask the maintainers to accept an empty list as a valid
     answer (question 2).

**Two more things to note:**

- **Not filtered by place.** Risk briefs filter feeds by `hazards` only, not by `countries` or
  place. A flood brief for any country could cite our Bangkok feed.
  - `usage_notes` must start with "Bangkok only".
  - We ask the maintainers whether `countries` can filter risk briefs too (question 4).
- **Replay.** A receipt keeps only `query_receipt` ("records via URL"), not the fetched bytes.
  Replaying an answer after the feed has changed cannot show what was cited, so we ask about this
  (question 5).

**Design changes that follow:**

| Item | Change |
| --- | --- |
| District order | `districts` records share one `as_of`, so the sort keeps our order. We publish them **least concern first**, so the default 12, or a brief's 3, are the worst districts |
| Incident time | `as_of_field: last_evidence_at`, so the newest evidence comes last and is returned first |
| Staleness | `valid_until` on every record, not only at feed level |
| Submission order | districts first (never empty), incidents second |
| `usage_notes` | starts "Bangkok only"; tells readers to pass `{limit: 50}` for every district |

## What goes in the feed (v1, whole Bangkok)

One document, `feed.json`, with two record lists. Each list can be registered as its own
manifest, because a manifest reads exactly one `records_path`.

### `records`: one per open incident

| Field | From | Note |
| --- | --- | --- |
| `incident_id` | incident store | stable across snapshots |
| `status` | incident | `active` or `receding` |
| `confidence` | incident | `low`, `medium`, `high` or `conflicting`; a word, never a number |
| `confidence_reasons` | incident | short codes such as `two_families` and `official_source` |
| `source_families` | incident | such as `["traffy","crowd"]`; names of source types only |
| `district_codes`, `district_names_en`, `district_names_th` | outlines | every district its roads touch |
| `road_names_en`, `road_names_th` | Floodboard roads | public road names, empty ones dropped |
| `lon`, `lat`, `bbox` | incident | centre and box; no line geometry |
| `max_depth_cm` | Floodboard only | `null` when no Floodboard source gave a number |
| `report_count` | Floodboard only | reports from Floodboard sources |
| `facilities_nearby` | exposure | counts by type: `{school, hospital, clinic}`; "flooding reported nearby", never "flooded" |
| `camera_check` | camera check (Step 2) | `water`, `partial_water`, `dry` or `cannot_tell`, with `checked_at` and `cameras_checked`; `null` until built |
| `first_seen`, `last_evidence_at` | incident | ISO UTC |
| `valid_until` | feed | copied into every record, because Global Risk's adapter reads records only |
| `evidence_class` | pilot | `crowd_only`, `official_only` or `crowd_and_official_mix`; never `verified` |

Records are in a fixed, neutral order (`first_seen`, then `incident_id`). Order must never leak
an officer's judgement.

### `districts`: one per Bangkok district, all 50

| Field | Note |
| --- | --- |
| `district_code`, `district_name_en`, `district_name_th` | every district appears, even with no incidents |
| `active_incidents`, `receding_incidents` | counts |
| `worst_confidence` | highest-concern word among active incidents, or `null` |
| `facilities_nearby` | counts by type across its incidents |
| `camera_check_summary` | counts of `water`, `partial_water`, `dry` and `cannot_tell` |
| `as_of`, `valid_until` | copied from the feed level into every district record |

Districts are published **least concern first** (no incidents, then low, medium, high,
conflicting, then by active count). All 50 share one `as_of`, so Global Risk's sort keeps this
order and its default "newest" tail returns the worst districts.

A district with zero incidents says `0`. It is never missing, so absence is never read as "no
data".

### Feed-level fields

- `run_at`: when the incidents were last computed (the worker run), not the request time.
- `checked_at`: the last successful Floodboard roads fetch. On 4 October 2026 roads were fetched
  every 10 minutes, but incidents were recomputed only when the export changed (gaps of up to
  80 minutes), so `run_at` alone would make a healthy feed look stale.
- `as_of`: the newest evidence time.
- `valid_until`: `checked_at` plus 30 minutes, which is three missed fetches. A reader can tell
  when the feed is stale, even if our worker has stopped.
- `coverage`: Bangkok, 50 districts.
- `sources`: each upstream source with its licence and credit, read from the pilot config.
- `limits`: the standing caveats in plain words. These are estimates, not a flood map. There are
  no water-level sensors. Rain is not flooding. Camera checks are a machine's reading of one
  picture.

If no incident run exists yet, the feed is empty, with `run_at`, `checked_at` and `valid_until` set to `null`.

### Left out on purpose

These stay out until the gates below are passed:

- **Report text, contributor names, photos and IDs.** We never store them.
- **Officer reviews and anything officer-confirmed**, including `verification`, `access_to_check`
  and facility access states. These are internal.
- **Camera URLs, camera IDs and pictures.** Only the one-word camera check result can be added,
  after Gate B.
- **Longdo rain and Longdo event content.** The redistribution terms are not stated. Incidents
  keep `doh`, `itic` or `longdo_user` in `source_families`, but `max_depth_cm`, `report_count`
  and `last_evidence_at` are computed from Floodboard sources only, so no Longdo value leaks.

### Licence status

| Source | For the feed |
| --- | --- |
| Floodboard roads | CC BY 4.0, redistribution allowed with attribution (recorded in the pilot config). A short confirmation is drafted. |
| Floodboard reports | CC BY 4.0 for the export; quoted text is not cleared, and we never use it |
| OSM facilities | ODbL; credit "© OpenStreetMap contributors"; counts only |
| Longdo events and rain | excluded until written terms |
| BMA, bmatraffic and Longdo cameras | excluded until written terms; this covers the camera check result too |

## The camera check: water, partial water or dry

The owner asked for a simple, cheap reading of what the live cameras see.

**What it does.** For each **active** incident, take the latest picture from up to **2 cameras
within 400 m**. A vision model answers with one word: `water`, `partial_water`, `dry` or
`cannot_tell`. Night, glare, a blank frame or an unclear view give `cannot_tell`.

**How it stays cheap:**

| Rule | Effect |
| --- | --- |
| Active incidents only, never all 1,413 cameras | about 44 incidents at a busy moment (4 October capture) |
| At most 2 cameras per incident | about 88 pictures per round |
| One round every 15 minutes, while the incident is active | at most about 350 checks an hour |
| Picture shrunk to 320 × 180 before sending | about 80 image tokens |
| A fixed short prompt, answer limited to a few tokens | about 160 input and 5 output tokens per check |
| Skip if the picture is unchanged (same hash) or the camera answered in the last 15 minutes | fewer calls when flooding is steady |

Estimate with Claude Haiku 4.5 ($1 per million input tokens, $5 per million output tokens):
about $0.0002 a check, so **about $0.07 an hour, or $1.70 a day, in the worst case of
continuous heavy flooding**. A dry day costs close to nothing, because no incident is active.

**Rules that keep it honest:**

- It runs in the worker, never in a web request, and goes through `api/ai_gateway.py`, the only
  module allowed to call an AI provider. The gateway speaks an OpenAI-style API today; a vision
  call needs a small extension there.
- The result is labelled as a machine reading of one picture, with time and camera count. It is
  shown beside the officer checks and **does not change the confidence word in v1**.
- Pictures are never stored. Only the word, the time and a hash of the picture are kept.
- First source: bmatraffic pictures through the local relay (ADR-0051), which already arrive as
  JPEG. Longdo HLS would need a frame grab and comes later.
- A daily cap (for example 5,000 checks) stops cost running away. When it is reached, the result
  is `cannot_tell` with the reason `daily_cap`.

## Steps

### Step 1: the feed endpoint (local, Gate A)

- `GET /api/v1/pilot/flood/{pilot_id}/feed.json`, labelled `x-grp-access: protected` for now
  (decision 2).
  - Hub members get 200, other Hubs 403, anonymous callers 401.
  - The pilot comes from `pilot_config` only. A replay ID never resolves, so it gives 404.
  - Access is one small dependency, so making the route public later is a one-line change.
- `core/flood_evidence/feed.py` builds the document as a pure function from stored incidents,
  roads, reports, exposure and the config. Records are built from an explicit allow-list of
  fields.
- Serialisation is deterministic (sorted keys and records). The `ETag` is a hash of the body,
  `If-None-Match` gives 304, and the response sends `Cache-Control: private, max-age=60`.
- Tests:
  - shape, empty state and all 50 districts present;
  - no free text, usernames, camera or rain fields;
  - an incident with an officer review gives a **byte-identical** feed to one without;
  - Longdo-only reports change no number;
  - an incident crossing a district border lists both districts;
  - replay gives 404, and the permission cases above.
- ADR-0052 records the route, the fields and the exclusions.

### Step 2: the camera check (local, Gate A for the build, Gate B to publish it)

- `core/flood_evidence/camera_check.py`, a worker job, a small table for results, and the
  gateway extension.
- Tests with a fake provider: the four labels, the cap, unchanged-picture skipping, and no
  picture stored.
- ADR-0054. It goes into the feed only after Gate B.

### Step 3: the public host (decision 3: the Ubuntu GRP deployment over HTTPS)

- Run the Ubuntu deployment for the first time and choose a permanent domain. The manifest points
  at it for good.
- Flip the feed route to `public` in the same change, with a rate limit.
- Fallback if the VM is slow to arrive: the worker writes `feed.json` every 5 minutes to static
  HTTPS storage. This needs the owner's yes, because it is a new moving part.

### Step 4: staged test on Global Risk (Gate C, explicit yes at the time)

1. The manifests are already drafted in `docs/pilot/global_risk_manifests/`. Review them
   together.
2. Send the maintainer questions (`docs/pilot/2026-10-04_Global_Risk_Maintainer_Questions.md`).
3. Remove the `_status` line, then submit the **districts** manifest first, because it is never
   empty. It is **staged**, visible only to us and the reviewers.
4. Check it with `feeds_query("bangkok_flood_districts_live", {"limit": 50})` and
   `contribute_status`. Then submit the incidents manifest on a day with flooding, since an empty
   list is refused.
5. If the shape is wrong, withdraw it with `contribute_status(action="withdraw")` before review.

### Step 5: go live

- A reviewer approves both. Before going live, the 6-hour cache must be answered (maintainer
  question 1); otherwise usage_notes must say values can be up to 6 hours old.
- Planners anywhere use `feeds_query`. Later, `assemble_pack(pack="risk", place="Bangkok",
  hazard="flood")` could cite the live feed beside the static JRC flood layers.

## Cost of submitting

- **One-off:** two manifest submissions, about 2 KB of text each. No data is uploaded.
- **Ongoing:** nothing to Global Risk. Our only costs are the host and, if built, the camera check
  (about $1.70 a day at most, as above).

## Risks

| Risk | Mitigation |
| --- | --- |
| Name spent on a wrong manifest | staged test first, withdraw before review if wrong, owner reviews the draft |
| Licence breach (Longdo, cameras, rain) | excluded in code and tested; Gate B before any change |
| Officer judgements leak | allow-listed fields, neutral order, byte-identical test |
| Readers take estimates as fact | confidence words, `limits`, `usage_notes`, `validation: unvalidated` |
| Camera check wrong at night or in rain | `cannot_tell` is allowed and expected; it never changes confidence in v1 |
| Camera check cost runs away | active incidents only, 2 cameras, 15 minutes, unchanged-skip, daily cap |
| Stale feed after an outage | `valid_until` from the last good fetch, not from the request |
| Host URL changes | choose the permanent domain before Step 4 |
| Replay data leaks | the route never resolves replay IDs; tested |

## Gates

- **Gate A (now, local):** Steps 1 and 2 built and tested, ADRs and drafts written. No outward
  calls.
- **Gate B (terms):** written terms from BMA, Longdo and bmatraffic before any camera-derived or
  Longdo field enters the feed. Floodboard: confirmation of the credit wording.
- **Gate C (publish):** the public host, then the staged submission, then going live. Each needs
  the owner's explicit yes at the time.

## Decisions for the owner (answered 4 October 2026)

1. **Feed scope:** incidents **and** a district summary. The summary is a separate `districts`
   list, registered as its own manifest.
2. **Public route:** keep it `protected` until the public host exists.
3. **Host:** the Ubuntu GRP deployment over HTTPS (A).
4. **Name:** `bangkok_flood_incidents_live` is kept. The district list is
   `bangkok_flood_districts_live`.
5. **Floodboard licence:** "don't worry, just do it". A short confirmation request is drafted in
   `docs/pilot/2026-10-04_Floodboard_Licence_Confirmation.md`. The config already records CC BY
   4.0, so this confirms the credit wording rather than asking for permission. It has not been
   sent.
6. **Maintainer questions:** "just do it". Drafted in
   `docs/pilot/2026-10-04_Global_Risk_Maintainer_Questions.md`. Not sent.

Also decided on 4 October 2026:

- **Whole Bangkok** (ADR-0053).
- A simple **camera check** that answers water, partial water or dry, kept cheap.
