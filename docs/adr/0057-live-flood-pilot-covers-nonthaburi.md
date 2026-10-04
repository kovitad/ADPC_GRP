# ADR-0057: the live flood pilot covers Nonthaburi, with Pak Kret's public cameras

## Status

Accepted on 4 October 2026 by the Product Owner ("ok go go ahead"), after the validation in
[`docs/pilot/2026-10-04_Nonthaburi_Expansion_Validation_and_Plan.md`](../pilot/2026-10-04_Nonthaburi_Expansion_Validation_and_Plan.md).
It extends ADR-0053 (whole Bangkok), ADR-0051 (picture relay) and ADR-0056 (Planner live data).

## Context

- Floodboard's export already covers Nonthaburi: 314 road segments and 82 reports in 24 hours,
  across all six districts.
- Pak Kret City Municipality publishes 52 cameras. Each has a public JPEG snapshot that needs no
  login. No terms are stated.
- DDPM's delivery has 64 usable evacuation centres in Nonthaburi, and none in Bangkok.
- The pilot was built around Bangkok: its district outlines came from the River Watch file, and
  "live" was a `10` code-prefix check.

## Decision

1. **Area list.** `demo_corridor.areas` adds 1201-1206; the title is "Bangkok and Nonthaburi
   (56 districts)". The pilot ID stays `bangkok`, so stored data and archive paths do not change.
   Rain stays on the four `rain_areas`.
2. **Outlines.**
   - `core/flood_evidence/areas.py` reads `core/data/flood_pilot_bangkok_areas.json`, which holds
     all 56 districts.
   - The file is captured once from the GRP boundary table (2025-10 edition, simplified) by
     `python -m grpcli.flood_pilot areas`. If the file is missing, the River Watch Bangkok
     outlines are used.
   - Every user of the outlines reads them through it: incidents, briefing, weather, the archive,
     the Planner layer and answers, the pilot's area route and the OSM capture.
3. **"Live" means "in the pilot area".**
   - `in_pilot(config, code)` replaces the `10` prefix checks; sub-districts roll up.
   - The Planner page gets `live_flood_areas` in `GET /api/v1/maps/layers` (empty for a Hub the
     pilot does not include).
   - Wording reads "Bangkok and Nonthaburi".
4. **Pak Kret cameras.**
   - `grpcli/pakkret_cameras_capture.py` builds
     `core/data/flood_pilot_bangkok_cameras_pakkret.json` (52 cameras, provider `PAKKRET_CCTV`,
     access mode `snapshot`).
   - A map point's number is the camera's ID number; the list position is not.
   - `core/flood_evidence/snapshot_relay.py` relays a picture only from the registry address,
     with the same limits as ADR-0051: on demand, once a second per camera, 8 a second overall,
     never stored. It runs only when the relay is enabled.
   - The cache-busting time is appended to the address, because httpx's `params` would drop the
     camera's `name=`.
   - **Pictures are shown on screen only, not put in downloaded reports**, until the municipality
     replies (`docs/pilot/2026-10-04_Pak_Kret_CCTV_Request.md`).
   - The 21 Longdo copies of the same cameras are not added.
5. **Not used.**
   - The World Flood CCTV aggregator: it does not own the cameras, and it discourages automated
     use.
   - The Nakhon Nonthaburi GIS: it has no public interface, and reverse-engineering is ruled out.
     A feed request is drafted (`docs/pilot/2026-10-04_Nakhon_Nonthaburi_Camera_Feed_Request.md`).

## Consequences

- **Cameras exist only in Pak Kret** (51 of 52; one falls in Lak Si, Bangkok). The other five
  Nonthaburi districts show reports and facilities without camera views.
- **OSM facilities for Nonthaburi are not captured yet.** Overpass timed out on 4 October 2026,
  from the main server and from `overpass.kumi.systems`. The capture now asks in groups of ten
  districts and takes `--overpass`. Run it again later. DDPM centres already cover Nonthaburi.
- Nonthaburi incidents appear from the first roads snapshot processed after deployment.
