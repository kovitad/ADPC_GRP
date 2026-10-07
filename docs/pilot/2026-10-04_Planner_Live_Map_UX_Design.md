# Planner live map: facilities and cameras near reported flooding (UX design)

Status: design for review, 4 October 2026. Nothing built. The Product Owner asked to see, on the
Planner map, evacuation centres near reported flooding and the cameras near it, and to click
each point for careful detail.

It extends ADR-0056 step 2 (the live road layer), which is built.

## 1. What a planner wants to know at a glance

1. **Where is flooding reported now** in this district, and how sure are we?
2. **Which evacuation centres** (and schools, hospitals, clinics) have flooding reported nearby?
3. **Can I see it?** Which cameras look at those places, and what do they show now?
4. **How old is this**, and what does it not tell me?

The map answers 1-3 visually. Each card answers 4.

## 2. Layer controls (Layers panel)

The controls appear only for a Bangkok area, as one group under a heading:

```text
LIVE (BANGKOK)                                  as of 14:20
[x] Reported flooding on roads (live, not a flood map)
    [x] Facilities with flooding reported nearby      (3)
    [x] Cameras near reported flooding                (5)
    Legend ▾
```

- The sub-switches are enabled only when the main switch is on. Each shows its count, so an empty
  result is visible without opening the map.
- The time sits beside the heading. Older than 2 hours, it turns amber: "as of 11:40 (2 h 40 min
  ago)".
- Choices are remembered in this browser, as the pilot page already does.

## 3. Visual language on the map

| Item | Mark | Why |
| --- | --- | --- |
| Incident road | line, 5 px, coloured by confidence word: conflicting purple, high red, medium orange, low amber; dashed and faded when receding | already built; the colour is a word, not a depth |
| DDPM evacuation centre with flooding nearby | the existing centre pin gets an **orange ring and a small wave badge** | no second pin for the same centre, so no confusion with the assessment pins |
| School, hospital or clinic with flooding nearby | small round marker with a letter (S, H, C) in an orange ring | these are not shown elsewhere on the Planner map |
| Camera | small dark camera glyph; green dot when it can show a picture in GRP, grey when it opens the official viewer | tells the planner before clicking whether a picture is available |
| Selected item | thicker outline, and its related items stay full colour while others fade | makes "what belongs to this incident" obvious |

Zoom behaviour:

- **District zoom (default):** roads and facility rings are shown. Cameras are grouped into one
  numbered badge per incident ("📷 3"), so the map stays readable.
- **Zoom 15 and closer:** individual cameras appear.
- The live layer draws above the flood-scenario layer and below popups, and never covers
  assessment pins (they are drawn above it).

## 4. Cards (click or tap a point)

Every card follows one pattern:

1. title;
2. one plain sentence of meaning;
3. key facts;
4. related items as buttons;
5. a "what this is not" line;
6. source and time.

Text is built safely, never from raw HTML. Cards are at most 300 px wide; on a phone they open
as a bottom sheet.

### 4.1 Incident card (click a road)

```text
┌──────────────────────────────────────────┐
│ Flooding reported · Soi Phatthanakan 46  │
│ ● Medium confidence                      │
│ Reports from two kinds of source (crowd, │
│ Traffy) agree.                           │
│                                          │
│ Deepest reported   45 cm                 │
│ Reports            3 · last 15:29        │
│ Roads              2 segments            │
│                                          │
│ Nearby: [🏫 2 facilities] [📷 2 cameras] │
│                                          │
│ Reported flooding, not verified on the   │
│ ground. Not part of the assessment.      │
│ Floodboard (CC BY 4.0) · as of 14:20     │
└──────────────────────────────────────────┘
```

- The confidence word comes with its reason in plain words, from the incident's reasons
  (`two_families` becomes "two kinds of source agree").
- **Nearby buttons** fit the map to those items and highlight them.

### 4.2 DDPM evacuation centre card (click the ringed pin)

The existing centre card keeps its assessment content. A live block is added at the top, visibly
separate:

```text
┌──────────────────────────────────────────┐
│ วัดหนองจอก                                │
│ DDPM evacuation centre · Nong Chok       │
│ ┌ LIVE · as of 14:20 ──────────────────┐ │
│ │ Flooding reported on a road 90 m away│ │
│ │ Access not confirmed by GRP.         │ │
│ │ [Show the incident] [📷 Nearest camera]│ │
│ └──────────────────────────────────────┘ │
│ Assessment (RP100): not exposed under    │
│ this scenario · capacity 300             │
│ ...existing card content...              │
└──────────────────────────────────────────┘
```

- **Live and assessment never mix.** The live block has its own time and border.
- "Flooding reported nearby" is never "flooded". "Not exposed under this scenario" stays as the
  assessment wording.

### 4.3 School, hospital or clinic card

