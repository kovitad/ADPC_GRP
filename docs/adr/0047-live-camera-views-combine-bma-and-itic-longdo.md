# ADR-0047: Live camera views combine BMA and iTIC/Longdo, played by the officer's browser

## Status

Accepted on 3 October 2026 for the Gate A local demo. The Product Owner asked to integrate the
live camera into the page ("we can show it"), offered the iTIC Foundation / Longdo Traffic feed,
and asked to "combine them for maximum benefit". This amends ADR-0039 and ADR-0046.

## Context

- **BMA stream addresses are not public.** The `LiveStream` addresses in BMA's camera list
  (`rtc-bkk-bma-*.larry-cctv.com`) do not exist in public DNS (Google and Cloudflare answer
  NXDOMAIN). BMA's own page plays every camera through its public relay,
  `https://floodbangkok.bangkok.go.th/api/proxy?rtcUrl=<stream>`. On 3 October that relay
  answered HTTP 500 for every camera tried from this machine: three cameras on three provider
  servers, with and without BMA's timestamp parameter. Probing stopped there.
- **The iTIC/Longdo feed is documented and public.** `https://camera.longdo.com/feed/?command=json`
  publishes 186 iTIC Motion cameras with coordinates and HLS streams; its documentation states
  only a copyright. 21 cameras with a stream are inside Bangkok, of which 7 are in Bang Sue and 1
  in Chatuchak. A Bang Sue playlist and segment were checked: live 5-second H.264 MPEG-TS, sent
  with `Access-Control-Allow-Origin: *`.

## Decision

1. **Combined sources.** The registry loads every `flood_pilot_<pilot>_cameras*.json` file
   together, and IDs must not repeat across sources:
   - BMA: 872 cameras, with location, the BMA sensor each watches, and a live view through BMA's
     relay (`mp4`).
   - iTIC/Longdo: 21 cameras, with location and the feed's HLS stream (`hls`), credited "iTIC
     Foundation · Longdo Traffic".

   Each source has its own capture script (`grpcli/bma_cameras_capture.py`,
   `grpcli/longdo_cameras_capture.py`) and records its URL, retrieval time, SHA-256 and terms.
2. **A camera may carry `live: {kind: hls|mp4, url}`.** The URL must be `https://`, and a
   placeholder may not have one. `public()` sends the live URL to the page, because only the
   officer's browser plays it.
   - GRP's servers never fetch, relay, record or analyse video.
   - `ingestion_allowed` and `cv_allowed` stay false.
   - No camera confirms anything on its own.
3. **On the page:**
   - "▶ Play live here" on each camera, both in an incident or road card and in a camera card
     opened by clicking its map marker;
   - one player at a time, muted, stopped when the card changes;
   - HLS plays through hls.js 1.5.17 (loaded from jsDelivr only when first needed) or natively
     in Safari, and MP4 through the video element;
   - a stream that has not started after 15 s shows "the camera or its relay may be down";
   - each player is credited with its source and "not recorded by GRP";
   - the coverage row counts both sources.

## Consequences

- Live video works wherever an iTIC/Longdo camera is near an incident. BMA views work only when
  BMA's relay answers, which it did not from this machine on 3 October. The page says so, rather
  than showing nothing.
- At deployment, no open incident had an iTIC/Longdo camera within 400 m; 8 of 50 had a BMA
  camera.
- **Not verified:** frames played in a real browser. Headless capture could not wait for video;
  the playlist, segment, codec support and the page's player code were checked.
- Gate B needs written terms from BMA and from iTIC/Longdo.
