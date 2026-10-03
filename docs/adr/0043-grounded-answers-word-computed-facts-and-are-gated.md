# ADR-0043: Flood answers word computed facts, and a gate withholds ungrounded wording

## Status

Accepted on 3 October 2026 for a local demo (Gate A). This is slice 7 of the Bangkok flood pilot
plan, the owner's screen 4: "What has changed in Bangkok during the last hour, and which critical
facilities may require attention?" Part 7a, the deterministic changes and facts, is described
here. Part 7b, the AI wording and the gate, is added below when built.

## Context

- **Spec §16 and the integration tweak:** AI summarises computed results and cites evidence. It
  must not invent depths, thresholds, confidence or evacuation advice, and must never present a
  forecast, RP100 or HAND as observed.
- **The tweak's read-only tools:** `get_current_incidents`, `get_incident_evidence`,
  `get_exposed_assets`, `get_access_impact`, `get_river_outlook` and `get_situation_changes`.
- **History is limited.** Incidents have been tracked only since the first incident run, at
  11:08 Bangkok time on 3 October. Its `created` events describe what already existed, not new
  flooding. Past road counts cannot be rebuilt either, because a road row remembers only its
  newest snapshot.

## Decision (7a)

1. **Deterministic tools in `core/flood_evidence/briefing.py`**, named after the tweak:
   `get_current_incidents`, `get_incident_evidence`, `get_exposed_assets` and
   `get_situation_changes`. `get_access_impact` is the facility access state (ADR-0040/0042).
   `get_river_outlook` stays in River Watch and is never mixed into these answers.
2. **The first run is a baseline.**
   - Changes count only events strictly after `max(since, tracked_since)`.
   - A window that starts earlier says "GRP has tracked incidents since HH:MM".
   - Facility changes compare the stored per-snapshot exposure rows at or before the window
     start with the latest ones.
   - Open-incident counts then and now come from the incident runs, demo-area wide.
3. **Areas:** `all`, `corridor` (the demo area) or a district code. Incidents are placed by
   their centre and facilities by their district.
4. **The fact bundle (`build_facts`)** holds:
   - `S`, the situation totals;
   - `C`, the changes;
   - `I1`–`I15`, incidents in check-first order;
   - `F1`…, facilities near flooding or with access to check or confirmed cut;
   - `L`, the limits: sources, what is not connected, and the meaning of verdicts, facilities
     and confidence.

   Each fact has a short opaque label, and the label-to-ID map goes only to the page. Times are
   pre-rendered in Bangkok time and as minutes ago, and totals are pre-computed, so nothing needs
   arithmetic. Road names are capped at 60 characters. **Officer notes, report text, HAND and
   RP100 are never included.**
5. **Routes,** `protected` and read-only, open to pilot operators:
   `GET /api/v1/pilot/flood/{pilot_id}/changes` and `/facts`, with `area` and
   `since_minutes` (10–1,440).
6. **A "What changed" panel** has a window choice of 30 minutes, 1 hour, 3 hours or 6 hours. It
   shows counts by kind, with links to the incidents and the facilities newly near or no longer
   near flooding, and is labelled "computed from stored evidence; no AI".
7. **No MCP server is built or registered.** Gate A forbids registration; the tool names keep a
   later wrapper thin.

## Consequences

- **On live data for the hour after tracking began:** 1 new incident, 3 grew, 6 shrank,
  4 no longer reported. Open incidents in the demo area went from 59 to 55.
- **Tests:**
  - the baseline is not "new";
  - counts by kind;
  - the area filter;
  - an unknown area is refused;
  - the bundle is capped with an "N not listed" count;
  - the bundle carries no notes, phone numbers, HAND or RP100, and no UUIDs.
