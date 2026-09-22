# Evacuation-centre planning UI plan

**Status:** Ready for implementation planning; no product code changed by this document.
**Date:** 22 September 2026
**Scope:** Connect the existing centre records to a useful Planning panel without inventing missing evidence.

## Outcome

When a planner selects a district, Planning should show every evacuation-centre record in that
district by name and on the map. Before an assessment, rows are labelled **Not assessed yet**.
After an assessment, the same rows show the locked flood classification, reason and measured flood
depth where available. Selecting a row focuses its map marker; selecting a marker opens the same
row. Assessment and Planning continue to share the exact `assessment_id`.

## Evidence available now

The active DDPM version contains 10,303 points and real Thai names in `Feature.name`. The stored
assessment centre contract already returns `feature_id`, `name`, coordinates, status, reason code
and `flood_depth_m`. Feature attributes also contain `admin_code`, claimed district/province and a
district-name-mismatch flag. Sources, method, gaps and limits are already available from the locked
result.

Do not collapse records with the same name. AO Luek contains several distinct points with repeated
names; `feature_id` is the identity and coordinates distinguish them.

## Proposed Planning experience

Use one right-side panel with these views:

1. **Overview** — area, scenario, counts, source versions and a plain-language limitation.
2. **Evacuation centres** — `All`, `Lower mapped exposure`, `Potentially exposed`, `Unable to
   assess` and `Not assessed` filters; name search; complete district list; status, flood depth or
   reason; and a **Show on map** action.
3. **Vulnerable people** — show cited district aggregates only when SIG returns them. State clearly
   that aggregates are not tied to a centre and are not a household map.
4. **Evidence and gaps** — sources, method, missing capacity/accessibility/routes/services and the
   current SIG trace. Keep low-level technical trace secondary.

Never label a centre **safe**. `not_exposed_under_scenario` should read **Lower mapped flood
exposure under this scenario**. Display every centre, not only a ranked top five.

## Implementation sequence

### 1. District-scoped source contract

- Extend the protected map feature read with a required/optional `boundary_id` filter and return
  only the selected district's points. Resolve membership by stable `admin_code` (with a synthetic
  fallback), not by the current `boundary_id`: the active centre import and current boundary version
  can carry different boundary UUIDs.
- Return `feature_id`, name, coordinates, source title/provider and confirmed display attributes.
- Keep the existing Hub/version visibility checks and add cross-Hub/unknown-ID tests.
- Stop loading all 10,303 national points into Planning when one district is selected.

### 2. One reusable centre-list component

- Render source rows from the district endpoint before assessment.
- Upgrade the same component with `/assessments/{id}/centers` after assessment; do not build a
  second list or copy result state.
- Synchronize list selection, marker focus, popup and keyboard focus by `feature_id`.
- Provide search, status filters, counts and accessible empty/loading/error states. Use paging or
  list virtualization if a district count makes rendering noticeably slow.

### 3. Useful details without fabrication

For each row, show only: stored name, status, reason, flood depth, coordinates on demand, dataset
source and assessment reference. Surface claimed district/province or mismatch flags only after the
data owner confirms they are appropriate planner-facing fields. Show missing capacity, services,
accessibility and route checks as gaps—not blank scores.

### 4. Vulnerability and proximity later

SIG `population_by_age` may be displayed as cited district-level evidence now. Do not draw
vulnerability zones, calculate people near centres or create 500 m/1 km/2 km tables from aggregate
totals. Those features require DEP-07 semantics, approved population geometry/denominators and a
versioned proximity method. Implement them as an independent result layer when those inputs exist.

## Data-name safeguard

The active database version (`grp-shelters/1`) has real Thai names. Current importer code
(`grp-shelters/2`) intentionally generates `Evacuation centre N` because the source mapping for
`สถา`, `สถ_1` and `รอง` is still recorded as unconfirmed. Do not re-import or replace the active
version while implementing this UI. First obtain/record DEP-06 field mapping, add a regression test
for known names, then publish a new immutable dataset version. Never overwrite old locked results.

## Acceptance criteria

- Selecting AO Luek shows all district centre records by stored name; repeated names remain separate.
- The map and list contain the same feature IDs and selecting either focuses the other.
- Before assessment, every row says **Not assessed yet** and makes no exposure claim.
- After a valid assessment, totals and per-centre statuses equal the locked API result exactly.
- A source row cannot be described as safe, suitable, approved or ranked without supporting data.
- SIG population values retain citations, geographic scope, unit and denominator; no centre linkage
  is implied.
- A district request does not download or render the national 10,303-point collection.
- Permission, cross-Hub, synthetic/real compatibility and duplicate-name regression tests pass.
- The panel works at desktop and mobile widths and is usable by keyboard.

## Explicit non-goals for this increment

- No invented candidate count, capacity, vulnerable zone, support indicator or proximity statistic.
- No routing, travel-time or road-safety claim.
- No risk ranking across centres.
- No change to approved assessment calculations or historical results.
