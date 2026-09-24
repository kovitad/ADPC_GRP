# ADR-0023: Treat SIG return-period layers as external screening

**Status:** Proposed

**Date:** 24 September 2026

**Deciders:** Product Owner, Scientific and Data Authority, Technical Lead

## Context

The Thailand delivery contains only local RP100 flood-depth tiles. The SIG runbook discusses a
regional RP100 source, while the reviewed MCP source at commit `6479521` registers JRC Southeast
Asia layers for RP10, RP20, RP50, RP100, RP200 and RP500. There is no RP25 layer. The SIG metadata
states that the return-period rasters are 1 km regional screening products and should not be used
for siting. GRP needs to show useful scenario context without presenting a remote embedded layer as
a local reproducible assessment.

## Decision

Keep the imported ADPC RP100 source as the detailed local GRP assessment input. Offer exact live
SIG return-period layers as optional **district-wide external screening**, discovered through live
capabilities and requested explicitly with `assemble_pack(pack="risk", hazard="flood_rpNN", ...)`.

Do not create a receipt for a read-only lookup. Only after the user confirms **Create public record
and show SIG map** may GRP publish the grounded answer and call receipt-bound
`ui_embed(hazard_map)`. Never combine SIG counts with local results or classify private Hub centres
against the visual embed. A locked local RP20/RP50 assessment requires locally imported immutable
rasters and an approved method.

## Options considered

| Option | Assessment |
|---|---|
| Pretend RP20/RP50 are local inputs | Rejected: GRP has no such source versions |
| Use the SIG embedded map as a GRP calculation input | Rejected: an iframe is not a pinned raster contract |
| Optional SIG screening plus separate local assessment | Chosen: useful context with honest provenance and scope |
| Automatically publish every lookup to obtain an embed | Rejected: creates public records without informed consent |

## Consequences

- The scenario UI must distinguish **Detailed GRP assessment** from **External SIG screening**.
- Live capability preflight prevents stale source-code assumptions.
- RP20/RP50 context can improve the demo before local scenario rasters arrive.
- Comparison remains qualitative/structured external evidence, not a local multi-scenario result.
- Public map embeds retain the existing explicit confirmation and receipt trail.

## Action items

1. [ ] Record a live `platform_capabilities`/risk-manifest fixture showing deployed scenario layers.
2. [ ] Add capability-driven external-scenario choices; never hard-code RP25.
3. [ ] Add read-only `assemble_pack` rendering with resolution/vintage/scope warnings.
4. [ ] Keep publish/embed behind the explicit two-step public-record confirmation.
5. [ ] Obtain and import local RP20/RP50 rasters if locked shelter comparison becomes required.
