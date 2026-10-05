# ADR-0063: sub-district is a first-class planning scope

## Status

Accepted on 6 October 2026. It implements
[`docs/pilot/2026-10-05_Subdistrict_Level_Plan.md`](../pilot/2026-10-05_Subdistrict_Level_Plan.md)
and amends ADR-0056's former district roll-up rule.

## Context

GRP already stored supported Thailand sub-district boundaries and could run assessments against
them, but the main Planning and live workflows silently treated a selected sub-district as its
parent district. That hid the user's actual scope and could present district totals as though they
were sub-district evidence.

## Decision

1. **One selection, two levels of context.** Selecting a sub-district also identifies and displays
   its province and parent district. The default scope is the selected sub-district; an explicit
   switch can show the whole parent district where that comparison is useful.
2. **Planning follows the selected scope.** The map breadcrumb, boundary, People figures,
   preparedness places, live-flood cards and downloadable summary use the chosen scope. A parent
   district outline is context, not part of the selected geometry.
3. **Assessment remains reproducible.** The picker exposes province, district and optional
   sub-district. Results and breadcrumbs preserve all three levels, and a dashed parent outline
   supplies district context without changing the assessment boundary.
4. **Live flood evidence is filtered, not inferred.** The worker computes incident district and
   sub-district codes when it processes stored snapshots. Request handlers never do GIS work.
   The live page filters roads, reports, facilities and cameras against a captured sub-district
   outline and filters incidents by their worker-produced `subdistrict_codes`.
5. **Captured live-page boundaries.** The flood pilot's versioned area capture contains its
   district and sub-district simplified outlines. The operator regenerates it with
   `python -m grpcli.flood_pilot areas` after a boundary edition or pilot-area change. Web requests
   read that capture rather than the boundary database.
6. **No false disaggregation.** Global Risk evidence remains district-wide because the upstream
   service supplies district packs. It is clearly labelled as parent-district context and is never
   divided, apportioned or combined with sub-district totals. Legacy flood incidents without a
   sub-district placement are reported as a gap rather than silently assigned.

## Consequences

- URLs preserve selected area scope, so a sub-district view can be reopened and shared inside the
  authenticated application.
- Live-page counts and the Check first list change with the selected sub-district; the district is
  still available as the explicit whole-district option.
- The static flood area payload is larger, but provider and database availability cannot delay a
  page request and request-time GIS remains prohibited.
- Browser checks at 1,440 px and 390 px confirmed the Planning breadcrumb and scope switch, the
  Assessment three-level breadcrumb, and the Live district/sub-district picker and filtered counts.
  The checks also found and fixed a pre-existing phone-width overflow in Planning's action row.
