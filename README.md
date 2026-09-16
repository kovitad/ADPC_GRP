# SERVIR Global Risk Platform

This repository is the implementation foundation for the ADPC Hub of the SERVIR Global Risk Platform (GRP) MVP 1. It follows solution architecture `GRP-ARC-001` version 2.2: ADPC owns access, data, GIS processing, and immutable assessment results; SIG reads only Admin-approved results to build traceable evidence and receipts.

> **Current status:** Increment 0 foundation complete, with the sign-in and access-guidance UI delivered early. Health endpoints, module boundaries, configuration loading, deployment manifests, tests, and CI exist. Increment 1 has not started: database tables, migrations, the assessment queue, GIS processing, and the signed Chiang Yuen golden case remain to be implemented. The SERVIR OIDC adapter, sessions, membership enforcement, downloads, AI, and the live SIG evidence connection remain unimplemented.

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
web/              Responsive sign-in and Hub access-guidance screens
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

Preview the static sign-in screens separately:

```powershell
python -m http.server 4173 --directory web
```

Open `http://127.0.0.1:4173`. This static preview does not proxy API requests; append `/?auth=unavailable` to review the error state. In the deployed stack, the login entry returns to that state until the approved SERVIR OIDC adapter and GRP membership model are implemented.

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

Development follows the approved increments: server foundation; signed Chiang Yuen RP100 golden assessment; access and Admin; SIG sharing and evidence; review/downloads; additional data; vulnerability and AI; pilot hardening. No fallback geography, dataset, or provider is permitted.

The next work is Increment 1: implement the architecture-defined database schema and first migration, then build the queued assessment workflow against a scientifically approved Chiang Yuen RP100 golden fixture. Scientific expected values must come from the designated authority and must never be invented to make a test pass.

## Security

Never commit `.env`, tokens, credentials, private keys, raw uploads, or provisioning correspondence. Every route must declare `public`, `protected`, or `internal` access in its OpenAPI operation. Public or cross-Hub lookups must fail closed, and logs must not contain authorization headers, cookies, secrets, private geometry, or uploaded content.

See [`AGENTS.md`](AGENTS.md) for contribution requirements.
