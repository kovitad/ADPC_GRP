# ADR-0017: Renew the SIG access token instead of asking for a new sign-in

**Status:** Accepted for the Developer environment (Docker Desktop) on 2026-09-22. Extends ADR-0002 and ADR-0004; it does not replace either.

**Date:** 2026-09-22

**Deciders:** Product owner and architecture owner (Ole); Technical Lead (Kwan) to review; SIG platform owner informed

## Context

The planning page kept showing "SIG evidence needs a fresh sign-in" to a person who had just signed in and whose GRP session was still valid. There were two separate causes.

1. **The access token expired.** Sign-in asked only for `openid profile email`, so SERVIR issued an access token and nothing else. That token commonly lasts one hour. A GRP session lasts `SESSION_MAX_HOURS` (12) with a 60-minute idle window, so from about the second hour of a working session every SIG lookup was refused with `SIG_REAUTH_REQUIRED` although the person was signed in and authorised.
2. **The API restarted.** The token store is a process-local dictionary (ADR-0002, ADR-0004), so a rebuild of `grp-api:desktop` empties it.

Cause 1 is the one that hits a planner in the middle of real work, and OAuth already has the answer for it: a refresh token.

## Decision

Ask SERVIR for a refresh token at sign-in and renew the access token in the background, inside the same in-memory boundary the interim exception already allows.

- **Scope.** The authorization request asks for `openid profile email offline_access`. `offline_access` is dropped only when the authorization server publishes a `scopes_supported` list that omits it, so GRP never sends a scope the server has said it does not accept. Dynamic client registration (ADR-0002) now also registers the `refresh_token` grant, or the server would never issue one.
- **Storage.** The refresh token lives beside the access token in `api/token_store.py`: process memory only, never in a cookie, the database, a log line or a receipt. It is a credential and is treated as one.
- **Renewal window.** A session's refresh token is usable for at most `SESSION_MAX_HOURS`, recorded per session as `renewable_until`. Renewal can therefore never outlive the GRP session it belongs to, and signing out drops both tokens immediately.
- **When renewal happens.** `api/sig_connection.py` renews when the access token has under two minutes left, so a lookup never starts on a token that dies mid-call. Two concurrent lookups renew once, under a per-session lock, because SERVIR rotates refresh tokens and a second exchange with a spent token would fail.
- **Failing.** A failed renewal is not an error the person sees. They keep whatever life the current token has, and once it is gone the page says a sign-in is needed, as before.
- **What the page shows.** `GET /api/v1/planning/status` also returns `sig_expires_in_seconds`. The banner says how long the connection has left once it is under fifteen minutes, and in both cases offers a **Sign in again** link rather than only stating the problem.

Cause 2 is **not** fixed here. A restart still empties the store. Persisting a refresh token to disk or the database is a larger decision than this one and is properly solved by the shared token store that multi-instance deployment needs anyway.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Leave it: sign in again each hour | No new credential held | A planner loses the thread of real work every hour; the warning trains people to ignore warnings |
| Refresh token in process memory, bounded by the GRP session (chosen) | The warning disappears for the case that actually bites; no new storage, no new surface | A longer-lived credential is held in memory; still lost on restart |
| Persist the refresh token in PostgreSQL | Survives restarts and works across replicas | Stores an upstream credential at rest, which needs a security review and an encryption decision; goes further than ADR-0002 allows |
| Lengthen the SERVIR token lifetime | No GRP change | Not ours to set, and a long-lived bearer token is worse than a short one that renews |

## Consequences

- A planner signed in for a working day is no longer interrupted by a sign-in prompt caused only by token expiry.
- GRP now holds a refresh token in memory in the Developer environment. `main` still never persists, forwards or logs it. Sandbox, staging and production remain blocked on DEP-01 as before.
- When the token store moves to shared storage for multiple API instances, the refresh token moves with it, and that change must decide how an upstream credential is protected at rest.
- If SERVIR does not issue a refresh token — for example because the registered client is not allowed the grant — nothing breaks: the connection behaves exactly as it did before this change.

## Action items

- [x] `offline_access` scope, refresh grant, renewal, per-session lock, tests (`tests/fast/test_sig_connection.py`, `tests/fast/test_oidc.py`)
- [ ] Confirm in Docker Desktop with a real SERVIR account that a session past two hours still runs a SIG lookup
- [ ] Decide how the refresh token is protected once the token store is shared between API instances
- [ ] Technical Lead review
