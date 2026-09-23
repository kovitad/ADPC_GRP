# SERVIR Global Risk Platform

This repository is the implementation foundation for the ADPC Hub of the SERVIR Global Risk Platform (GRP) MVP 1. It follows solution architecture `GRP-ARC-001` version 2.2: ADPC owns access, data, GIS processing, and immutable assessment results; SIG reads only Admin-approved results to build traceable evidence and receipts.

> **Current status:** The local Docker Desktop build includes access and Admin controls, the metered AI gateway, Planner chat/map, receipt-bound SIG hazard/risk embeds, and the managed Thailand baseline. Under ADR-0015's explicit Product Owner approval assumption, Platform Admins can record the versioned SIG risk recipe and activate the imported boundaries, evacuation centres and RP100 hazard. ADR-0016 makes Planning display those available layers immediately; a queued assessment is optional rather than a prerequisite for seeing data. Local assessment proofs succeeded for Mueang Nan and Bang Bua Thong. Staging has not been deployed; see [`handovers.md`](handovers.md) for the exact revision, validation record and remaining production gates.

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
grpcli/           Server-side access administration commands
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

Replace the sample with the administrator's verified SIG email. The admin then opens `http://127.0.0.1:8000/admin`, authenticates through SIG, and reaches the protected approval panel. Platform Admins and Hub Admins add people by work email and can change and disable members of Hubs they manage, and the last active Hub Admin is protected. State-changing requests need the `X-CSRF-Token` header (value from the `grp_csrf` cookie). Sign-out and any role or access change end that person's sessions on the server. Authentication proves the SIG identity; only an active GRP membership grants application access. The interim sign-in flow is recorded in `docs/adr/0002-interim-sig-mcp-client-login.md`; its access token is not kept.

## LLM token preparation

AI is enabled only in the local Docker Desktop configuration and still defaults off for server deployments. Both environment templates contain provider, model, base URL, output limit, and `AI_KEY_FILE_ADPC`. Store a local token through hidden input:

```powershell
python -m grpcli.configure set-ai-key
```

This writes `.local/secrets/ai_key_adpc`, which Git ignores. On staging, place the token at `/srv/grp/secrets/ai_key_adpc` with root ownership and mode `0600`. Never put the raw token in `.env`; `.env` contains only the file path. Do not enable AI outside the approved local configuration until its deployment and budget controls are accepted.

## Run in Docker Desktop

The local stack runs PostGIS, Alembic migrations, the API (with the web screens) and the worker shell:

```powershell
.\scripts\docker-desktop.ps1 -AdminEmail you@adpc.net
```

Open `http://127.0.0.1:8000` (sign-in) or `http://127.0.0.1:8000/admin`. The script creates ignored secrets under `.local/docker/secrets`, reuses the localhost SIG client from `.\scripts\run-local.ps1 -RegisterSigClient`, runs migrations, and makes each `-AdminEmail` a Platform Admin with the `adpc` Hub. Stop it with `.\scripts\docker-desktop.ps1 -Down`; data stays in Docker volumes. This file is for local demos only; servers use `deploy/compose.yml`.

### Test the shelter upload and district workflow

In the local development build, a Platform Admin can open **Data library**, upload one ZIP with
the `ddpm_shelters` Shapefile components, and follow the background validation progress. Review
the quality counts, then choose **Use in new assessments** for the exact immutable version.

Open **Planning**, select a supported district, and choose **Data & run**. Confirm the flood
scenario, accepted shelter source, and method, then start the assessment. The drawer shows six
persisted worker steps; the finished map and **Centres** tab use the same feature IDs and list every
returned shelter name, status, reason, and mapped flood depth. The recommendation identifies only
lower-exposure candidates and explicitly leaves capacity, access, services, routes, and other
hazards for human review. Optional SIG context is separate and never blocks the local result.

The browser upload/accept action is a developer-only Platform baseline path. Production Hub-local
ownership and Hub Admin approval remain a later hardening step; uploaded data is never sent to SIG
automatically.

The current components, trust boundaries, worker sequence and production extension are diagrammed
in [`docs/shelter-upload-assessment-architecture.md`](docs/shelter-upload-assessment-architecture.md).

## Run on a shared Ubuntu host

When another application already owns ports 80/443, run the local demo stack on the Ubuntu loopback address and reach it through an SSH tunnel:

```bash
./scripts/docker-ubuntu.sh --register-sig-client --configure-ai --configure-langfuse \
  --admin-email you@adpc.net --hub-admin-email you@adpc.net
```

This binds only to `127.0.0.1:8000` and does not install or change Caddy. Keep port 8000 closed in the AWS security group; configure a PuTTY local tunnel from port 8000 to `127.0.0.1:8000`, then browse to `http://127.0.0.1:8000`. See [`deploy/UBUNTU_SHARED_HOST.md`](deploy/UBUNTU_SHARED_HOST.md) for prerequisites, reruns, status, shutdown, OAuth, and secret handling.

## Sign-in and membership mapping

GRP registration is only for people who already have a SIG/SERVIR account. It collects no local password or unverified identity data: the applicant must complete SERVIR authentication before a pending request appears. An unknown verified identity creates an `identity_link_denied` audit event for administrator review, but no user, external identity, or membership record. After an administrator assigns a Hub role, the user returns to sign in and GRP links the external identity.

Architecture roles are `ndmo_planner`, `hub_expert` (Hub Expert / GIS Specialist), Hub `admin`, and Platform Admin. The two planning roles have the same least-privilege planning access in this release; only Hub Admin manages Hub membership. See [`docs/access-management.md`](docs/access-management.md) for the table map and provisioning commands.

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

The queued assessment workflow is proved by the locked synthetic fixture and by local real-data execution against the imported six-tile RP100 baseline. Formal production acceptance still needs the authority-signed Chiang Yuen golden artifact; expected values must never be invented to make a test pass. The activation and recipe decision are recorded in [`ADR-0015`](docs/adr/0015-approved-sig-risk-recipe-and-baseline-activation.md).

## Security

Never commit `.env`, tokens, credentials, private keys, raw uploads, or provisioning correspondence. Every route must declare `public`, `protected`, or `internal` access in its OpenAPI operation. Public or cross-Hub lookups must fail closed, and logs must not contain authorization headers, cookies, secrets, private geometry, or uploaded content.

See [`AGENTS.md`](AGENTS.md) for contribution requirements.
