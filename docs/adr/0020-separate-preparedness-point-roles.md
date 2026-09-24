# ADR-0020: Keep preparedness point roles separate

**Status:** Proposed

**Date:** 24 September 2026

**Deciders:** Product Owner, Scientific and Data Authority, Technical Lead

## Context

The delivered `evacuation_centers` folder contains 10,303 shelters, 8,199 civil-defence volunteer
centres and 1,533 early-warning resources. They are all point geometries, but they answer different
planning questions. Treating every record as an evacuation destination would produce misleading
movement options. Maintaining three unrelated import implementations would duplicate quarantine,
validation, versioning and map logic.

## Decision

Use one reusable point-data ingestion pipeline with three explicit dataset roles:
`evacuation_centers`, `volunteer_centers`, and `early_warning_resources`. Store and version each
source independently. Only `evacuation_centers` may be pinned into the MVP 1 shelter flood
assessment. The other two roles are optional, district-scoped supporting layers and do not alter a
locked assessment.

When a planner selects an area, show volunteer-centre and early-warning points by default and
summarize all three supporting roles, including village locations, in the decision panel. Keep
their counts and provenance explicitly outside the locked shelter-flood result. Vulnerability
rasters are likewise shown as current display context, never silently treated as assessment inputs.

Upload one Shapefile ZIP per role. Never infer the role from a field value, merge roles, activate a
technically valid upload automatically, or publish it to SIG automatically. Exclude volunteer
contact fields from planner-facing normalized data.

The detailed workflow and acceptance criteria are in
[`docs/preparedness-point-data-design.md`](../preparedness-point-data-design.md).

## Options considered

| Option | Assessment |
|---|---|
| Merge all points as evacuation centres | Rejected: changes their meaning and creates unsafe recommendations |
| Build three complete upload systems | Rejected: needless security and maintenance duplication |
| One pipeline with explicit roles | Chosen: shared controls without mixing operational meaning |
| Store every source field and hide it in the UI | Rejected for MVP 1: unnecessary personal/contact-data exposure |

## Consequences

- Admins can manage all delivered point sources through one consistent workflow.
- Planners can see response and warning context without confusing it with candidate shelters.
- Assessment reproducibility remains stable because supporting layers are not calculation inputs.
- The dataset enum, migrations, importer profiles, catalog UI and map API must be extended.
- Any future method that uses a supporting role requires a new approved method version; it cannot
  silently change `center-flood-overlay`.

## Action items

1. [ ] Confirm the final user-facing English/Thai names for the three roles.
2. [x] Exclude volunteer contact fields from planner-facing API responses.
3. [x] Implement the three versioned import profiles and migration.
4. [x] Add separate Data Library review cards and supporting map layers.
5. [x] Show area-scoped counts in the decision summary without changing assessment fingerprints.
