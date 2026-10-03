# ADR-0041: Flood incidents group evidence, count independent source types and keep their identity

## Status

Accepted on 3 October 2026 for a local demo (Gate A). This is slice 5a of the Bangkok flood pilot
plan: the read-only incident engine. Officer reviews (slice 5b) are a separate decision. The demo
area is Bang Sue, Chatuchak, Bang Kapi and Lat Krabang.

## Context

- **Spec §10 and §29 (scenarios A–D):** group observations into incidents, show corroboration and
  conflict, never average conflicting evidence, and let stale evidence lose influence.
- **The integration tweak:**
  - count one underlying report once;
  - keep observation quality separate from decision certainty;
  - do not invent a calibrated confidence score.
- **Floodboard's lineage** names `traffy`, `crowd`, `bma_sensor`, `bma_dds`, `cluster` and `news`.
  Its `updated` time can be a batch recalculation; ADR-0038 promised slice 5 would measure
  freshness from the newest underlying report instead.
- **Live scale on 3 October:** the four districts had about 390 road segments with flooding
  reported now. Lat Krabang alone had 281.

## Decision

1. **Grouping** (`core/flood_evidence/incidents.py`, `IncidentGrouping v0.1`, pure functions):
   - Segments inside the demo area that are flooded now are joined when within 80 m (union-find
     with a box prefilter). "Flooded now" means uncleared, with current, recent or aging evidence.
   - Each report from the last 6 hours goes to its nearest incident within 200 m.
2. **Independence counts source families, not reports.** The families are:
   - BMA (`bma_sensor` or `bma_dds`);
   - Traffy;
   - crowd.

   `cluster` (Floodboard's inference) and `news` never count. Many reports of one family are
   labelled "several reports of one kind", not corroboration.
3. **Confidence is a word with reasons:**

   | Confidence | When |
   |---|---|
   | `conflicting` | Any fresh contrary evidence |
   | `high` | BMA plus another family |
   | `medium` | Two families, or BMA alone |
   | `low` | Otherwise |

   - Every reason is stored and shown. No number is shown.
   - The thresholds are pilot rules, not validated, and the page says so.
4. **Conflict is never averaged.** Contrary evidence is a fresh (current or recent) report within
   100 m that says cleared, or a BMA reading of 0 cm. The flooding claim is kept as it is, and the
   contrary reports are listed under "Evidence against".
5. **Freshness comes from the newest attached report.** When no report is attached, the
   incident's age comes from Floodboard's update time, flagged
   `freshness_from_floodboard_update`.
6. **Identity across snapshots** (`core/flood_evidence/incident_store.py`), run by the worker
   after each good roads snapshot:
   - A cluster continues the open incident it shares the most segments with, measured against
     footprints as they were *before* this snapshot.
   - With no shared segment, it continues an open incident whose box is within 80 m, because
     Floodboard re-cuts segments.
   - **Merge:** the oldest incident survives, and the others close as `merged` (with `absorbed`
     on the survivor).
   - **Split:** the biggest part keeps the ID, and the others open as `split`.
   - An incident with no cluster becomes `receding`, and closes after 2 hours.
   - A snapshot not newer than the last processed one is skipped, so loading old captures can
     never rewrite history.
7. **Events are stored** for slice 7's "what changed": `created`, `confidence_changed`,
   `conflict_started`, `conflict_ended`, `size_changed`, `access_to_check`, `receding`,
   `reactivated`, `closed`, `merged`, `absorbed` and `split`. Migration `20261003_0024` adds
   `flood_incident`, `flood_incident_event` and `flood_incident_run` (which records duration).
8. **Check-first order:**
   1. conflict;
   2. a facility whose access is to be checked;
   3. a hospital nearby;
   4. least certain;
   5. biggest.
9. **Routes,** `protected` and read-only, open to pilot operators:
   - `GET /api/v1/pilot/flood/{pilot_id}/incidents`;
   - `GET /api/v1/pilot/flood/{pilot_id}/incidents/{incident_id}`, which returns the
     interpretation, events, roads, reports (flooding and contrary), facilities and nearby
     cameras.

## Consequences

- The first live pass took about 4.8 s, including exposure, once every 10 minutes, and found 59
  incidents. On the page:
  - a "Check first" queue (eight shown, "show all");
  - an incident card with confidence and reasons, facts, evidence against, a report timeline,
    facilities, cameras and "what changed";
  - road cards link to their incident;
  - `?incident=` links can be shared.
- **Tests:** spec scenarios A–D, plus:
  - one-family "several reports";
  - cluster and news never counting;
  - the freshness basis;
  - re-cut continuity;
  - merge;
  - split, which caught a bug where in-loop updates hid the original footprint;
  - recede and close;
  - out-of-order snapshots;
  - ordering.
- **Not done here:**
  - officer reviews and access confirmation (5b);
  - replay (slice 6);
  - severity labels, which need BMA thresholds.
