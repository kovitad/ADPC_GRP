# ADR-0014: Gate SIG risk levels and verify the embedded map layer

**Status:** Superseded for approved recipes by ADR-0015; remains the fail-closed fallback
**Date:** 22 September 2026

## Context

Live SIG checks on 22 September found two contract changes that can silently alter what a Planner sees:

- SIG now computes vulnerability-weighted risk levels using a configurable recipe whose Thailand science owner, sources and weights are not yet approved.
- The embedded map kept the field name `severity` while changing its meaning from water-depth class to risk level.

The same checks also found an unresolved choice between `hazard_flood` and `flood_rp100`. GRP must not infer that either identifier is the approved JRC RP100 assessment layer. MVP 1 already requires approved vulnerability meaning before presenting vulnerability-weighted results.

## Decision

Until a named science owner signs a versioned Thailand flood-risk recipe:

1. Planning filters SIG citations and summary fields that contain risk-level, risk-class, risk-score, ambiguous `severity`, or vulnerability-weighted values.
2. AI drafting receives only the remaining hazard/exposure citations and is explicitly forbidden from repeating risk classifications or weights.
3. A draft that nevertheless contains a risk classification fails deterministic preflight and is replaced with the non-publishable evidence digest.
4. `ui_embed(hazard_map)` is displayed only when the tool response explicitly identifies exactly one supported flood-hazard layer: `hazard_flood` or `flood_rp10` through `flood_rp500`.
5. A risk layer, missing layer metadata, multiple layers, or an unknown identifier withholds the iframe. The public receipt remains available, and the Planner sees the reason the map was withheld.
6. GRP records the verified displayed-layer identifier in its execution trace. It never interprets the generic `severity` field without that layer context.

This guard does not approve `hazard_flood` as RP100. That mapping still requires an explicit SIG answer and a reviewed contract fixture.

## Consequences

- The existing receipt and evidence workflow continues, but a SIG contract change cannot silently turn a flood-depth map into a risk map.
- A live SIG embed that omits displayed-layer metadata is withheld until SIG supplies a typed field or the team records and approves the real contract.
- Population-by-age information may later appear as separately labelled demographic evidence. It does not become a vulnerability score through this decision.
- Once the science owner approves a recipe, enabling risk requires a new versioned method decision and tests; removing this gate is not a copy change.

## Verification

- Contract tests accept declared flood-hazard layers and reject missing, unknown, multiple and risk layers.
- Planning tests prove that unapproved risk citations and ambiguous stats do not reach the screen or AI prompt.
- Browser copy distinguishes a verified flood-hazard embed from a receipt whose map was withheld.
