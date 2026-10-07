# ADR-0051: a bmatraffic.com picture relay, for the local demo only

## Status

Accepted on 3 October 2026 by the Product Owner, for the Gate A local demo only. It amends
ADR-0050 and the rule that GRP never fetches or passes on video.

## Context

- bmatraffic.com plays a camera by loading `show.aspx?image=<id>` about once a second.
- It sends a real picture (about 20 KB) only to a session that has opened `index.aspx` and a
  `PlayVideo.aspx` page. Any other request gets a blank 1.4 KB picture or an empty answer.
- The session cookie is `SameSite=Lax`, so a browser never sends it from inside another site.
  No iframe, image tag or pop-up gives an in-page picture. The small window in ADR-0050
  amendment 2 also failed, because cutting its `opener` stopped GRP sending it on to the camera.
- The Product Owner asked for the camera to show inside the GRP page, and chose this relay over
  the window.
- BMA has not given permission. The site has no stated terms and no robots.txt.

## Decision

`core/flood_evidence/camera_relay.py` plus a route,
`GET /api/v1/pilot/flood/{pilot_id}/cameras/{camera_id}/frame.jpg` (`protected`).

**Switched off by default.**
- `BMATRAFFIC_RELAY_ENABLED` is set only in `deploy/compose.desktop.yml`.
- When it is off, the route answers 404 and cameras keep the new-tab link.

**Bounded.**
- **Which cameras:** only registry cameras whose provider is `BMA_TRAFFIC` and whose ID is
  numeric. Anything else is a 404 and never reaches the site.
- **When:** on demand only. Each camera is fetched at most once a second, and every viewer
  shares that one fetch.
- **How many:** at most 8 upstream picture requests a second overall (429 beyond that), and 150
  frames per person per minute.
- **Lifetime:** one visitor session, renewed after 15 minutes or when a blank picture comes back,
  at most once per request.

**Never stored.**
- Pictures stay in memory for at most 30 seconds.
- They are never written to disk or the database, logged or analysed.
- Responses carry `Cache-Control: no-store`.

**Honest.**
- Requests name GRP in the User-Agent.
- The page says the pictures are passed on by GRP for the local demo and not stored.

**Light.** The page asks for the next picture only after the last one arrives, and stops after 10
minutes until the officer presses Continue.

**Ranking.** Nearby cameras that play in the page come first: HLS, then relayed frames, then the
BMA relay MP4.

**Exception to "web requests do no upstream work".** This route calls bmatraffic.com from a web
request, because a live picture cannot wait for a worker cycle. It does no GIS work and is
bounded by the limits above. Every other upstream call stays in the worker.

## Consequences

- bmatraffic cameras play inside the camera card at about one picture a second.
- Because GRP serves the picture itself, this would also work on an HTTPS deployment. It stays
  off there until BMA agrees.
- The BMA request now says exactly what the demo does and asks permission before wider use, and
  how BMA prefers it done (Gate B).
- One shared session and one lock keep the relay simple. A slow answer from bmatraffic delays
  other cameras for up to 8 seconds. That is acceptable for a demo; a deployment would need
  per-camera locks.

## Validation

- `tests/fast/test_flood_camera_relay.py`:
  - the session is opened first;
  - one shared picture a second;
  - a blank picture renews the session once, then gives up;
  - non-JPEG, empty and HTTP-error answers are refused;
  - the overall per-second limit holds;
  - non-numeric IDs never reach the site;
  - only bmatraffic cameras are relayed, and they rank after HLS.
- The permission matrix covers the route switched off: anonymous 401, other Hub 403, members 404.
- A contract test covers it switched on:
  - a JPEG comes back with `no-store`;
  - other providers and unknown IDs get 404 without contacting the site;
  - the camera list shows `frames`.
- Live check in the Docker Desktop stack: camera 1362 (Sam Sen junction) returned a real
  21.6 KB picture in 1.9 seconds, including opening the session.

## Amendment, 3 October 2026: one session per camera

The owner saw every bmatraffic camera show the same picture. bmatraffic.com sends the picture of
the camera whose `PlayVideo.aspx` the session opened last, and ignores the `image` number.
Checked with curl: the same session gave 1362's picture for `image=1108` until it opened 1108's
player.

- **One session per watched camera.** Each session opens the home page and that camera's player
  once.
- **Sessions are dropped** after 30 seconds without a viewer, which also drops the picture.
  At most 16 sessions exist at once; beyond that the least recently used idle one goes, or the
  request gets 429.
- **Each camera has its own lock,** so a slow camera no longer delays the others. This replaces
  the single-lock consequence above.
- **Live check:** cameras 1362 and 1108 gave different, correct pictures.
