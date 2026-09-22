# ADR-0010: Cache repeated SIG planning answers within one login

**Status:** Accepted for local Docker Desktop validation  
**Date:** 20 September 2026

## Context

A Chiang Yuen SIG evidence request took 151 seconds: 2.2 seconds to route, 138 seconds in the external SIG MCP sequence and 10 seconds to draft. Repeating the same question previously repeated all provider work. The delay is largely upstream, but GRP must not make a person pay it twice during one review session.

Cached evidence must not cross people, Hubs or login boundaries. It must also expire before the 15-minute reviewed-draft publish token, and retrying an incomplete draft must be able to request fresh processing rather than returning the same incomplete response forever.

## Decision

1. Cache only completed `sig_evidence` responses, in API process memory.
2. Key entries by user, login session, Hub, normalized exact question and confirmed place.
3. Also retain a no-place alias after a verified request so manually repeating the exact question in the same login is a hit.
4. Expire entries after ten minutes and cap the process at 500 entries.
5. A successful new login evicts every prior entry for that user. Logout evicts that session immediately. Restarting the API also clears the cache.
6. Return deep copies and mark hits with `cached=true`; the UI says the answer came from this login's cache rather than repeating the old 151-second timing as if it ran again.
7. `refresh=true` bypasses lookup. **Retry brief generation** uses refresh so an incomplete draft can be regenerated.
8. Cached answers do not call SIG or the AI provider and do not consume another AI allowance reservation. Publishing still validates the signed reviewed draft through SIG and is never satisfied from this cache.

## Consequences

- The first distinct SIG request can still be slow because SIG MCP is external and currently takes most of the time.
- An exact repeat during the same login returns immediately.
- The cache is intentionally unsuitable for multi-process deployment. Before staging with more than one API process, replace it with encrypted shared storage or explicitly accept per-process cache misses.
- No raw uploads, browser coordinates, access tokens or cookies are cached.
