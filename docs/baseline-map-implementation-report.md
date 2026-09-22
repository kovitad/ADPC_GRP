# Baseline flood and evacuation-centre implementation report

**Date:** 20 September 2026  
**Scope:** Local Docker Desktop baseline; not a real GRP assessment  
**Decision:** [ADR-0009](adr/0009-display-only-baseline-map-layers.md)

## Outcome

The accepted Thailand source delivery is now visible on the Planning map as two display-only baseline layers:

- **Flood depth · 100-year** — a worker-produced national picture from one immutable six-tile RP100 version;
- **Evacuation centers** — 10,303 materialized DDPM points assigned to imported districts by geometry.

Neither layer is assessment-ready. The flood version is `waiting_for_method` because DEP-05 has not defined NoData, modelled-area and permanent-water behavior. The shelter version is `technically_valid`; the uncertain `สถา`, `สถ_1` and `รอง` fields are excluded, with generated centre labels used instead. Imported boundaries remain unsupported assessment areas.

## Requirement traceability

| Requirement | Implementation | Verification |
|---|---|---|
| One logical RP100 version | Six source TIFFs are sorted into one stable manifest and one dataset version | Local version reports `tile_count=6` |
| Preserve immutable source | Originals are staged, re-hashed and promoted under generated version keys | Six original `dataset_file` rows |
| Bounded raster processing | COGs are generated sequentially with a 256 MB GDAL cache; map preview is capped at 1,200 px wide | Six COG rows and one PNG row |
| Stable edges | CRS, resolution, band count, tile union, overlap and gap are validated before publication | Fast tests plus successful real import |
| Do not activate flood assessment | Version ends in `waiting_for_method`; Catalog does not expose it as current | Local database check |
| Materialize shelters as points | Generated label, longitude and latitude are written to `feature`; PostGIS `Point` is populated | 10,303 feature and geometry rows |
| Membership by geometry | Every point is spatially assigned to a versioned district boundary; source district text is never used as membership | 10,303 populated `boundary_id` rows |
| Report name/geometry conflicts | Conflicts are retained and reported, not moved or silently removed | 1,139 mismatches; 10 safe examples in the job report |
| Keep uncertain fields away from planners | Importer v2 does not materialize `สถา`, `สถ_1` or `รอง`; the map API returns its stored generated label without renumbering | Unit and map contract tests plus report payload |
| GIS only in worker | Validation, point-in-polygon assignment, COG creation and PNG rendering run in the import worker | API only queues and serves stored output |
| Show layers without implying a result | Non-current versions require `map_preview`; API returns `preview_only`; UI says centres are not assessed and DEP-05 is pending | ADR-0009 and static UI tests/full suite |
| Show a completed assessment on its own map | Result returns its pinned hazard display metadata; browser enables that flood layer, loads every paged assessed centre and fits the pinned boundary | ADR-0012 and golden result tests |
| Distinguish flood depth visually | Worker products and legend use a sequential red palette; grey remains NoData and zero remains transparent | Palette assertions; importer-v2 version `02e40c73-8b41-54bc-ad82-37d4e67add0c` verified with 123,470 red and zero blue visible pixels |

## Local import results

| Category | Result | Duration | Managed file records | Managed bytes |
|---|---:|---:|---:|---:|
| Evacuation centres | 10,303 points; 1,139 name conflicts; 0 outside all districts | 5.55 s | 8 | 29,987,922 |
| RP100 flood depth | 6 originals; 6 COGs; 1 national PNG | 31.64 s | 13 | 279,132,713 |

The complete local managed `datasets/` tree is 325 MB including the previously imported boundary collection. PostgreSQL contains 10,303 shelter `Point` geometries and district foreign keys. Migration head is `20260920_0010`.

## User experience

1. Open **Planning** and then **Layers**.
2. Open **Layers**, choose the return period and check **Flood depth**. RP100 is available; RP20 and RP50 are configured but disabled as **not imported**, because no accepted source versions exist for them.
3. **Evacuation centers** is enabled by default and draws the DDPM points. A point popup says **Evacuation center · not assessed yet**.
4. Read the visible preview warning. No preview centre is classified and no assessment can be started from these imported versions.
5. When a supported assessment is run, its completed result automatically opens the exact pinned flood picture and only the assessed centres inside that district or future supported sub-district. Red means flood depth, not vulnerability-weighted risk.
5. Platform Admins can inspect version, readiness, conflict and file counts on **Data library**.

Flood depth is opt-in and changing scenario replaces the single display overlay; selecting a district never silently enables it. The Planning client uses Leaflet's canvas renderer for the national point layer. Repeated exact SIG questions use the ten-minute, login-bound cache in [ADR-0010](adr/0010-session-bound-sig-answer-cache.md); this does not make a first upstream SIG request faster. This remains a local acceptance implementation; browser timing and phone layout still require a signed-in browser pass.

## Validation

- `python -m pytest -q`: **301 passed, 2 PostgreSQL-only skipped** (including the later login-bound cache tests).
- `python -m ruff check .`: clean.
- `node --check web/planning.js` and `node --check web/data-library.js`: clean.
- Docker Desktop image rebuilt; migration `0010` applied; API health returned `{"status":"ok"}`.
- Real local imports succeeded with the counts above.
- Database checks: 10,303/10,303 shelter rows have district membership and PostGIS geometry; 1,139 carry the mismatch flag; hazard has six COGs and one map preview.

## Open gates

- A person must sign in again after the image rebuild and visually accept the Planning map; the rebuild cleared the local session and in-memory SIG token.
- DEP-05 blocks flood classification and real assessment activation.
- DEP-06 must confirm the source mapping and meaning of `สถา`, `สถ_1` and `รอง` before any can be planner-facing.
- Before staging, measure rendering of all 10,303 points. Add viewport queries or vector tiles if needed.
- External Leaflet, OSM tiles and Nominatim remain local-only dependencies.
