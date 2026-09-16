# SERVIR Global Risk Platform

This repository is the implementation foundation for the ADPC Hub of the SERVIR Global Risk Platform (GRP) MVP 1. It follows solution architecture `GRP-ARC-001` version 2.2: ADPC owns access, data, GIS processing, and immutable assessment results; SIG reads only Admin-approved results to build traceable evidence and receipts.

> **Current status:** Increment 0 is complete and the first access-control slice is implemented early. GRP now discovers the OAuth server from the SIG MCP resource, supports authorization-code/PKCE sign-in for existing SIG accounts, creates pending access requests, and enforces GRP-owned Hub membership. A localhost public client can be registered with the supplied command; staging still needs its own callback-specific client ID. Assessment, GIS, downloads, AI execution, and SIG evidence screens remain unimplemented.

For the current implementation inventory, known limitations, validation record, and exact next slice, read [`handovers.md`](handovers.md).

## Architecture

```mermaid
flowchart LR
    Browser -->|HTTPS| Caddy
    SIG[SIG Risk pack] -->|shared evidence only| Caddy
    Caddy --> API[grp-api / FastAPI]
    API --> DB[(PostgreSQL + PostGIS)]
    Worker[grp-worker] --> DB
    Worker --> Files[/srv/grp/data]
    API --> Files
```

The API validates identity, Hub membership, permissions, and inputs. The worker is the only component allowed to calculate GIS results. Successful results are immutable and are reused by the screens, exports, SIG integration, and later AI explanations.

## Repository layout

```text
api/              FastAPI entry point and bounded API modules
worker/           Background job and GIS-worker boundary
core/             Shared models, validation, result rules, and storage protocol
migrations/       Alembic environment and versioned database migrations
grp/              Server-side access administration commands
web/              Existing-SIG registration, sign-in, and protected workspace screens
deploy/           Ubuntu Compose, Caddy, and deployment guidance
tests/            Fast, contract, golden, live, and load test layers
docs/adr/         Architecture decision records
```

## Local quick start

Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
.\scripts\run-local.ps1 -RegisterSigClient
```

The first run creates ignored SQLite/session files and registers the exact localhost callback. Later runs use `.\scripts\run-local.ps1`. Open `http://127.0.0.1:8000/register.html`, choose **Continue with SIG**, and authenticate in SIG. A verified account without GRP membership returns to the pending screen.

Bootstrap a different existing SIG user as Platform Admin, then create the ADPC Hub:

```powershell
.\scripts\admin-local.ps1 bootstrap-platform-admin --email admin@example.org
.\scripts\admin-local.ps1 ensure-hub --actor-email admin@example.org --code adpc --name "ADPC Hub"
```

Replace the sample with the administrator's verified SIG email. The admin then opens `http://127.0.0.1:8000/admin`, authenticates through SIG, and reaches the protected approval panel. Platform Admins see pending requests; Platform Admins and Hub Admins can add, change and disable members of Hubs they manage, and the last active Hub Admin is protected. State-changing requests need the `X-CSRF-Token` header (value from the `grp_csrf` cookie). Sign-out and any role or access change end that person's sessions on the server. Authentication proves the SIG identity; only an active GRP membership grants application access. The interim sign-in flow is recorded in `docs/adr/0002-interim-sig-mcp-client-login.md`; its access token is not kept.

## LLM token preparation

AI remains disabled, but both environment templates contain provider, model, base URL, output limit, and `AI_KEY_FILE_ADPC`. Store a local token through hidden input:

```powershell
python -m grp.configure set-ai-key
```

This writes `.local/secrets/ai_key_adpc`, which Git ignores. On staging, place the token at `/srv/grp/secrets/ai_key_adpc` with root ownership and mode `0600`. Never put the raw token in `.env`; `.env` contains only the file path. Enabling `AI_FEATURE_ENABLED` does not yet add LLM behavior.

## Sign-in and membership mapping

GRP registration is only for people who already have a SIG/SERVIR account. It collects no local password or unverified identity data: the applicant must complete SERVIR authentication before a pending request appears. An unknown verified identity creates an `identity_link_denied` audit event for administrator review, but no user, external identity, or membership record. After an administrator assigns a Hub role, the user returns to sign in and GRP links the external identity.

Architecture roles are `planner`, Hub `admin`, and Platform Admin. A SIG “Hub Expert” maps to the least-privilege GRP role, normally `planner`; it is not a separate GRP role. See [`docs/access-management.md`](docs/access-management.md) for the table map and provisioning commands.

## Staging deployment

The target is Ubuntu 24.04 at `staging-risk-servir.adpc.net`. Caddy runs on the host; the API is published only to `127.0.0.1:8000`; PostGIS has no host port.

The idempotent bootstrap installs the host dependencies, creates the filesystem layout and secrets, deploys the stack, and verifies health. It can either build from source on the VM or pull the prebuilt GHCR image:

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh --deploy-mode source
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh --deploy-mode image
```

Follow [`deploy/BOOTSTRAP.md`](deploy/BOOTSTRAP.md) for the first-run download commands, firewall safeguards, GHCR authentication, verification, and recovery steps. Use image mode for faster routine releases once the GitHub package is available.

Do not expose ports `8000` or `5432` publicly. Do not enable AI until Increment 6 has passed its acceptance tests.

## Development commands

```bash
make install         # install API and development dependencies
make test            # run the current offline test suite
make lint            # run Ruff checks
make migrate         # apply Alembic migrations using DATABASE_URL_FILE
make compose-config  # validate the staging Compose model
```

## Delivery order

Development follows the approved increments: server foundation; signed Chiang Yuen RP100 golden assessment; access and Admin; SIG sharing and evidence; review/downloads; additional data; vulnerability and AI; pilot hardening. The access foundation was brought forward to support the requested SIG account test. No fallback geography, dataset, or provider is permitted.

The next assessment work is Increment 1: add its remaining architecture-defined tables and build the queued assessment workflow against a scientifically approved Chiang Yuen RP100 golden fixture. Scientific expected values must come from the designated authority and must never be invented to make a test pass.

## Security

Never commit `.env`, tokens, credentials, private keys, raw uploads, or provisioning correspondence. Every route must declare `public`, `protected`, or `internal` access in its OpenAPI operation. Public or cross-Hub lookups must fail closed, and logs must not contain authorization headers, cookies, secrets, private geometry, or uploaded content.

See [`AGENTS.md`](AGENTS.md) for contribution requirements.
