# ADR-0005: Explicit NDMO and GIS planning roles

**Status:** Accepted by the product owner on 2026-09-17.

## Decision

Replace the generic user-facing **Planner** assignment with two explicit Hub roles:

- `ndmo_planner` — **NDMO Planner**
- `hub_expert` — **Hub Expert / GIS Specialist**

Both roles have the same least-privilege planning access in this release: planning chat, map, catalog and assessments in their own Hub. They cannot manage membership, view Hub security logs, change platform settings or reset AI usage. `admin` remains **Hub Admin**.

The role migration converts existing `planner` records to `hub_expert`, preserving access. The `planner` value remains accepted only for older API/CLI clients during transition and is not shown in the administration UI.

## Consequences

The assignment screen and access documentation use the new labels. Adding different permissions later requires a new ADR, permission-matrix changes, and explicit security review.
