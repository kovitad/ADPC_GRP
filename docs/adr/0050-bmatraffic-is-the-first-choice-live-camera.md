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

## Amendment, 3 October 2026: open bmatraffic in a new tab

The embedded player showed a blank picture inside GRP. Checked with curl:

- `show.aspx` sends the real frame (about 24 KB) only with a bmatraffic session cookie that was
  first set by `index.aspx`. Without it, it sends a blank white JPEG of about 1.4 KB.
- The cookie is `SameSite=Lax`, so a browser never sends it from a frame inside another site.
  That is why it works in its own tab and not in GRP.

Decision:

- bmatraffic cameras keep their location and `viewer_url` but have no `live` player. The card
  shows "Open live view in a new tab", with a hint to open www.bmatraffic.com once if the picture
  stays blank.
- GRP does not proxy the images or fake a session. That would work around the site's own check,
  and it needs BMA's permission (Gate B).
- Cameras that play inside GRP now come first: Longdo HLS, then the BMA relay MP4.

The BMA flood relay (`floodbangkok.bangkok.go.th/api/proxy`) answered HTTP 500 to a direct
request on the same day, and the owner found BMA's own site slow too. The page gives up after
12 seconds and suggests a camera from another source.

The map also gained one on/off switch per source: road ratings, reports by original source,
facilities, cameras by provider, and the district outline. The choice is remembered in the
browser only.

## Amendment 2, 3 October 2026: a small window instead of a tab

The owner asked for the camera to stay closer to the map. bmatraffic cameras now open in a small
window (460×340) beside the map, named `grp-camera` and reused by later clicks.

- **First click:** the window opens www.bmatraffic.com's home page, so the site sets its own
  session the normal way. After 2.5 seconds it moves to the camera's `PlayVideo.aspx`. Later
  clicks go straight to the camera.
  - This is what a person would do by hand. GRP never fetches, proxies or records the pictures.
- **Security:** the window starts as `about:blank`, and its `opener` is cut before the provider
  page loads, so that page cannot navigate GRP.
- **Fallbacks:** if pop-ups are blocked, the card says so. A plain new-tab link is always there.
- **Still pending:** playback inside the camera card needs BMA's permission or an embed-friendly
  feed (options 1 and 2 in the session notes).
