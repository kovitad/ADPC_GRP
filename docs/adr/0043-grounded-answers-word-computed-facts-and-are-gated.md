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

## Decision (7b), added the same day

1. **`POST /api/v1/pilot/flood/{pilot_id}/ask`** takes `question` (at most 300 characters),
   `area`, `since_minutes` and `lang` (`th` or `en`). It **always** returns:
   - the facts and the label map;
   - a computed answer in the chosen language, built from the facts alone, cited, and passing
     its own gate.

   AI wording is added only when all of these hold:
   - the asker is a pilot-Hub member, because the allowance and the Hub's key depend on it. A
     Platform Admin with no membership gets `not_a_pilot_member`;
   - the per-person AI rate limit and the monthly allowance allow it;
   - the provider answers;
   - the wording passes the gate.

   Otherwise `withheld` gives the reason (`AI_OFF`, `AI_LIMIT_REACHED`, `AI_USAGE_UNAVAILABLE`,
   `RATE_LIMITED`, `not_a_pilot_member` or `not_grounded` with its problems), and the computed
   answer stands.
2. **The model sees only the facts,** one JSON object per line, inside a block the instructions
   call untrusted data, followed by the officer's question. The instructions require:
   - citing a label for every claim;
   - using digits copied from the facts and no arithmetic;
   - no evacuation advice, no "safe", no guarantees;
   - "flooding reported nearby" is not "flooded";
   - answering in the page's language, in at most 8 sentences.
3. **The gate (`core/flood_evidence/answer.py`) withholds wording when:**
   - it cites nothing, or cites a label that is not in the bundle;
   - a number (Thai digits normalised, citation tokens removed) is in neither the facts nor the
     question;
   - it uses evacuation, forecast-as-observed or guarantee wording.

   **Known limits:**
   - A number written as a word is not caught.
   - A wrong number that happens to equal another number in the facts passes.
   - The model is told to use digits.
4. **Calls go through the existing gateway** (`run_ai_call`): allowance reservation and
   settlement, channel `web`, prompt version `flood-ask-v1`, and Langfuse metadata only.
   - Testing found that a new channel name would have broken usage recording, because the table
     only allows `web` and `mcp`.
   - Tests inject a fake provider. **No live provider call was made while building this.** The
     owner's allowance was not spent, and no pilot data was sent to the provider.
5. **On the page,** an "Ask about the situation" section offers:
   - suggested questions, the first being the owner's expected-outcome question;
   - an AI card when one passes the gate, otherwise the reason;
   - the computed answer;
   - the facts used.

   Citations become buttons that open the incident or facility, or scroll to the cards, changes
   or limits. Model text is rendered as text only.

## Consequences (7b)

- **Tests:**
  - a grounded answer passes;
  - an invented number, an unknown citation, no citations, evacuation (English and Thai), the
    future tense and Thai digits are each handled;
  - the computed answer passes its own gate in both languages;
  - the data stays inside the untrusted block;
  - AI off, allowance used up and a non-member each still return the computed answer.
- **Not verified:** a live AI answer. The owner should ask one question after signing in. It will
  use their allowance and send the fact bundle (about 11,000 characters, no report text or notes)
  to the configured provider.
