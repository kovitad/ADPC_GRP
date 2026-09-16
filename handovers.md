# GRP MVP 1 Project Handover

**Updated:** 16 September 2026 (Phase A review and stabilization)

**Repository:** <https://github.com/kovitad/ADPC_GRP>

**Branches:** `main` (product baseline) and `experiment/planning-chat` (local AI chat prototype, not for merge)

**Baseline:** `GRP-ARC-001` v2.2. Local commits are not pushed yet.

## Current position

Increment 0 is complete. Most of Increment 2 (sign-in, membership, Hub administration) is built early. **Increment 1 (golden assessment) has not started**: `api/assessments.py` and `worker/main.py` are stubs, and the golden and SIG fixture folders contain only READMEs. The spec's Alpha gate needs Increments 0 to 3, so Increment 1 is the critical path.

| Area | Current state on `main` |
|---|---|
| Sign-in | SERVIR OIDC/PKCE, ID-token checks (issuer, audience, signature, expiry, nonce, verified email). Uses an interim dynamically registered MCP client; see [ADR-0002](docs/adr/0002-interim-sig-mcp-client-login.md) |
| Linking | Matches Section 9.2: only a pre-added email links; otherwise denied, logged, nothing created |
| Sessions | Signed HttpOnly cookie, 60 min idle / 12 h max, membership reloaded every request. **New:** CSRF token on every state change; sign-out and any role/access change end the person's sessions on the server (`app_user.sessions_valid_after`) |
| Hub administration | Platform Admin and Hub Admin member list, add, role change, enable/disable; last-Admin guard with row lock; audited changes; setup CLI (`bootstrap-platform-admin`, `ensure-hub`, `assign-member`) |
| Errors | **New:** Appendix D format `{error: {code, message, support_ref}}` on sessions and admin routes; other-Hub and unknown items return 404 |
| Database | Migrations `20260916_0001` (5 access tables) and `20260916_0002` (session revocation). 11 of 16 spec tables still missing |
| Tests | 31 offline tests, Ruff clean. New `tests/fast/test_session_security.py` covers CSRF, role-change revocation, and sign-out replay |

## Phase A work done on 16 September

Commits (local, not pushed):

| Commit | Branch | What |
|---|---|---|
| `ff084c7` | experiment | Snapshot of the uncommitted chat prototype, preserved as-is |
| `3f3db5c` | main | Hub administration plus review fixes #6 to #8 (CSRF, session revocation, 404 and Appendix D errors) |
| `3e0fe24` | experiment | Merge of main; public SIG receipts now opt-in only; Platform Admin without membership blocked from SIG evidence |
| (this commit) | main | ADR-0002 and this handover |

## Code review findings (16 September)

Reviewed against `GRP-ARC-001` v2.2.

| # | Finding | Status |
|---|---|---|
| 1 | Sign-in requests a token addressed to SIG's MCP resource via self-registered client (Sections 9.1, 9.6) | Open, recorded as interim exception in ADR-0002; needs DEP-01 |
| 2 | Chat issued a public SIG receipt on every flood question (Checklist I.2, Section 15.4) | Fixed on experiment branch: `publish_receipt` must be explicitly true |
| 3 | Chat calls `assemble_pack` by free-text place with no area-match check (AD-03; the Ku Thong fallback-box failure) | Open, experiment only. Do not reuse this path in product code |
| 4 | Platform Admin without Hub membership could run the SIG path (Section 9.4) | Fixed on experiment branch, with test |
| 5 | Chat bypasses `AI_FEATURE_ENABLED`, allowance, usage records and per-Hub key (Section 7.5, AI-12/13) | Open, experiment only; ADR-0001 remains Proposed |
| 6 | No CSRF protection (Section 13.1) | Fixed on main |
| 7 | No new session after role change; sign-out left a copied cookie valid (Section 9.1) | Fixed on main |
| 8 | 403/400 instead of 404 for other Hubs; errors not in Appendix D format | Fixed for sessions and admin routes; apply to every new route |
| 9 | No rate limits (settings exist, not enforced) | Open, Phase B |
| 10 | Pending-request list scans the whole audit log and lists any SERVIR account; spec has no self sign-up queue | Open, Phase B: decide keep (with ADR) or remove |
| 11 | In-memory MCP token store is unbounded | Experiment only |
| 12 | No permission-matrix, cross-Hub contract, or full Section 15.3 sign-in tests | Open, Phase B |

Known limits of the Phase A fixes: sign-out is still a GET link and ends the person's sessions on all devices; migration `20260916_0002` was checked with SQLite tests only, not run on PostgreSQL.

## Experiment branch rules

`experiment/planning-chat` holds the local chat (`/planning.html`, `api/ai.py`, `api/mcp_client.py`, `api/openai_gateway.py`, `api/token_store.py`, ADR-0001). It passes 40 offline tests. It must not be merged into `main`: general chat, token storage and place-name pack calls conflict with the spec. Keep it `GRP_ENV=dev` only, never enable receipt publishing with private data, and keep the OpenAI key out of Git and logs. Revisit it in Increment 6, rebuilt to explain a stored GRP result.

## Architecture guardrails

- The GIS worker is the only calculator. Screens, SIG, downloads, and AI read the same locked result.
- Every assessment is a background job with pinned boundary, dataset, method, and SHA-256 fingerprints.
- Stop safely with typed errors. Never substitute a fallback area, dataset, route, or provider.
- SERVIR sign-in proves identity; GRP membership decides Hub and role.
- Nothing goes to SIG unless an Admin shares it. Receipts are issued by hand during acceptance only.
- AI explains stored results only and stays off until Increment 6 is accepted.

Any change to these rules needs an ADR and the approvals in Section 17.

## Refined plan

**Phase B: finish Increment 2 security (about 1 week)**
- Rate limits from Section 13.1
- Permission matrix test for every row of Section 9.4; cross-Hub denial contract tests; remaining Section 15.3 sign-in tests
- Decide the pending-request list (finding 10)
- Cancel queued jobs on disable once jobs exist

**Phase C: Increment 1, golden assessment (main work, 2 to 3 weeks)**
- Remaining tables and migrations, storage interface, Chiang Yuen seed, validation and result rules
- `POST /assessments` with idempotency and 202; PostgreSQL `SKIP LOCKED` queue; worker with 15-minute lease; locked result
- Golden test in CI (synthetic case until DEP-04 arrives); CI blocks merges on golden, migration, permission, contract and secret-scan failures

**Phase D: Increment 3, SIG connection**
- Sharing approval, evidence endpoint (rejects MCP-audience tokens), SIG machine login, contract tests, one receipt by hand

## Dependencies to chase this week

| ID | Needed | Owner | Blocks |
|---|---|---|---|
| DEP-01 | GRP registered as its own app in SIG WorkOS (Sandbox, staging, production) | SIG platform owner | Removing ADR-0002 exception; Beta |
| DEP-04, DEP-06 | Approved Chiang Yuen boundary, signed golden result, evacuation-center dataset | Scientific and Data Authority | Increment 1 acceptance |
| DEP-08, DEP-09, DEP-13 | Risk pack `assessment_ref`, SIG machine login and how it is issued | SIG platform owner | Increment 3 |

## Resume commands

```powershell
git pull --ff-only
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest
alembic upgrade head
docker compose --env-file .env -f deploy/compose.yml config
```

Read [`README.md`](README.md), [`AGENTS.md`](AGENTS.md), [`docs/access-management.md`](docs/access-management.md), and the secure copy of `GRP-ARC-001` v2.2 before changing application behavior.
