# ADR-0003: Platform Admin manual reset of a person's AI usage

**Status:** Accepted by the product owner on 2026-09-16; needs the Section 17 spec update

**Date:** 2026-09-16

**Deciders:** Product owner and architecture owner (Ole), Technical Lead (Kwan)

## Context

`GRP-ARC-001` v2.2 Section 10 sets one token limit for everyone, counted per person and reset automatically at 00:00 Bangkok time on the 1st of each month (AI-05). AI-11 says there are no tiers, top-ups or personal exceptions in MVP 1. The product owner asked for a way to reset a person's usage without waiting for the monthly reset, for example after a testing mistake or a provider fault.

## Decision

A Platform Admin may reset one person's usage for the **current month** to zero:

- `POST /api/v1/platform/ai-usage/people/{user_id}/reset`, Platform Admin only, with a CSRF check.
- Only `ai_allowance.tokens_used` for the current Bangkok month becomes zero. Open reservations are left alone. `llm_usage` rows are kept, so the real history and cost stay traceable.
- Each reset writes `ai_allowance_reset` to the security log, with the actor, the person, the month and the old value.
- The automatic monthly reset is unchanged. The limit value stays the same for everyone. There is still no per-person limit, top-up or tier.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Monthly reset only (spec as written) | Simplest; no admin discretion | People blocked for weeks after a test or provider error |
| Manual reset of current month, logged (chosen) | Fixes mistakes quickly; history kept | Can hide real overuse; relies on the security log for oversight |
| Per-person top-up or extra allowance | Flexible | Contradicts AI-08 and AI-11; harder to budget (risk R-06) |

## Consequences

- Monthly spend can exceed `limit × people`. Cost reviews must read `llm_usage`, not the `ai_allowance` totals.
- The Platform Admin monitoring view and Langfuse still show every call.
- AI-11 wording must change in the spec to allow "manual reset of the current month by a Platform Admin, logged".

## Action items

- [x] Endpoint, security log event and tests (`tests/fast/test_ai_usage_limit.py`, `tests/fast/test_platform_admin.py`)
- [ ] Update `GRP-ARC-001` Section 10.1 (AI-11) and Section 13.3 events in the next version
- [ ] Add a monthly review of `ai_allowance_reset` events to the runbook
