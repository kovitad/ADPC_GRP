# ADR-0046: The Gate A demo uses BMA's public camera list, as locations and live-view links only

## Status

Accepted on 3 October 2026. The Product Owner asked why camera links were not taken from
floodbangkok.bangkok.go.th, and approved "pull the BMA camera list for the demo". This amends
ADR-0039, which had found no licensed camera list and used three placeholders.

## Context

- **The data is already public.** BMA's flood site (`/road-flood`) is a public app, and its
  `robots.txt` allows everything. The app loads its camera list from
  `…/bkk/dds/services/api/floods/v1/items/camera_profile` without any login.
- **What each record holds:** camera ID, name and place, latitude and longitude, the BMA flood
  sensor it watches, and a live-stream link on the CCTV provider's server
  (`rtc-bkk-bma-*.larry-cctv.com`).
- **On 3 October:** 876 records, 872 inside Bangkok, 873 linked to a sensor. The four demo
  districts hold 122 cameras.
- **The spec and the tweak** allow only documented, public or authorised camera sources, and
  forbid rebroadcasting or storing video without permission. The list carries no licence.

## Decision

1. **Captured once.** `grpcli/bma_cameras_capture.py` takes a saved download (or downloads once
   with `--download`) and writes `core/data/flood_pilot_bangkok_cameras.json` with the source
   URL, retrieval time, SHA-256, record counts, and **"terms not confirmed; Gate A local demo
   only"**. The 3 October download is kept in the ignored `.local/bma_cameras.json`.
2. **The registry file has shared `defaults`.** `parse_registry` merges them and still checks
   every camera in full. Each camera is stored as:
   - `external_viewer`, with the provider's live link as `viewer_url`, opened in a new tab by
     the officer's browser;
   - `status: unknown`;
   - `ingestion_allowed = cv_allowed = false`;
   - no stream or snapshot URL.

   GRP never embeds, relays, records or analyses the video.
3. **No camera confirms anything on its own.** The engine lists its reasons: health unknown, not
   checked recently, view direction unknown. A real BMA camera may be named in an officer check;
   a placeholder still may not.
4. **The page shows:**
   - the camera's distance, its BMA sensor and an "Open live view ↗" link;
   - a coverage row: "Connected (BMA public list)", terms not confirmed, no video shown or
     stored, status not checked.
5. **The BMA request is now mainly about permission:** terms and attribution, embedding, a
   status check, and camera headings.

## Consequences

- **Live, 3 October:** the top conflicting incident in Lat Krabang has two cameras 30 m away
  watching sensor `FL.LKB.01`, so an officer can resolve the conflict by opening the live view.
  8 of 48 open incidents had a camera within 400 m.
- **Gate B** needs BMA's written terms before this list or its links leave the local demo.
- **The camera-to-sensor link uses BMA sensor codes** (e.g. `FL.LKB.01`). Floodboard names
  sensors differently (`bma_sensor:S-125`), so GRP does not yet join the two.
- **Tests:**
  - the shipped list is real BMA cameras that are links, never evidence, never ingestible, with
    no stream or snapshot URL;
  - defaults are merged and each camera is still checked;
  - an unknown or placeholder camera cannot be named in a review, and a real one can.
