# ADR-0004: Interim Planner chat box and map on SIG generic evidence (Docker Desktop only)

**Status:** Accepted by the product owner on 2026-09-16 for local Docker Desktop testing. Supersedes ADR-0001.

**Date:** 2026-09-16

**Deciders:** Product owner and architecture owner (Ole); Technical Lead (Kwan) to review; SIG platform owner informed

## Context

The product owner wants a first Planner feature to test both SIG MCP and the AI model: a chat box and a map. `GRP-ARC-001` v2.2 limits AI to explaining a stored GRP result (Section 2.2, 10.5). It also makes the GRP worker the only calculator (AD-03). Increment 1 results do not exist yet. The `experiment/planning-chat` prototype showed the idea works, but review findings #2 (automatic public receipts), #3 (no area check), #4 (Platform Admin bypass) and #5 (AI rules bypassed) blocked it from `main`.

## Decision

Add `POST /api/v1/planning/chat`, `GET /api/v1/planning/status` and `/planning.html`, enabled only when `PLANNING_CHAT_ENABLED=true` **and** `GRP_ENV=dev`. They are set only in `deploy/compose.desktop.yml`.

- **Who:** a Planner or Hub Admin of the chosen Hub. A Platform Admin flag alone is refused. Another Hub returns 404. CSRF and the 20 AI requests per hour limit apply.
- **AI:** every model call (routing and drafting) goes through `api/ai_gateway.py`. So the allowance, `llm_usage`, Section 10.6 messages and Langfuse export all apply. The model only proposes `chat`, `sig_flood` or `cannot`. GRP writes the refusal text itself.
- **SIG MCP:** a fixed sequence of `assemble_pack(risk, place, flood)`, then a gateway draft, then (only if the Planner ticks **Publish**) `publish_answer` and `ui_embed(hazard_map)`. It uses the person's SERVIR access token, held in process memory under ADR-0002.
- **Area check (stop safely):** evidence is shown only if the pack's `trace` states `aoi[...] via admin boundary` and the AOI name matches the district the Planner typed. Otherwise the reply says why it stopped, and no numbers, draft or receipt are shown.
- **Receipts:** off by default. Without Publish the answer is labelled "Unverified draft". If SIG's gate blocks a published draft, the draft is withheld.
- **Map:** an OpenStreetMap basemap, plus an OSM search outline for orientation only. SIG's receipt-bound hazard map iframe appears only after Publish. The analysis area stated by SIG is shown as text.
- **Records:** `planning_sig_evidence`, `planning_sig_area_rejected`, `sig_receipt_published` and `sig_receipt_blocked` in the security log. Chat text is not stored.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Wait for Increment 1 and AI explain of stored results | Fully within spec | No way to test MCP and AI with Planners now |
| Merge the experiment branch as is | Fast | Public receipts by default, wrong-area evidence, AI rules bypassed |
| Rebuild on the gateway with area check, opt-in receipts, local only (chosen) | Tests MCP, AI limits and Langfuse end to end | Generic SIG evidence could be mistaken for a GRP result; token in memory |

## Consequences

- Not for Sandbox, staging or production. Moving it needs DEP-01, a security review, a spec update and a new decision.
- The browser calls `nominatim.openstreetmap.org` and `unpkg.com` for the map. That is acceptable for a local test only.
- The OSM outline is not the analysis area. The page says so.
- When Increment 1 lands, the chat should explain stored GRP results instead of SIG generic packs.

## Action items

- [x] Route, area check, gateway accounting, opt-in receipt, tests (`tests/fast/test_planning_chat.py`)
- [ ] Browser test in Docker Desktop with the product owner
- [ ] Technical Lead review
- [ ] Revisit after Increment 1 (replace with result explanation)
