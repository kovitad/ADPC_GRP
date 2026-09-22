# ADR-0015: Activate the approved SIG risk recipe and Thailand baseline

**Status:** Accepted for MVP 1 under the Product Owner approval assumption
**Date:** 22 September 2026

## Context

ADR-0014 correctly withheld vulnerability-weighted risk while the recipe, source meanings and
NoData behavior were unresolved. The Product Owner has now instructed the implementation to
proceed on the explicit assumption that the delivered data and the current SIG Thailand recipe
are approved for MVP 1.

The current recipe weights are population `0.40`, building density `0.35` and road distance
`0.25`. SIG remains the calculator. GRP must pin and disclose the recipe rather than reproduce
the calculation or silently follow a changed SIG configuration.

## Decision

1. Store the active SIG recipe as a versioned, auditable Platform configuration. A Platform
   Admin may record a replacement only when the three weights total 100%, a science owner,
   source reference and change reason are supplied.
2. Treat missing coverage as **Unable to assess**. Do not redistribute weights.
3. Preserve SIG risk citations and statistics when an approved recipe is active. Pin its version
   in the evidence bundle and public-receipt review token.
4. Accept a receipt-bound SIG risk embed only when the response declares exactly one recognized
   risk layer. Continue rejecting missing, multiple or unknown layer identifiers.
5. Activate the latest imported Thailand boundaries, evacuation centres and RP100 hazard only
   through an audited Platform Admin action. The worker reads the six COG tiles as one logical
   pinned input.
6. Continue describing evacuation centres as candidates or as not exposed under the selected
   scenario. Neither SIG risk nor GRP screening certifies safety.

## Consequences

- Real imported districts can become supported and use the existing queued assessment workflow.
- Population-by-age values returned by SIG appear as separately labelled demographic evidence.
- A recipe change invalidates cached answers and requires a new reviewed brief before publishing.
- This decision does not add capacity, accessibility, service, route or cost evidence. Those
  remain explicit gaps in movement and investment decisions.

## Verification

- Permission tests restrict recipe and activation actions to Platform Admins.
- Tests cover recipe validation and audit, six-tile sampling, baseline activation, retained risk
  evidence, risk-layer allow-listing and recipe pinning.
