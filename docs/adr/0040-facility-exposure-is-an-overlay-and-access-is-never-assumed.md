# ADR-0040: Facility exposure is an overlay, and access is never assumed

## Status

Accepted on 3 October 2026 for a local demo (Gate A). This is slice 4 of the Bangkok flood pilot
plan, in the Bang Sue and Chatuchak corridor. The Product Owner chose OpenStreetMap for schools
and hospitals, to be replaced by authoritative BMA lists when available.

## Context

- **Screen 3 of the owner's expected outcome** asks which schools and hospitals are near flooding,
  which may lose access, and where to check.
- **The integration tweak:**
  - spatial overlay gives only *potential* exposure;
  - access needs a road network and justified rules;
  - states are reported separately: `potentially_exposed`, `access_under_review`,
    `access_disrupted_confirmed` and `access_unknown`;
  - a missing road graph gives `access_unknown`, never "accessible" (scenario 8).
- **Spec FB-4:** a hospital is not "flooded" because its access road is.
- **GRP has no road network today.** Floodboard's segments are flood states, not a routable graph.
- **AGENTS.md:** spatial work runs in the worker, never in a web request.

## Decision

1. **Facilities are captured once.**
   - `python -m grpcli.osm_assets_capture --pilot bangkok` asks Overpass for `amenity` school,
     hospital and clinic. It keeps those inside the corridor's district outlines and writes
     `core/data/flood_pilot_bangkok_assets.json`, holding the OSM timestamp, the query and ODbL
     attribution.
   - On 3 October this gave **52 facilities: 32 schools, 10 hospitals and 10 clinics.**
   - No web request or worker pass calls Overpass.
   - The file is refused whole if any entry is unclear: unknown type, outside the region, a
     missing field or a repeated ID.
2. **Two separate answers per facility** (`core/flood_evidence/assets.py`, `FacilityExposure v0.1`):
   - **Exposure:** `potentially_exposed` when a road with flooding reported now lies within
     `near_m` (150 m). Otherwise `no_report_nearby`, shown as "no report, which is not the same
     as dry".
   - **Access:** `access_under_review` when a road within `frontage_m` (60 m) is reported closed
     to all traffic, or Floodboard rates it risky or impassable for a truck. Otherwise
     `access_unknown`, always with the reason `no_road_network`.
   - **Never set by GRP:** "accessible", and `access_disrupted_confirmed`, which is reserved for
     an officer's check (slice 5).
   - Both distances are pilot configuration, labelled on the page as demo settings rather than
     validated rules.
3. **Only current evidence counts:** an uncleared segment whose freshness is current, recent or
   aging. Distance is measured point-to-segment in a local flat projection.
4. **The worker computes; the API reads.**
   - After each good roads snapshot, `ingest_body` calls `store_exposure`, which writes one
     `flood_asset_exposure` row per facility for that fetch (migration `20261003_0023`).
   - `GET /api/v1/pilot/flood/{pilot_id}/assets` returns the rows of the latest good snapshot.
     It is `protected` and open to pilot operators.
   - A facility not yet assessed against that snapshot says `not_assessed` rather than guessing.
5. **On the page:**
   - H, C and S markers, coloured by state;
   - two cards: facilities with flooding nearby, and of those, access to check;
   - a facility card with the distance, a link to the nearest flooded road, the access reason,
     the OSM label and the rule version;
   - the road evidence card lists the facilities that road affects;
   - a shareable `?facility=` link;
   - facility names are set as text only.

## Consequences

- **On live data at 10:35 on 3 October**, two facilities were potentially exposed:
  - Kasemrad Prachachuen Hospital, 78 m from a flooded road;
  - Atthamit School, 69 m.

  Access for both stayed unknown.
- Replacing OSM with BMA lists is a data change, not a code change. So is extending to more
  districts: re-run the capture with a wider corridor.
- **Rows grow by one per facility per roads pull,** about 7,500 a day for 52 facilities. They are
  covered by the retention rule required before Gate B.
- **Not done here:**
  - population exposure;
  - a road network and routing, so access can move beyond "unknown";
  - officer confirmation of access;
  - authoritative facility lists.

## Amendment, 3 October 2026 (later)

- The owner added **Bang Kapi (1006) and Lat Krabang (1011)** to the demo area, which is now four
  districts. The districts do not touch, so the capture asks Overpass for one box per district.
- The re-run file holds **94 facilities**: Bang Sue 12, Chatuchak 40, Bang Kapi 22 and
  Lat Krabang 20.
