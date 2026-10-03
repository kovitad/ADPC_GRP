# Bangkok flood live feed to Global Risk: plan

Status: plan only, 3 October 2026. Nothing has been submitted or registered, and no endpoint has been built.

## Goal

Publish a small, honest, machine-readable live feed from the Bangkok flood pilot. Global Risk registers it once as a contributed feed, and any MCP client can then read it with `feeds_query`, for example: "which incidents in Bang Sue are active and how confident are we?"

## What Global Risk already supports (read on 3 October 2026)

`platform_capabilities` lists one contributed live feed of exactly the kind we need: `usgs_quakes_m45_month`.

```yaml
adapter: generic_json
residency: external call-out        # Global Risk fetches our URL at query time
fetch:
  url: https://earthquake.usgs.gov/.../4.5_month.geojson
  records_path: features
  as_of_field: time
  fields: {magnitude: properties.mag, place: properties.place, time: properties.time}
pack: risk
hazards: [earthquake, tsunami]
contributed: true
```

So the pattern is: we serve a public JSON document, and Global Risk stores only a declarative manifest that says where to fetch it and which fields to keep. Our data stays with us, and every `feeds_query` is a live pull.

Two consequences:

1. **Global Risk must be able to reach the URL.** The pilot runs on Docker Desktop, which Global Risk cannot reach. A real feed therefore needs a public HTTPS host first (the Ubuntu deployment, or a small static mirror). This is the main blocker, not the code.
2. **Registration is permanent and probably public at once.** ADR-0032 notes that this deployment auto-approves contributions and that a name can never be overwritten. One wrong name or one wrong licence stays forever.

## What goes in the feed

