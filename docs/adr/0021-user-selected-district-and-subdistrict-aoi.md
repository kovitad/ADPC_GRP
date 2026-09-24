# ADR-0021: User-selected district and sub-district analysis areas

**Status:** Proposed

**Date:** 24 September 2026

**Deciders:** Product Owner, Scientific and Data Authority, Technical Lead

## Context

The accepted baseline currently imports only 928 district polygons. The delivered geography also
contains 77 province polygons, 7,436 sub-district polygons with 2020 population attributes, and
80,397 village points. Planners need local sub-district analysis, while SIG evidence currently
describes a district. Presenting those scopes as one result would be misleading. A village point
cannot safely serve as a flood-analysis boundary.

## Decision

Allow the planner to choose a district or sub-district polygon as the GRP analysis area. Import
country, province, district and sub-district collections as one compatible, version-pinned boundary
release with explicit parent links. Keep village records as an optional location catalogue: choosing
one resolves to and requires confirmation of its containing sub-district.

For a sub-district assessment, request optional SIG evidence for the stored parent district and
label it **district-wide supporting context**. Never disaggregate, combine or relabel SIG district
values as sub-district values. The complete design is in
[`docs/multi-level-boundary-planning-design.md`](../multi-level-boundary-planning-design.md).

Every SIG request originating from a managed boundary uses the catalogue's full unambiguous name:
administrative level, province and country. Short screen labels such as `KANTHARAROM` must become
`KANTHARAROM District, SI SA KET, Thailand` before they reach SIG. GRP still checks the AOI returned
by SIG and refuses evidence for a different or approximate area.

## Options considered

| Option | Assessment |
|---|---|
| Keep district-only planning | Simple but does not meet the required local planning scope |
| Treat village points or buffers as boundaries | Rejected: invents spatial coverage and changes results |
| Use sub-district polygons and parent-district SIG context | Chosen: exact local analysis with honest external context |
| Estimate sub-district SIG values from district totals | Rejected: unsupported disaggregation |

## Consequences

- Planners gain a meaningful level choice without losing reproducibility.
- The boundary importer, area catalogue, selector and input resolver must become level-aware.
- A release manifest is needed to prevent incompatible hierarchy versions from being activated
  together.
- GRP local facts and SIG supporting facts need persistent scope metadata and separate labels.
- Village-level polygon analysis remains unavailable until an authoritative polygon source exists.

## Action items

1. [ ] Confirm district and sub-district as the two assessment-eligible MVP levels.
2. [ ] Confirm source/licence and approval of the `2025-10` sub-district population attributes.
3. [ ] Resolve the village file's incorrect/ambiguous text encoding and provenance.
4. [x] Implement hierarchy import, release validation, AOI search and canonical SIG place names.
5. [ ] Prove one sub-district assessment and its parent-district SIG context end to end.
