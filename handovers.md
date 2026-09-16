# GRP MVP 1 Project Handover

**Updated:** 16 September 2026

**Repository:** <https://github.com/kovitad/ADPC_GRP>

**Branch:** `main`
**Current phase:** Increment 0 complete; first Increment 2 identity and membership slice implemented early

## Current position

The repository now provides a tested, architecture-aligned foundation for the ADPC Hub of the SERVIR Global Risk Platform. It is intentionally a scaffold, not a working flood-assessment product.

| Area | Current state |
|---|---|
| FastAPI | Application factory, configuration loading, public `/api/v1/healthz`, and internal `/api/v1/readyz` |
| API modules | Standard OIDC authorization-code/PKCE flow, callback verification, signed sessions, and protected `/api/v1/me` exist; login fails closed until SERVIR configuration is supplied |
| Worker | Runnable process and shutdown handling exist; PostgreSQL job claiming and GIS processing are not implemented |
| Database | The first forward-only migration implements `hub`, `app_user`, `external_identity`, `hub_membership`, and `audit_event`; the remaining architecture tables are pending |
| Deployment | Idempotent Ubuntu bootstrap, source/image release modes, GHCR publishing, hardened secret staging, Compose services, host Caddy configuration, and an operator runbook exist; the VM has not yet been bootstrapped from this repository |
| Web | Registration for existing SIG accounts, SERVIR sign-in, unavailable/failed/pending states, and a protected membership/Admin view exist |
| Access administration | A protected Platform Admin panel/API lists pending verified identities and assigns `planner`/`admin`; idempotent CLI commands provide bootstrap and recovery |
| Tests and CI | Nineteen offline tests cover liveness, result invariants, route classification, registration guardrails, OIDC verification, unknown-user denial, protected admin assignment, and membership mapping |

## Architecture guardrails

The implementation follows `GRP-ARC-001` version 2.2.

- The GIS worker is the only calculator. Screens, SIG, downloads, and AI read the same immutable result.
- Every assessment is an asynchronous job with pinned boundary, dataset, method, and SHA-256 fingerprints.
- Unsupported or mismatched inputs stop with typed errors. Never substitute a fallback area, dataset, route, or provider.
- GRP owns users, Hub access, private data, methods, jobs, and results. SIG reads only Admin-approved evidence through a read-only endpoint.
- SERVIR sign-in proves identity; GRP database membership determines Hub and role.
- AI explains stored results only and remains disabled until Increment 6 is accepted.
- A SIG receipt proves traceability, not scientific correctness or center safety.

Any change to these rules requires an ADR and the approvals defined by the architecture baseline.

## Validation completed

The current foundation has passed:

```text
Ruff                       passed
pytest                     19 passed
Python dependency check    passed
Compose model validation   passed
Deployment shell syntax    passed locally
staged secret scan         passed
GitHub Actions CI          passed at 0f4391a
Container image workflow   passed at 0f4391a
```

The access implementation passed GitHub CI and the container workflow at feature commit `0f4391a`. The image was not built locally because Docker Desktop was not running. Before using image mode, confirm the GHCR package is visible for that commit, then execute the staging smoke checks in [`deploy/BOOTSTRAP.md`](deploy/BOOTSTRAP.md).

## Configuration and security

`.env.example` contains safe staging defaults and secret file paths only. The real `.env`, architecture sources, integration captures, and provisioning correspondence are intentionally ignored and are not in the public repository.

On the server, secret values belong in root-owned files under `/srv/grp/secrets` with mode `0600`. Live login needs a SERVIR OIDC issuer, client ID, exact callback URI, and `servir_auth_client_secret`; a pre-existing SIG user account alone is insufficient. Do not put tokens, passwords, private keys, OAuth client secrets, or database credentials in Git, `.env`, container images, logs, screenshots, or issue comments.

Unknown verified identities are recorded in the audit table as pending access requests but do not create users, identity links, or memberships. The administrator notification appears in the protected Platform Admin workspace; the server-side `list-access-requests` command is the fallback. No email is sent. Provision roles with the audited workflow in [`docs/access-management.md`](docs/access-management.md).

The staging target is Ubuntu 24.04 at `staging-risk-servir.adpc.net`, sized at 4 vCPU, 16 GB memory, and 250 GB disk. Caddy should expose HTTPS; FastAPI remains on `127.0.0.1:8000`, and PostGIS has no host port. SSH addresses and credentials must stay in the secure operations channel.

For the first server run, download the reviewed bootstrap to `/srv/grp/bootstrap/bootstrap-ubuntu.sh` and run source mode. After the GHCR package is available, use image mode for faster releases. Firewall activation remains deliberately opt-in and requires an approved SSH source CIDR.

## Next implementation slice

Proceed in this order:

1. Register GRP as a dedicated application in SERVIR identity, set its exact staging callback, and install the client secret on the VM.
2. Validate first Platform Admin and Hub membership provisioning using the documented CLI flow.
3. Add PostgreSQL migration and cross-Hub isolation tests.
4. Obtain the approved Chiang Yuen boundary, RP100 flood input, evacuation-center fixture, method, NoData rule, fingerprints, and signed expected result from the Scientific and Data Authority.
5. Add the remaining tables, immutable storage, assessment validation, idempotent queueing, leases, typed failures, and signed golden-result proof.

Do not invent or commit placeholder scientific values. The base SERVIR adapter is implemented for Increment 2, but provider registration and a live acceptance test remain outstanding. The SIG machine identity and evidence endpoint belong to Increment 3.

## Resume commands

```powershell
git pull --ff-only
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest
docker compose --env-file .env -f deploy/compose.yml config
```

Read [`README.md`](README.md), [`AGENTS.md`](AGENTS.md), and the secure copy of `GRP-ARC-001` version 2.2 before changing application behavior.