```text
┌──────────────────────────────────────────┐
│ โรงพยาบาลวิภาราม                          │
│ Hospital · OpenStreetMap                 │
│ Flooding reported on a road 73 m away.   │
│ Access: not confirmed (GRP has no road   │
│ network).                                │
│ [Show the incident] [📷 Nearest camera]   │
│ Not an official facility list.           │
│ as of 14:20                              │
└──────────────────────────────────────────┘
```

When a frontage road is closed or rated risky for trucks, the access line is shown in amber:
"Access under review: a road at the entrance is reported closed."

### 4.4 Camera card

```text
┌──────────────────────────────────────────┐
│ ปากซอยพัฒนาการ 57 · On Nut Road            │
│ 9 m from reported flooding (Incident I1) │
│ ┌──────────────────────────────────────┐ │
│ │        [ live picture 16:24 ]        │ │
│ └──────────────────────────────────────┘ │
│ ↻ updates every 10 s · ⏸ Pause           │
│ BMA traffic camera (bmatraffic.com)      │
│ [Open official live view ↗]              │
│ One moment, one angle: an empty road in  │
│ a picture is not proof that it is dry.   │
└──────────────────────────────────────────┘
```

- **Pictures** (bmatraffic) come through the existing relay route.
  - They refresh every 10 seconds while the card is open, and stop when it closes or after 10
    minutes, as the pilot page does.
  - If a picture fails: "The camera is not answering right now", with the official link.
- **Other cameras** (BMA flood, iTIC) show "Picture not available in GRP" and the official link,
  which opens in a new tab.

## 5. A "Live now" list (panel)

The same items appear as a short list in the evidence panel's existing area, so everything can
be reached without precise clicking and with a keyboard:

```text
Live now · Suan Luang · as of 14:20
 Incidents (5)        ● I1 Srinagarindra Rd · high
 Facilities (3)       🏥 โรงพยาบาลวิภาราม · 73 m
 Cameras (2 with pictures)
```

Selecting a row flies to the item and opens its card.

## 6. States

| State | What the planner sees |
| --- | --- |
| Loading | "Loading live reports…" beside the switch; no blank flash on the map |
| No incidents | "No flooding reported in Suan Luang now (as of 14:20). No report is not proof that it is dry." |
| Older than 2 hours | the amber time, and a line in every card: "This is 2 h 40 min old." |
| Outside Bangkok | the group is hidden; asking in chat explains coverage |
| Camera fails | the camera card message above; the camera turns grey |
| Sub-district selected | "Shown for the whole district" under the heading |

## 7. Data and API

- **One request,** `GET /api/v1/maps/live-flood`, extended with:
  - **`facilities`:** for the area's district, facilities whose latest exposure is
    `potentially_exposed`. Each carries its type, name, position, nearest distance, the incidents
    it belongs to (shared road keys), the computed access state and its source.
  - **Officer-confirmed access is not shown** (D2). The computed state is shown instead.
  - **`cameras`:** cameras within 400 m of the district's incident roads, without duplicates and
    at most 40. Each carries its name in both languages, position, distance, related incidents,
    whether GRP can show a picture (`picture_url` through the relay) and the official viewer
    link.
- **Spatial work.** Camera distances are computed in this request, as the pilot's incident page
  already does: at most about 20 incidents times 1,413 cameras, which is small. If it becomes
  slow, the worker can store camera matches with each incident, like district codes in step 1.
- **Pictures.** `/api/v1/pilot/flood/bangkok/cameras/{id}/frame.jpg` is open to members of the
  pilot Hub and keeps its per-person rate limit. Nothing is stored.
- **Refresh.** Every 5 minutes while the layer is on (as now). Pictures refresh only while a card
  is open.

## 8. Accessibility and performance

- Markers use focusable icons with an accessible name ("Hospital, flooding reported 73 m away").
- The list in section 5 is fully keyboard-reachable. Colours always come with a word.
- One request per district, cached by the browser for 60 seconds, with no picture requests until
  a card opens.

## 9. Rules kept

- Not a flood map, not a warning; live data is never part of the assessment.
- "Flooding reported nearby", never "flooded"; access is never assumed.
- No officer checks (D2 open).
- Credits are shown: Floodboard, OSM, DDPM, BMA traffic cameras.

## 10. Build steps and checks

1. **API:** `facilities` and `cameras` in the live layer response, with tests (district filter,
   no officer fields, camera deduplication and cap, picture URL only for relay cameras). Add a
   permission-matrix entry if a new route is needed (none is planned).
2. **Map:** sub-switches, markers, rings on DDPM pins, camera grouping by zoom, the legend.
3. **Cards:** incident, facility, DDPM live block and camera, with picture refresh and pause.
4. **"Live now" list** in the panel.
5. **Check in a browser** on Suan Luang (pictures) and Lat Krabang (no pictures), on desktop
   and phone widths, with screenshots.
6. ADR-0056 amendment and handover.

## 11. Questions for the owner

1. **Default:** should the sub-switches start on (recommended) or off?
2. **Camera grouping:** group cameras at district zoom (recommended for a clean map), or always
   show each camera?
3. **"Live now" list:** include it in this round (recommended), or later?
