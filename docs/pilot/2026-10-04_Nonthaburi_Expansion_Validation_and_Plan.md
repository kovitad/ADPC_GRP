# Expanding the live flood pilot to Nonthaburi: validation and plan

Status: validation done on 4 October 2026; plan for review; nothing built. The Product Owner asked
to "expand live to Nonthaburi with this live cam" and gave a list of camera sites from an article.
They added: "not sure it is working, but check and validate first".

## 1. What was checked

Each site got one request (and a `robots.txt` read), as a one-off availability check. This
machine's Windows certificate-revocation lookup was offline, so requests used `--ssl-no-revoke`.

### Live flood evidence (the main source)

**Floodboard already covers Nonthaburi.** In the latest roads snapshot:

| District | Road segments | Reports, last 24 hours |
| --- | --- | --- |
| Mueang Nonthaburi (1201) | 104 | 18 |
| Bang Kruai (1202) | 90 | 15 |
| Bang Yai (1203) | 18 | 5 |
| Bang Bua Thong (1204) | 13 | 24 |
| Sai Noi (1205) | 2 | 3 |
| Pak Kret (1206) | 87 | 17 |

That is 314 road segments and 82 reports in all. The same CC BY 4.0 export is already captured, so
nothing new needs fetching. Bang Bua Thong is also the River Watch (GEOGLOWS) pilot area, so live
street reports and the river outlook would meet there for the first time.

### Camera sources from the article

| Source | Result | Usable? |
| --- | --- | --- |
| **Pak Kret municipality CCTV** (`thaiclouderp.com/CCTV_MONITOR/web/pakkred`) | HTTP 200. **52 cameras**, with IDs (CAMPK001 to CAMPK064), names and coordinates in the page. The picture is a plain JPEG at `https://www.thaiclouderp.com/src/img.php?name=<ID>_thumb.jpg`, which their page refreshes every second. A test picture was a real 640×480 view stamped 19:23 that day, with **no login or session**. No terms are stated; `robots.txt` is empty. | **Yes, technically.** Terms not stated: ask Pak Kret municipality (section 4) |
| **Longdo / iTIC camera feed** (`camera.longdo.com/feed/?command=json`, already used) | 186 cameras; **21 in Nonthaburi**, all in Pak Kret (geocode 1206), still images only. Their names match the municipality's cameras. | Yes, already used; mostly **the same Pak Kret cameras**, so de-duplicate |
| **Nakhon Nonthaburi GIS** (`nkndatamap.nakornnont.go.th/public`) | HTTP 200, but a Next.js app with no documented data interface. No camera data is visible without reading its code. | **No.** The spec forbids reverse-engineering; ask the municipality for a feed |
| **World Flood CCTV** (`world.tehx.dyndns.info/flood`) | HTTP 200. A private aggregator of other people's cameras on a dynamic-DNS host. `robots.txt` blocks AI crawlers. Licence unknown. | **No**: not an owner of the cameras, and it signals that it does not want automated use |
| **iTIC Live** (`live.iticfoundation.org`) | HTTP 200; the viewer site for the same iTIC feed above | Covered by the Longdo/iTIC feed |
| **BMA Traffic** (`cpudapp.bangkok.go.th/bmatraffic/`) | HTTP 404 | Not needed: GRP already uses `bmatraffic.com` |
| **Flood Bangkok, Longdo Traffic** | Bangkok sources already assessed (ADR-0047, ADR-0048) | No change |

### Facilities

**DDPM evacuation centres in Nonthaburi: 64 usable** (flagged records excluded):

| District | Usable | Flagged |
| --- | --- | --- |
| Mueang Nonthaburi | 38 | 0 |
| Sai Noi | 20 | 1 |
| Bang Kruai | 5 | 0 |
| Pak Kret | 1 | 3 |
| Bang Bua Thong | 0 | 1 |
| Bang Yai | 0 | 1 |

This is a real gain for planners: Bangkok has none in DDPM's delivery. OSM schools, hospitals and
clinics would be captured for Nonthaburi as they were for Bangkok.

## 2. Coverage gap to state honestly

Cameras exist only in **Pak Kret**. Mueang Nonthaburi, Bang Kruai, Bang Yai, Bang Bua Thong and
Sai Noi have no usable camera source yet. Their live picture is Floodboard reports plus
facilities, without camera views.

## 3. What has to change in the code

The pilot is built around Bangkok in a few places:

1. **District outlines** come from `core.river_watch.bangkok_outlines()`, which is Bangkok only.
   Use the GRP `boundary` table, which already holds Nonthaburi 1201-1206.
2. **"Is this Bangkok?" checks** use the code prefix `10` (Planner layer, answers, summary, page).
   Replace them with "is this district in the pilot's area list".
3. **Pilot config:** add the six Nonthaburi codes to `demo_corridor.areas`. Rain stays on the
   first four Bangkok districts unless widened.
4. **Pak Kret camera registry:** a capture command (like `bmatraffic_cameras_capture`) that reads
   the 52 cameras once into `core/data/flood_pilot_bangkok_cameras_pakkret.json`. Add a picture
   relay route for them (plain JPEG, no session), with the same limits as ADR-0051 (on demand,
   shared, rate-limited, never stored). De-duplicate against the 21 Longdo copies.
5. **OSM facilities:** capture again for the six districts (one Overpass request).
6. **Naming:** titles that say "Bangkok" become "Bangkok and Nonthaburi". The pilot ID `bangkok`
   stays, so stored data and archive paths do not change.

Effort: about a day of work, plus a browser check.

## 4. Decisions and requests for the owner

1. **Go ahead with Nonthaburi** as part of the same pilot (recommended), or as a separate pilot?
2. **Pak Kret cameras:** no terms are stated. As with BMA, ask the municipality before showing
   pictures in reports. A short request can be drafted. In the meantime, show pictures on screen
   only, or wait?
3. **Nakhon Nonthaburi:** draft a request asking the municipality for a camera feed?

## 5. Not used, and why

- World Flood CCTV: an aggregator of cameras it does not own, with automated use discouraged.
- The Nakhon Nonthaburi GIS internals: reverse-engineering is ruled out by the pilot spec.
