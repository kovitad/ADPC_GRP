# ADR-0039: CCTV P0 is a registry and an official-viewer link, never evidence

## Status

Accepted on 3 October 2026 for a local demo (Gate A). This is slice 3 of the Bangkok flood pilot
plan, in the demo corridor of Bang Sue and Chatuchak. The Product Owner chose to ask BMA for the
camera list. Until it arrives, the registry holds only labelled test entries.

## Context

- **Spec v0.3** makes CCTV a first-class visual source, but only through authorised access
  modes. P0 is the registry, nearest camera, provider viewer, health and provenance. Reverse
  engineering streams is forbidden.
- **The integration tweak** says:
  - the nearest camera is a discovery hint, not proof that it can see the incident (scenario 4);
  - a viewer-only camera is never passed to snapshot or CV processing (scenario 5);
  - an unavailable camera never means the road is dry.
- **No licensed camera list exists:**
  - the community catalogue has no licence;
  - Floodboard's `robots.txt` disallows `/api/cam/`;
  - floodbangkok.bangkok.go.th has no documented API.
- **The corridor's flooding (10:10, 3 October)** rested on Traffy reports alone, so cameras are
  the most useful independent check there.

## Decision

1. **A provider-neutral registry file per pilot:** `core/data/flood_pilot_<pilot>_cameras.json`.
   - It is read by `core/flood_evidence/cameras.py`. The core holds no provider-specific URL
     logic.
   - Fields follow the tweak's T3 list: ID, provider, location, heading and field of view,
     related sensors, viewer, snapshot and stream URLs, access mode, status and its check time,
     rights, retention, `ingestion_allowed`, `cv_allowed` and `placeholder`.
2. **The registry fails closed. The whole file is refused when:**
   - an access mode or status is unknown;
   - a URL is not `https://`;
   - a stream or snapshot URL appears without the matching mode;
   - an embed or external-viewer camera has no viewer;
   - CV is allowed on anything other than an authorised frame source;
   - an entry is placed outside the region;
   - a camera ID repeats;
   - a placeholder carries links or ingestion rights.
3. **Placeholders are honest.**
   - They use the `PLACEHOLDER` provider, have no links, and carry names that say "not a real
     camera".
   - The page labels them "test entry", draws them hollow, and says the list is waiting for BMA.
4. **P0 never confirms anything.** `corroboration_role` returns at best `officer_can_look`. Every
   reason a camera cannot help is listed:
   - placeholder;
   - offline or unknown status;
   - health not checked in 30 minutes;
   - no viewer;
   - view direction unknown;
   - facing away from the road.

   An officer's own look is recorded as a human observation in slice 5.
5. **Only an authorised, non-placeholder frame source with ingestion allowed may ever reach frame
   code** (`frame_capable`). P0 calls no frame code at all.
6. **Stream and snapshot URLs are never sent to the browser.** Viewer links open in a new tab with
   `noopener noreferrer`. Camera names are tooltip text, never HTML.
7. **Routes,** both `protected` and read-only, open to pilot operators as in ADR-0038:
   - `GET /api/v1/pilot/flood/{pilot_id}/cameras`;
   - `GET /api/v1/pilot/flood/{pilot_id}/roads/{road_id}/cameras?radius_m=` (50–1,000 m, default
     400), ranked by usefulness, then health, then distance.
8. **The request to BMA** is drafted in
   [`docs/pilot/2026-10-03_BMA_CCTV_Metadata_Request.md`](../pilot/2026-10-03_BMA_CCTV_Metadata_Request.md)
   in Thai and English. GRP sends nothing itself.

## Consequences

- Screen 2 of the owner's expected outcome now has a working CCTV row. It is honest that the
  cameras are test entries.
- Replacing the placeholders with BMA's list is a data change plus a status-check decision, not
  a code change.
- **Not done here:** snapshots, streams and CV (P1/P2, each needing written permission); a
  scheduled health check; the officer's "I looked" record (slice 5).