One record per **active or recently closed incident** (the pilot's main product, already deduplicated and confidence-rated). Road and report rows stay inside GRP.

| Field | From | Note |
| --- | --- | --- |
| `incident_id` | incident store | stable across snapshots |
| `status` | incident | active, receding, closed |
| `confidence` | incident | low, medium, high or conflicting; a word, never a probability |
| `confidence_reasons` | incident | short codes, e.g. `two_families`, `official_source` |
| `source_families` | incident | e.g. `["traffy","crowd"]`; counts only, no usernames |
| `report_count` | incident | |
| `road_names` | Floodboard road keys | the public road names only |
| `district_code`, `district_name_en`, `district_name_th` | outlines | |
| `lon`, `lat`, `bbox` | incident | centre and box; no line geometry in v1 |
| `max_depth_cm` | observations | only when a source gave a number; otherwise `null` |
| `first_seen`, `last_evidence_at` | incident | ISO UTC |
| `facilities_nearby` | exposure | counts by type (school, hospital, clinic) only; "flooding reported nearby", never "flooded" |
| `evidence_class` | pilot | always `crowd_and_official_mix` or narrower; never `verified` |

At the feed level (outside `records`):

- `run_at`: when the document was made;
- `as_of`: the newest evidence time;
- `valid_until`: `run_at` plus 15 minutes, so a reader can tell when the feed is stale;
- `coverage`: the four demo districts, with their codes;
- `sources`: each upstream with its licence and credit;
- `limits`: the standing caveats in plain words (estimates, not a flood map; no sensors; rain is not flooding).

This answers the questions ADR-0036 left open: run time is `run_at`, valid time is `valid_until`, and reach scope is `coverage`.

### Left out on purpose

- **Report text, contributor names, photos and IDs.** We never store them, so they cannot leak.
- **Camera URLs.** BMA, Longdo and bmatraffic have not given written permission to redistribute them (Gate B). The feed may later say `cameras_within_400m: 2` once terms allow.
- **Longdo Weather rain.** The terms are "provided as is", with no redistribution right confirmed. Rain stays in GRP's own page.
- **Longdo events.** Same reason. Incidents whose evidence includes Longdo or DOH events keep them in `source_families`, but the event content stays out.
- **Officer reviews.** These are internal judgements and stay protected.

### Licence check before anything is published

Each source has to allow redistribution of facts derived from it. The incident record is derived data, but the credit and licence must still pass through:

| Source | Status for the feed |
| --- | --- |
| Floodboard roads and reports (BMA, Traffy, crowd) | need to confirm the exact licence text on floodboard; record it in `sources` |
| Longdo events (DOH, iTIC, users) | **excluded until written terms** |
| BMA DDS, bmatraffic, Longdo cameras | **excluded until written terms** |
| OSM facilities | ODbL: credit "© OpenStreetMap contributors"; counts only |

If the Floodboard terms are not clear, v1 publishes only a **synthetic** feed (see Step 3).

## Steps

### Step 1: a GRP feed endpoint (in the repo, safe)

- `GET /api/v1/pilot/flood/{pilot_id}/feed.json`, labelled `x-grp-access: public`, read-only, and served from the latest stored snapshot only. The web request does no upstream or GIS work, keeping to the worker rule.
- Live pilots only. Replays answer 404, so a replay can never leak into Global Risk.
- `Cache-Control: max-age=60`, an `ETag` from the snapshot hash, and a small rate limit.
- New code `core/flood_evidence/feed.py` builds the document from `list_incidents`, exposure and the config. It is a pure function, so it can be tested offline.
- Tests (`tests/fast/test_flood_feed.py` and the permission matrix):
  - the shape is a list of flat records;
  - no free text and no usernames;
  - no camera or rain fields;
  - a replay returns 404;
  - `valid_until` is set;
  - excluded sources never appear;
  - anonymous access works, and write methods are refused.
- ADR-0052 records the access decision (the first public pilot route), the field list and the exclusions.

**Owner decision:** making this route public is new. Until a host is ready, we could keep it `protected` and switch it to public only once that host exists.

### Step 2: a public host (deployment, needs approval)

Pick one:

- **A. The Ubuntu GRP deployment over HTTPS (recommended).** The feed comes straight from the live database.
- **B. A static mirror.** The worker writes `feed.json` every 5 minutes to object storage behind HTTPS. This is simpler to expose and keeps the API private, but adds one more moving part.

Either way the URL must be stable for good, because the Global Risk manifest points at it permanently.

### Step 3: a dry run against Global Risk (needs approval, Gate A)

1. Write the manifest locally in `deliverables/global_risk/bangkok_flood_incidents.manifest.json` and review it together. Nothing is sent.
2. Ask the Global Risk maintainers whether the `feed` kind accepts an external `generic_json` URL. The kind exists in `contribute_submit`, but its required fields were not visible. Also ask whether a **test namespace** exists.
3. If there is no test namespace, the first submission is a deliberately synthetic, clearly named feed (e.g. `grp_pilot_feed_contract_test`, described "SYNTHETIC, contract test"). It points at a fixed synthetic file, which proves the adapter reads our shape without spending the real name.
4. `contribute_status` and `feeds_query` check that the records come back as expected.

### Step 4: register the real feed (needs explicit approval)

Proposed manifest (draft):

```json
{
  "dataset": "bangkok_flood_incidents_live",
  "title": "Bangkok flood incidents (live pilot, four districts)",
  "description": "Flood incidents on Bangkok roads, grouped from Floodboard road ratings and public reports by the GRP Bangkok pilot. Each record has a confidence word with reasons. Estimates from crowd and agency reports, not a flood map and not verified on the ground. Covers Bang Sue, Chatuchak, Bang Kapi and Lat Krabang only.",
  "source": "ADPC GRP Bangkok flood pilot (derived from Floodboard: BMA, Traffy Fondue and public reports)",
  "validation": "unvalidated",
  "residency": "external call-out",
  "cadence": "every 5 minutes",
  "adapter": "generic_json",
  "fetch": {
    "url": "https://<public-host>/api/v1/pilot/flood/bangkok/feed.json",
    "records_path": "records",
    "as_of_field": "last_evidence_at",
    "fields": {
      "incident_id": "incident_id", "status": "status", "confidence": "confidence",
      "district": "district_name_en", "roads": "road_names", "lat": "lat", "lon": "lon",
      "max_depth_cm": "max_depth_cm", "reports": "report_count",
      "families": "source_families", "last_evidence_at": "last_evidence_at"
    }
  },
  "pack": "risk",
  "hazards": ["flood", "flashflood"],
  "countries": ["Thailand"],
  "license": "<confirmed Floodboard licence>",
  "usage_notes": "Confidence is a word with reasons, not a probability. 'Facilities nearby' means flooding reported near them, not that they are flooded. Check valid_until: older records are stale. Rain is not included."
}
```

`validation: "unvalidated"` is deliberate: no field checks have been run yet. It can become `single-agency` only once BMA confirms the data.

### Step 5: use it through MCP (later)

Once the feed is registered:

- `feeds_query("bangkok_flood_incidents_live", {...})` gives any MCP client the current incidents with their confidence.
- `assemble_pack(pack="risk", place="Bang Sue", hazard="flood")` could cite the feed beside the static flood rasters, so live incidents sit next to the JRC return-period hazard.
- `publish_answer` and `record_receipt` make an answer replayable. Because a live feed changes, the receipt must keep the `run_at` and hash of the document it cited. Ask the maintainers whether `generic_json` call-outs already keep the fetched bytes.
- GRP's own `integrations/sig` can then read the feed back as a check that the round trip works.

## Risks

| Risk | Mitigation |
| --- | --- |
| Name spent on a wrong manifest | synthetic contract test first; draft reviewed by the owner; maintainers asked about a test namespace |
| Auto-approve makes it public at once | publish nothing that is not already fit to be public; exclusions above |
| Licence breach (Longdo, cameras, rain) | excluded in code and tested; Gate B before any change |
| Readers take estimates as fact | confidence words, `limits`, `usage_notes`, `validation: unvalidated` |
| Stale feed after a pull outage | `valid_until`; `as_of` from evidence, not from `run_at`; the source health already tracked |
| Host URL changes later | choose the permanent host before registering |
| Replay data leaks | the feed route refuses replay IDs, and a test covers it |
| Load from Global Risk call-outs | cache, ETag, rate limit; the document is precomputed |

## Gates

- **Gate A (now, local):** Step 1 only: the endpoint, its tests, the ADR and the manifest draft. No outward calls.
- **Gate B (terms):** written terms from Floodboard (for redistribution), and later from BMA, Longdo and bmatraffic, before any of their fields are added.
- **Gate C (publish):** the public host, the synthetic contract test, then the real registration. Each needs the owner's explicit yes at that moment.

## Decisions for the owner

1. **Feed scope.** Is "incidents only" right for v1, or do you also want a per-district summary record (active count, worst confidence)?
2. **Public route.** Make the feed route `public` now (Step 1), or keep it `protected` until a host exists?
3. **Host.** Use the Ubuntu deployment (A) or a static mirror (B)?
4. **Name.** Is `bangkok_flood_incidents_live` acceptable? It can never be changed.
5. **Floodboard licence.** Who confirms it: you, or should I draft a short request like the BMA one?
6. **Maintainer questions.** Should I draft the questions to the Global Risk maintainers about the `feed` kind, a test namespace and receipts for live call-outs?
