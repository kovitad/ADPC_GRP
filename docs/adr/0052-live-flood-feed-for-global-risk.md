# ADR-0052: a live flood feed for Global Risk, protected by default, public only by switch

## Status

Accepted on 5 October 2026. It builds Step 1 of
[`docs/pilot/2026-10-03_Global_Risk_Live_Feed_Plan.md`](../pilot/2026-10-03_Global_Risk_Live_Feed_Plan.md)
(backlog E1-1). The owner chose the simplest public test: a temporary tunnel in front of a
feed-only relay
([`docs/pilot/2026-10-05_Live_Feed_MCP_Test_Plan.md`](../pilot/2026-10-05_Live_Feed_MCP_Test_Plan.md)).

## Decision

1. **`core/flood_evidence/feed.py`** builds one document from stored data. It has two lists:
   - `records`: one per open incident;
   - `districts`: every pilot district (56), even with no incident, ordered least concern first.

   Fields come from an explicit allow-list. Serialisation is stable, with sorted keys, and the
   ETag is a hash of the body.
2. **Left out:**
   - report text, names and IDs;
   - officer reviews and officer reasons;
   - camera data;
   - DDPM centres: redistribution is not cleared, so facility counts are OpenStreetMap only;
   - Longdo values: depth, report count and evidence time come from Floodboard sources only.
3. **Routes:**
   - `GET /api/v1/pilot/flood/{pilot_id}/feed.json` is `protected`, under the pilot's rules
     (Hub members and Platform Admins; another Hub gets 403). It sends
     `Cache-Control: private, max-age=60`.
   - `GET /api/v1/public/flood/{pilot_id}/feed.json` is `public`. It answers **404 unless
     `FLOOD_FEED_PUBLIC=true`**, so it fails closed. It sends `public, max-age=60` and allows
     30 requests a minute per caller.
   - Both refuse replay IDs, and both support `If-None-Match` (304).
4. **`grpcli/feed_relay.py`** answers only `/feed.json`, by reading the public route. A tunnel
   goes in front of the relay, never in front of the API, which stays on `127.0.0.1`.
5. **Manifests** (`docs/pilot/global_risk_manifests/`) now cover Bangkok and Nonthaburi, and map
   the timestamp field into `fields`. Global Risk's reader sorts by the mapped output field, so
   without it the districts feed was reported as "unsorted".

## Consequences

- **Real data on 5 October 2026:** 65 open incidents and 56 districts, 67 KB, built in under
  2 seconds. No officer, camera, link, DDPM or text fields were found in the body.
- **Global Risk's own code** (`SERVIR-AI/global-platform` at `a8a43c2`):
  - `_validate_feed` passes both manifests with no problems;
  - `_adapt_generic_json` returns the records "sorted newest-last by the feed's own timestamp
    field", with the most concerning districts at the end.
- **Not yet done:** the tunnel, the switch and the staged submission. Each needs the owner's
  yes at the time.
- **A quick tunnel's URL changes on every start**, so approval needs a permanent host (a static
  IP, for example Lightsail).
