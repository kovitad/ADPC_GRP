# ADR-0050: bmatraffic.com is the first-choice live camera, embedded as its own player

## Status

Accepted on 3 October 2026 for the Gate A local demo. The Product Owner found BMA's traffic CCTV
site "much better performance", asked to change to it, and showed the embed:
`<iframe src="http://www.bmatraffic.com/PlayVideo.aspx?ID=1362">` (แยกสามเสน). This amends
ADR-0047.

## Context

- **The camera list.** `http://www.bmatraffic.com/index.aspx` embeds 521 camera records in the
  page: ID, Thai name, English name, viewing direction, latitude, longitude and an internal IP
  address. 520 are inside Bangkok:

  | District | Cameras |
  |---|---|
  | Chatuchak | 33 |
  | Bang Sue | 5 |
  | Bang Kapi | 3 |
  | Lat Krabang | 0 |

- **The player.** `PlayVideo.aspx?ID=<id>` sends no `X-Frame-Options` and no CSP, so other pages
  may embed it. The site answers only over plain `http://`; `https://` does not connect.
- **There is no robots.txt and no stated terms.**

## Decision

1. **A third camera source.** `grpcli/bmatraffic_cameras_capture.py` builds
   `core/data/flood_pilot_bangkok_cameras_bmatraffic.json` from a saved page or one download,
   recording source, time, SHA-256 and terms. It keeps the ID, names, direction and location.
   **Internal IP addresses are dropped**, and a test checks that.
2. **A new live kind, `iframe`.** It embeds the provider's own player page, sandboxed (scripts
   allowed; no navigating the GRP page, no pop-ups) with `referrerpolicy=no-referrer`.
3. **`http://` links are allowed only when a registry file declares `allow_http_links`.** Only
   bmatraffic does. Such embeds work on the local demo page. Browsers block them on an `https://`
   deployment, so this is a Gate B item: ask BMA for HTTPS, or proxy it.
4. **Order.** Nearby cameras are ranked by live view, with `iframe` (bmatraffic) before `hls`
   (Longdo) before `mp4` (BMA flood-site relay), then by distance. All three sources stay: BMA
   flood-site cameras keep their sensor links and are the only cameras in Lat Krabang.

## Consequences

- **1,413 cameras in all.** At deployment, no open incident had a bmatraffic camera within 400 m:
  the flooding was in Lat Krabang and Bang Kapi. The cameras are on the map and play from their
  camera card.
- **Not verified here:** whether the embedded player plays in a browser. The Product Owner's own
  test of the same embed worked.
- **Tests:** three sources combined and never evidence; no internal IPs; `http` only when
  declared; quicker live views ranked first.
