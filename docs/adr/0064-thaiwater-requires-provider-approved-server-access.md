# ADR-0064: ThaiWater requires provider-approved server access

## Status

Accepted on 5 October 2026 as an integration gate. This does not approve ingestion.

## Context

- ThaiWater's current application calls `twa-api-public.thaiwater.net`. Public Swagger UI at
  `/api-docs` describes rainfall, water level, canal level, discharge, reservoirs, gates/weirs,
  Bangkok flood products and CCTV.
- Data operations tested without credentials return `401 Unauthorized`.
- The website supplies an `x-api-key` to its own browser client. Its visibility is not a licence or
  authorization for GRP to copy it into a backend service.
- The Swagger contract does not state external-use terms, data licensing, attribution, quotas,
  retention, redistribution rights or an API-key application process. It documents no `429`
  behavior and does not accurately express gateway security.
- HII separately publishes 36 open-data catalogue packages, all labelled Creative Commons
  Attribution Non-Commercial but without a licence URL/version in package metadata. The open
  water/rain archives are historical; on 5 October, July 2026 was the newest non-empty monthly
  folder found.
- Actual archive samples expose quality flags and station lineage, but also contain a station
  metadata header/row-width mismatch. Open station metadata has sparse pilot coverage and no
  station labelled Bang Bua Thong.
- The official ThaiWater Standard distinguishes observation, creation, update and result times;
  defines quality flags; and describes provider-issued API credentials. It is a schema/security
  standard, not permission to access TWA.

Full findings and the staged plan are in
[`docs/pilot/2026-10-05_ThaiWater_HII_Integration_Research_and_Plan.md`](../pilot/2026-10-05_ThaiWater_HII_Integration_Research_and_Plan.md).

## Decision

1. **Do not reuse or disclose the website's embedded API key.** GRP will use only a credential
   issued by HII for GRP server-to-server use, delivered through an approved channel and stored
   through an `_FILE` secret.
2. **Keep TWA pulls disabled until written approval covers** client type, endpoints, cadence,
   quota, licence, attribution, storage, replay, retention, redistribution and support.
3. **A no-credential catalogue validation spike is allowed**, but its outputs remain research or
   historical context until the ambiguous non-commercial licence is reviewed and HII resolves
   schema questions.
4. **Workers acquire; APIs read.** No web request calls HII/TWA or performs GIS. Every attempted
   pull records bounded fetch lineage; valid raw captures are immutable; malformed input produces
   no normalized observations.
5. **Preserve provider and time lineage.** HII/TWA as aggregator, source agency, station identity,
   observation/forecast time, source create/update time, retrieval time, unit/datum, quality flag,
   raw hash and adapter version remain separate.
6. **Fail closed.** Unknown, missing, suspect, incorrect, removed, stale and clock-invalid values
   never become zero/normal. The last good value retains its real observation age.
7. **Do not infer area values.** Worker-side point-in-polygon may attach a station to a pinned GRP
   area, but a station/district value is never apportioned or averaged into a sub-district.
8. **Classify products before use.** Rain and forecasts are context, never flooding evidence.
   Water level is evidence only of level at its station unless a reviewed threshold says more.
   Provider warnings remain attributed provider judgements. Road-depth, flood polygons and CCTV
   each require a later product-specific decision before incident corroboration.
9. **Replays never call TWA.** They use immutable captured source states and preserve corrections
   or removals rather than silently replacing history.
10. **No public redistribution by default.** TWA/HII values do not enter a public GRP feed or
    Global Risk contribution without explicit downstream rights and approved attribution.

## Consequences

- There is no live ThaiWater feature in the current pilot and no credential is committed or
  borrowed from browser traffic.
- HII authorization and legal interpretation, not implementation effort, are the first gates.
- Open archive research can improve parsers, coverage knowledge and historical replay without
  pretending it is live.
- If access is approved, delivery starts with a 30-day shadow capture and source-health review,
  then limited contextual display. Evidence promotion occurs one product at a time.
- Operational ownership, monitoring, key rotation, retention, station mapping, clock validation
  and source outage behavior are mandatory parts of the integration rather than follow-up work.
