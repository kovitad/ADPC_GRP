# ADR-0009: Display technically validated baseline layers before method activation

**Status:** Accepted for local Docker Desktop validation  
**Date:** 20 September 2026

## Context

The accepted Thailand delivery now has immutable boundary, evacuation-centre and RP100 flood-depth versions. The Scientific and Data Authority has not yet resolved DEP-05 (flood NoData, modelled area and permanent water), and the imported districts are not approved assessment areas. Marking these versions `is_current` or `assessment_ready` would incorrectly offer them as assessment inputs.

The product owner nevertheless needs to see **Flood depth · 100-year** and the evacuation centres on the Planning map to review whether the delivered files align.

## Decision

1. An imported version may set immutable metadata `map_preview: true` after worker validation.
2. `/api/v1/maps/layers` may expose a visible platform or Hub version when it is either current or explicitly marked `map_preview`.
3. The Catalog and assessment input routes continue to require current versions. A map preview does not activate an input.
4. The map API labels a non-current preview with `preview_only: true` and its readiness state.
5. The Planning map states that the baseline is a preview, centres are not assessed, and DEP-05 remains unresolved.
6. The API serves only worker-produced display products and materialized point rows. Web requests do no GIS processing.
7. Flood NoData remains visible in the legend and must not be described as dry or not exposed.

## Consequences

- Planners and Admins can inspect the real national RP100 picture and DDPM points without creating a GRP result.
- Preview visibility and assessment eligibility remain separate, fail-closed concepts.
- The six hazard originals and six COGs remain one logical version; the national PNG is display-only.
- Once DEP-05 and method approval are complete, acceptance can make the compatible versions current without changing the immutable imported bytes.
- Loading 10,303 points is acceptable for local review using Leaflet's canvas renderer. Viewport or vector-tile delivery must replace the all-points response if measured browser performance is unacceptable before staging.
