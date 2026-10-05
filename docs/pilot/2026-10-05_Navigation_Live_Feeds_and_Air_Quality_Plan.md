# Navigation menu, "Contribute a live feed", and the ADPC air-quality feed

Status: proposed on 5 October 2026, waiting for the owner's answers at the end.

The owner asked for three things:

- the top bar has too many tabs, and needs a menu with a better layout, "since I might have more
  than one pilot";
- the ADPC air-quality API (AQ Tracker, `docs/adhoc/AQ Tracker API_ Brief for AI2 Agent
  Pilot.docx`) as the next live feed;
- "Contribute a live feed" on the Share data page, either from our platform or from a new
  source, beside the static data kinds.

## A. Top navigation: a grouped menu

Today an Admin sees nine flat tabs:

- Planning
- Assessments
- Share data
- My access
- Administration
- Source data
- Data library
- Platform
- Pilot

On a laptop they crowd the bar, and there is no room for a second pilot.

### Proposed

```text
[SERVIR] Global Risk Platform   Planning  Assessments  Live ▾  Share data ▾  Admin ▾        Kovit ▾
                                                        │        │             │             │
                         Live pilots ───────────────────┘        │             │             ├ My access
                         ● Bangkok and Nonthaburi flood (live)   │             │             ├ Running jobs
                         ● River Watch (GEOGLOWS)                │             │             └ Sign out
                         ○ Southeast Asia air quality (soon)     │             │
                                                                 │             └ Administration
                          Contribute data (files, tables) ───────┤               Source data
                          Contribute a live feed ────────────────┤               Data library
                          My contributions ──────────────────────┘               Platform (Platform Admin)
```

1. **Four or five top items** instead of nine:
   - Planning;
   - Assessments;
   - **Live ▾**, with every pilot the person can open;
   - **Share data ▾**;
   - **Admin ▾**, shown only to Admins.

   **My access** and **Sign out** move into the name menu.
2. **The Live menu is a list built from a pilot registry.** Each entry has a name, a page, who
   may open it and its state (live, soon, paused), so a new pilot is one entry. Pilots the person
   cannot open are not listed.
3. **Behaviour:**
   - menus open on click, not hover;
   - they close with Esc or a click outside;
   - arrow keys move between items;
   - the current page's group is underlined.
4. **Phones** get a ☰ button that opens the same groups as a full-height list.
5. **Built once, in `web/grp-common.js`,** so every page gets it. Page URLs do not change.

## B. Share data → "Contribute a live feed"

A new kind on the Share data page beside vector, raster, table, document and weights. It has
two tabs:

| Tab | What the person does | What GRP does |
| --- | --- | --- |
| **From this platform** | Picks a GRP feed (Bangkok and Nonthaburi flood by district, or flood incidents; later air quality by province) | Fills the whole manifest from our feed registry. The public address comes from `GRP_PUBLIC_FEED_BASE_URL`. Sending is disabled, with the reason, when no public host is set |
| **From another source** | Gives a URL, the records path, the field mapping and the date field | **Test** fetches it once and runs the same checks as Global Risk's validator and `generic_json` reader: a public address, no credentials, a list that is not empty, and sorting by the date field. It shows the first records as Global Risk would see them |

**Rules shown on the page:**
- **Live at once.** A red notice: "This Global Risk server approves contributions at once. They
  go live for everyone and cannot be withdrawn." This was found on 5 October 2026.
- **No keys.** A source that needs an API key, like AQ Tracker, cannot be given directly,
  because Global Risk fetches anonymously. The page says to add it to GRP first, then share it
  "from this platform".
- **Permanent address.** The URL must be one that will stay up. A temporary tunnel address is
  refused, because it matches `trycloudflare.com` and the like.

**API:**
- `GET /api/v1/feeds` lists GRP's publishable feeds, each with its manifest template and
  public URL;
- `POST /api/v1/feeds/check` runs the external-source test;
- sending reuses today's contribution route with `kind=feed`.

## C. ADPC air quality (AQ Tracker) as a live feed

- **Source:** `https://aq-tracker-servir.adpc.net/api/mapclient?action=…`, run by SERVIR
  Southeast Asia.
- **The product:** a 3-hourly, 72-hour PM2.5 forecast (NASA GEOS-CF corrected with a neural
  network, about 5 km), averaged over 11 countries and 351 provinces. It is GET only, and the key
  goes in the `Authorization` header.
- **No key here.** The API answered **403 without a key** on 5 October 2026, and there is none
  on this machine.

### Design

1. **The worker fetches; the web page never does.**
   - Every 3 hours: `get-latest-date?dataset=geos5km`, then `get-data-pm25` at the province
     level for the current step.
   - The result is stored as a snapshot: province, country, average, minimum, maximum,
     forecast time and run date.
   - The key file is `AQ_TRACKER_API_KEY_FILE`, under `/srv/grp/secrets`, mode `0600`.
   - Positional arrays are read by the index the API reference gives, and a changed shape fails
     closed.
2. **US EPA category, labelled as indicative.**
   - Each value gets a category from the 2024 PM2.5 breakpoints (Good up to 9.0, Moderate up to
     35.4, and so on).
   - The label says "indicative: one 3-hour step; the standard is a 24-hour average". The API
     gives concentrations, not AQI.
3. **The feed:** `GET /api/v1/public/aq/sea/feed.json`, behind the same switch pattern as the
   flood feed.
   - Records: one per province, least concern first, with `country`, `province`, `pm25_avg`,
     `pm25_max`, `category`, `forecast_time`, `init_date` and `valid_until` (the next run plus
     one hour).
   - Manifest `sea_pm25_province_forecast`: pack `risk`, hazards `["air_quality","pm25"]`,
     `as_of_field` mapped.
4. **In GRP:**
   - a "Southeast Asia air quality" entry in the Live menu;
   - later, a province layer on the Planner map, and a line in the district summary for Thai
     provinces.
5. **Global Risk.** The risk pack builds its exposure maths from hazard rasters, and has none for
   air quality. So `feeds_query` works at once, but `assemble_pack(risk, hazard="air_quality")`
   will cite the feed with no exposure numbers. That needs a maintainer question.

**Before building C:**
- an API key from ADPC;
- a yes from the AQ Tracker team to republish province averages through GRP and Global Risk,
  with their credit line.

## Order of work

1. A (menu), because it is small and needs nothing.
2. B "from another source" with the Test button, and "from this platform" for the flood feeds.
   Sending stays disabled until a permanent host is set.
3. C as soon as the key arrives: worker job, feed, Live menu entry, and tests with recorded
   answers. Then share it through B.

## Questions for the owner

1. **Menu:** grouped top menu (recommended), or a left side menu?
2. **AQ Tracker key and permission:** do you have a key, and can GRP republish province PM2.5 to
   Global Risk?
3. **The flood tunnel still running from this morning:** close it now (recommended) and ask the
   Global Risk maintainers to re-point or remove `bangkok_flood_districts_live`, or keep it open?
