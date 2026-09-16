# ADR-0002: Interim SERVIR sign-in through a dynamically registered SIG MCP client

**Status:** Proposed (temporary exception; must be removed before the Alpha → Beta gate)

**Date:** 2026-09-16

**Deciders:** Architecture owner (Ole), Technical Lead (Kwan), SIG platform owner, ADPC security

## Context

`GRP-ARC-001` v2.2 Section 9.1 and dependency DEP-01 require SIG to register GRP as its own application in SIG's WorkOS login, with logins addressed to GRP only. Section 9.6 says a login addressed to SIG's MCP service must never be accepted by GRP, and Section 9.1 says login tokens are not stored.

DEP-01 is not signed yet. To make progress, the current code (`api/oidc.py`, `grp/oauth.py`) discovers the authorization server from the SIG MCP resource metadata, registers a PKCE public client through dynamic client registration, and sends `resource=<SIG MCP URL>` in the authorization and token requests. The ID token audience is the registered client, and GRP verifies issuer, audience, signature, expiry, nonce and verified email. The access token that comes back is addressed to SIG's MCP service. On `main` it is discarded; on the `experiment/planning-chat` branch it is kept in process memory for the planning demo.

## Decision

Accept this flow only as a temporary exception, for the Developer and Sandbox environments, until SIG registers GRP as its own application:

- `main` must not keep, forward or log the MCP access token.
- Staging and production must use a GRP application registered by SIG (DEP-01). No production sign-in uses dynamic client registration.
- The identity rules in Section 9.2 stay unchanged: only the verified `(issuer, subject)` and a pre-added email grant a link, and only GRP membership grants access.

## Options considered

| Option | Benefit | Main risk |
|---|---|---|
| Wait for DEP-01 before any sign-in work | Fully compliant | Blocks Increment 2 testing |
| Dynamic client registration against the MCP resource (chosen, temporary) | Real SERVIR accounts work now | Login is addressed to SIG's MCP resource, which Section 9.6 forbids; the client is not reviewed by SIG |
| Store and reuse the MCP token for SIG calls | Enables live MCP demos | Breaks Section 9.1; token lost on restart; not multi-worker safe |

## Consequences

- Sign-in can be tested with real SERVIR accounts before the SIG agreement is signed.
- Sections 9.1 and 9.6 are not met until DEP-01 is done. The Alpha → Beta gate must not pass on this flow.
- The GRP evidence endpoint (Increment 3) must reject any token whose audience is SIG's MCP service. Add that test when the endpoint is built.

## Action items

- [ ] Send the DEP-01 request to the SIG platform owner (GRP app for Sandbox, staging, production)
- [ ] Replace `resource=` MCP discovery with the SIG-registered GRP client once available; delete `grp/oauth.py` registration command
- [ ] Add a callback test that rejects an ID token addressed to another client
- [ ] Security owner approval of this interim exception
