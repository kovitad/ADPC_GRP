# Pilot tab, Phase B: HAND flood-depth experiment plan

Prepared 2 October 2026 from version 2.1 of
[`2026-10-02_Bang_Bua_Thong_GEOGLOWS_River_Watch_Plan.md`](2026-10-02_Bang_Bua_Thong_GEOGLOWS_River_Watch_Plan.md).
Phase A (the River Watch card, ADR-0036) is already built on `main`, uncommitted. This plan covers
what can be added to the Pilot tab for Phase B, what cannot yet, and what is needed.

## Short answer

- **Possible now, no keys:** a synthetic "how the depth maths works" demo, and a tested raster
  pipeline that runs on a synthetic GeoTIFF in the worker.
- **Not possible yet:** a real Bang Bua Thong depth map from the GEOGLOWS forecast. It needs data
  and decisions, not API keys:
  - a reviewed river reach;
  - a suitable HAND or bare-earth terrain;
  - a discharge-to-water-height (Q-to-H) relationship on the same vertical reference;
  - a hydraulic reviewer;
  - independent flood evidence to check against.
- **API keys:** none are needed for anything in steps B1-B3. GEOGLOWS (checked live) and the
  Copernicus GLO-30 terrain tile for this area on AWS (HTTP 200 on 2 October) need no key.

## What was checked in this repository on 2 October

| Item | Finding |
|---|---|
| Raster tools | `rasterio` 1.5.1 and `numpy` 2.5.3 are installed (`gis` extra); the worker already does raster work |
| Local terrain | None. `.local/data-in/floods` holds only the RP100 depth layer, which must not be turned into forecast depth |
| HAND-building tools | Not installed (no `pysheds` or WhiteboxTools). Building HAND would be new, reviewed work |
| Open terrain | Copernicus GLO-30 `N13 E100` reachable without a key. It is a **surface** model (roofs, trees), so it is poor for an urban district |

## Steps

### B1. Synthetic depth demo on the Pilot tab (built 2 October 2026, ADR-0037)

A new section below the River Watch card: **"How a flood-depth estimate would work (practice
example, not real)"**.

- A small grid of made-up "height above the river" values.
- A slider: "If the river rose __ metres above its channel".
- Each cell is coloured deep, shallow, dry or unknown, with the synthetic H = 3 m table from the plan.
- It is labelled **Synthetic practice example: this is not Bang Bua Thong** wherever it appears.
- Code: `core/hand_depth.py`, a pure NumPy kernel.
  - `depth = max(H - HAND, 0)` inside the supported area.
  - Equal values give zero depth, a dry cell stays 0, and unknown or outside cells stay NoData.
  - A negative H is refused.
  - The result does not depend on block size.
- Tests: the H = 3 table, the boundary cases, a true HAND = 0 cell versus an unknown cell, and
  whole-array versus block equivalence.

### B2. Raster pipeline on a synthetic GeoTIFF (can start now)

- A worker job: the web request only queues it (AGENTS.md: no GIS in web requests).
- Input: a tiny synthetic HAND GeoTIFF and a polygon with a hole, created by the test.
- It calculates block by block on the HAND grid, then writes:
  - depth in metres (float32, explicit NoData);
  - a wet-state raster (1 = wet, 0 = dry, 255 = unknown);
  - `run_manifest.json` with input hashes, mode, H and code version.
- The run is written to a temporary folder and marked complete only after every file reopens and
  passes its checks.
- Failures are explicit: a missing CRS, no overlap, a grid mismatch, an out-of-range H.
- The page shows the latest synthetic run's summary, with "Software check: passed" kept separate
  from "Hydraulic validation: not done".

### B3. Real-scenario readiness panel (can start now)

The Pilot tab lists what a real depth map is waiting for, as plain statuses:

| Status | Plain wording |
|---|---|
| `reach_mapping_unreviewed` | No hydrologist has confirmed the river spot |
| `terrain_missing` | No suitable ground-height map |
| `missing_rating_curve` | No agreed rule turning river flow into water height |
| `datum_unresolved` | Water height and ground height are not measured from the same zero |
| `hydraulic_assumptions_unresolved` | Canals, gates, pumps and tides not yet reviewed |
| `validation_missing` | No past flood to check against |

The real-scenario mode cannot run until each status is cleared with a named reviewer. It never
falls back to synthetic data or a guessed curve.

### B4. Real HAND scenario (blocked)

This needs everything in B3. Then it follows the plan's steps 1-9 and Phase B acceptance criteria:
- the peak-time P25, median and P75 discharge;
- converted to H through the reviewed curve, within its range;
- depth only in the reviewed supported domain;
- profiles and comparison with independent evidence;
- displayed as an experimental layer, kept apart from RP100 and the forecast card.

### Optional, needs the owner's approval: an exploratory HAND from open terrain

GRP could build a HAND raster from open terrain to look at "what if the water rose X m" with
real ground heights. Reasons not to start it yet:
- The only key-free terrain checked is a surface model, which is wrong among buildings.
- FABDEM (buildings removed) is CC BY-NC-SA.
- It needs a new HAND tool.
- It still gives **no forecast depth** without a Q-to-H curve.

Wait until Daniel and Pin say whether a HAND raster or hydraulic model already exists.

## Information needed (from the plan's first meeting with Daniel, Pin and the data team)

1. The nominated river reach, and the part of Bang Bua Thong it represents.
2. Any existing HAND, bare-earth terrain, drainage network or hydraulic model (HEC-RAS or other),
   and whether GRP may use it.
3. Who supplies and reviews the Q-to-H relationship, its vertical reference and its valid range.
4. Whether canals, gates, pumps or backwater make a single-reach HAND approximation unsuitable.
5. Which past floods, flood marks or water-level records can validate a result, and who sets the
   tolerance.
6. The GEOGLOWS licence for derived outputs (CC BY-NC-SA 4.0 or CC BY 4.0).

## Possible later access (not needed for B1-B3)

| Source | Needs |
|---|---|
| NASADEM / SRTM terrain | A free NASA Earthdata login |
| Global HAND products in Google Earth Engine | A free Earth Engine account and its terms |
| Observed Thai water levels for validation (ThaiWater, Royal Irrigation Department) | To be confirmed: public pages exist, but API or bulk access may need a key or a data request |

## Boundaries kept

- Nothing is sent to Global Risk.
- No depth raster is contributed, because Global Risk's raster kinds do not include depth in metres.
- No warning, evacuation, shelter-safety or loss output.
- RP100, the forecast card and any HAND layer stay separate.
- No LLM chooses H or calculates depth.
