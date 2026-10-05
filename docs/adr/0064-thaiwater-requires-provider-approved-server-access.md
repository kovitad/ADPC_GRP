# ADR-0064: ThaiWater requires provider-approved server access

## Status

Accepted on 5 October 2026 as an integration gate. Amended the same day after the Product Owner
reported that HII confirmed the website API key is public and available for everyone to use. The
amendment permits a controlled GRP shadow-ingestion pilot; it does not approve public warning or
unrestricted downstream redistribution.

## Context

- ThaiWater's current application calls `twa-api-public.thaiwater.net`. Public Swagger UI at
  `/api-docs` describes rainfall, water level, canal level, discharge, reservoirs, gates/weirs,
  Bangkok flood products and CCTV.
- Data operations tested without credentials return `401 Unauthorized`.
- The website supplies an `x-api-key` to its own browser client. Visibility alone was not treated
  as authorization during the initial research.
- The Product Owner subsequently reported direct confirmation from HII that this key is public and
  may be used by everyone. This clears use of the public key for a controlled GRP pilot. The key
  value is still deployment configuration, not source code, test data, a log field or a document.
- The Swagger contract does not state data licensing, attribution, quotas, retention or
  redistribution rights. It documents no `429` behavior and does not accurately express gateway
  security. Public API access does not by itself settle those downstream uses.
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

1. **The HII-confirmed public key may be used for a controlled pilot.** Its value is supplied
   through deployment configuration or an `_FILE` secret and is never committed, logged, copied
   into fixtures or returned by a GRP API. Record the HII confirmation with project governance.
2. **Start with bounded shadow pulls, not public warning.** Confirm/document endpoint cadence,
   fair-use expectations and attribution before sustained polling. Licence, retention and
   redistribution remain gates for public feeds, training exports and third-party sharing.
3. **The open-catalogue validation spike remains allowed**, but its outputs remain research or
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

- There is no live ThaiWater feature in the current pilot and no key value is committed.
- The Product Owner's reported HII confirmation clears a controlled shadow-capture start. The
  confirmation still needs to be retained in the project governance record.
- Open archive research can improve parsers, coverage knowledge and historical replay without
  pretending it is live.
- Delivery starts with a bounded shadow capture and source-health review, then limited contextual
  display. Evidence promotion occurs one product at a time.
- Operational ownership, monitoring, key rotation, retention, station mapping, clock validation
  and source outage behavior are mandatory parts of the integration rather than follow-up work.
