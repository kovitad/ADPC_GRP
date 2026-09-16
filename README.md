# SERVIR Global Risk Platform

This repository is the implementation foundation for the ADPC Hub of the SERVIR Global Risk Platform (GRP) MVP 1. It follows solution architecture `GRP-ARC-001` version 2.2: ADPC owns access, data, GIS processing, and immutable assessment results; SIG reads only Admin-approved results to build traceable evidence and receipts.

> **Current status:** Increment 0 foundation complete. Health endpoints, module boundaries, configuration loading, deployment manifests, tests, and CI exist. Increment 1 has not started: database tables, migrations, the assessment queue, GIS processing, and the signed Chiang Yuen golden case remain to be implemented. Authentication, downloads, AI, and the live SIG evidence connection also remain unimplemented.

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
web/              Static web-app foundation
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
Copy-Item .env.example .env
python -m pytest
python -m uvicorn api.main:app --reload
```

Then open `http://127.0.0.1:8000/api/v1/healthz`. The public response intentionally contains no infrastructure detail.

## Staging deployment

The target is Ubuntu 24.04 at `staging-risk-servir.adpc.net`. Caddy runs on the host; the API is published only to `127.0.0.1:8000`; PostGIS has no host port.

1. Install Docker Engine, the Compose plugin, and Caddy 2.
2. Place the checkout under `/srv/grp/app`.
3. Create `/srv/grp/data`, `/srv/grp/secrets`, and the secret files described in [`deploy/README.md`](deploy/README.md).
4. Copy `.env.example` to `.env` and fill only environment-specific, non-secret values. Keep secret values in root-owned `0600` files.
5. Validate and start the stack:

```bash
docker compose --env-file .env -f deploy/compose.yml config
docker compose --env-file .env -f deploy/compose.yml up -d --build
curl --fail http://127.0.0.1:8000/api/v1/healthz
```

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

Development follows the approved increments: server foundation; signed Chiang Yuen RP100 golden assessment; access and Admin; SIG sharing and evidence; review/downloads; additional data; vulnerability and AI; pilot hardening. No fallback geography, dataset, or provider is permitted.

The next work is Increment 1: implement the architecture-defined database schema and first migration, then build the queued assessment workflow against a scientifically approved Chiang Yuen RP100 golden fixture. Scientific expected values must come from the designated authority and must never be invented to make a test pass.

## Security

Never commit `.env`, tokens, credentials, private keys, raw uploads, or provisioning correspondence. Every route must declare `public`, `protected`, or `internal` access in its OpenAPI operation. Public or cross-Hub lookups must fail closed, and logs must not contain authorization headers, cookies, secrets, private geometry, or uploaded content.

See [`AGENTS.md`](AGENTS.md) for contribution requirements.
