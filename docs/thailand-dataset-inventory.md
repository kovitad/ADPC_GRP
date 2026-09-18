# What is actually in the Thailand datasets

**Inspected:** 18 September 2026, from `.local/data-in` (2.1 GB, never committed to Git).
**Purpose:** record what the files contain before any loader is written, and list the decisions they force.
**Status:** findings only. Nothing has been loaded into GRP.

## 1. Flood depth RP100 — ready to use, one rule to settle

| Property | Value |
|---|---|
| Files | 6 GeoTIFF tiles, `ID2xx_Nxx_Exx_RP100_depth.tif`, 113 MB in total |
| Grid | 11,999 × 11,999 pixels each, about 90 m |
| Coordinates | EPSG:4326, the same as the boundaries |
| Values | **Depth in metres** as decimals, not the 1 to 5 classes |
| No-data | −9999 |
| Coverage | longitude 90–110, latitude 0–30: all of Thailand, plus neighbours |
| Format | Already internally tiled (256 × 256) and compressed; **no overviews** |
| Observed depths | lowest 0.1 m, median about 2 m, highest 58 to 138 m per tile |

**Consequences**

1. **Dry land carries no value.** The lowest value anywhere is 0.1 m, so unflooded ground is stored as no-data, not as 0. GRP's method treats no-data as *unable to assess*, so loading this file as-is would mark almost every dry evacuation centre "unable to assess" instead of "not exposed under this scenario". **This is the one blocking question for the Scientific and Data Authority (DEP-05):** within the modelled area, does absent data mean "not flooded"? If yes, the method needs a modelled-area mask or a rule saying so, and a new method version.
2. **Very deep values exist** (over 50 m). These are probably sea or permanent water rather than flooding of dry land. Ask whether a permanent-water mask should be applied, and whether depths above a threshold should be excluded.
3. The legend already shown to planners (0–0.5, 0.5–1, 1–1.5, 1.5–2, over 2 m) fits these values directly.
4. Size is not a problem. Both drawing options stay open; overviews should be added when converting.

## 2. Administrative boundaries — ready to load

| File | Features | Notes |
|---|---|---|
| District | **928** | EPSG:4326. `ADMIN_ID2` district code, `NAME2`/`NAME_ENG2` district, `NAME1`/`NAME_ENG1` province, `VERSION` = `2025-10` (the edition to record) |
| Province | 77 | Same shape of fields |
| Sub-district | 7,436 | Also carries `POPULATION` and `POP_YEAR` |
| Nation | 1 | |
| Village points | 80,397 | Not needed for MVP 1 |

928 districts matches Thailand's real count, and both Thai and English names are present, which the chat's area matching needs.

## 3. Evacuation centres — three candidate layers

| File | Points | Fields |
|---|---|---|
| `ddpm_shelters` | **10,303** | Thai column names truncated to three characters by the shapefile format: `สถา` (place), `รอง` (capacity, for example 300), `จัง`/`อำเ`/`ตำบ` (province, district, sub-district), `ไฟฟ` (power), `ประ` (water), `สุข` (toilets), `ละต`/`ลอง` (latitude, longitude) |
| `ddpm_civil_defense_volunteer_center` | 8,199 | English field names, `LAT`/`LNG`, province and district codes |
| `ddpm_earlywarning_resources` | 1,533 | Equipment locations |

`ddpm_shelters` is the evacuation-centre layer (ศูนย์พักพิง); the other two are staff centres and equipment. **Confirm which layer the assessment must use**, and confirm the truncated Thai column meanings, especially capacity.

## 4. Vulnerable people — Increment 6 only, and needs conversion

| File | Size | Grid | Values |
|---|---|---|---|
| `childSensitivity_01.tif` | 608 MB | 71,075 × 131,389 at 12.5 m, **EPSG:32647** | 0 to 1, no-data as NaN |
| `elderlySensitivity_01.tif` | 603 MB | same | 0 to 1, no-data as NaN |
| `disability_total.tif` | 67 MB | 73,483 × 133,777 at 12.5 m, EPSG:32647 | whole numbers 1 to 2, no-data 255 — **meaning unknown** |

**Consequences**

- These use a different coordinate system from everything else, so they need reprojecting to EPSG:4326 (or the method must transform each point).
- 9 billion pixels each: convert once, keep overviews, never load whole.
- Two sensitivity layers and one count-like layer raise the question of which layer, or which combination, means "vulnerable people" (DEP-07). Until that is answered they stay a map layer marked "not approved" and never enter a result.

## 5. Decisions needed

| # | Question | Who | Blocks |
|---|---|---|---|
| 1 | Within the modelled area, does no-data mean "not flooded"? If yes, provide the modelled-area mask or the rule | Scientific and Data Authority | Any real result |
| 2 | Should permanent water be masked, or deep values capped? | Scientific and Data Authority | Believable numbers |
| 3 | Is `ddpm_shelters` the evacuation-centre layer, and what do the truncated Thai columns mean? | Product owner with the Hub | Loading centres |
| 4 | Which districts are approved as supported assessment areas at pilot start? | Product owner | Area list |
| 5 | Licence, provider and retrieval date for each dataset | Scientific and Data Authority | Showing anything as evidence |
| 6 | Drawing: Option A, a picture per district, or Option B, a tile service | Product owner | Map work |

## 6. Suggested order once those are answered

1. Load the 928 districts (PostGIS geometry, simplified copy for the map), marking only approved districts as supported.
2. Load `ddpm_shelters` as an evacuation-centre dataset version, with the Thai fields mapped to clear names.
3. Convert the six flood tiles to Cloud-Optimized GeoTIFF with overviews, register them with provenance, and decide the no-data rule in a new method version.
4. Draw flood depth for a selected district (Option A).
5. Run one real district end to end and compare with the signed result when DEP-04 arrives.
6. Register the vulnerability rasters, reprojected, as an unapproved layer for Increment 6.
