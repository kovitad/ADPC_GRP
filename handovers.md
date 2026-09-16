# GRP MVP 1 Project Handover

**Updated:** 16 September 2026

**Repository:** <https://github.com/kovitad/ADPC_GRP>

**Branch:** `main`
**Current phase:** Increment 0 application foundation and sign-in/access UI complete; Increment 1 implementation not started

## Current position

The repository now provides a tested, architecture-aligned foundation for the ADPC Hub of the SERVIR Global Risk Platform. It is intentionally a scaffold, not a working flood-assessment product.

| Area | Current state |
|---|---|
| FastAPI | Application factory, configuration loading, public `/api/v1/healthz`, and internal `/api/v1/readyz` |
| API modules | Boundaries exist for auth, access, Admin, catalog, uploads, assessments, AI, audit, health, and SIG integration; the public login entry fails closed until OIDC is configured and other business routes remain placeholders |
| Worker | Runnable process and shutdown handling exist; PostgreSQL job claiming and GIS processing are not implemented |
| Database | SQLAlchemy base and Alembic environment exist; the 16 architecture tables and first migration do not |
| Deployment | Idempotent Ubuntu bootstrap, source/image release modes, GHCR publishing, hardened secret staging, Compose services, host Caddy configuration, and an operator runbook exist; the VM has not yet been bootstrapped from this repository |
| Web | Responsive SERVIR sign-in, unavailable-provider state, and non-self-registration access guidance exist; no Planner or Admin workspace functionality |
| Tests and CI | Seven offline tests cover liveness, result-count invariants, route access classification, login fail-closed behavior, and authentication-screen guardrails; GitHub CI runs Ruff and pytest |

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
pytest                     7 passed
Python dependency check    passed
Compose model validation   passed
Deployment shell syntax    passed locally
staged secret scan         passed
GitHub Actions CI          passed at the prior commit
```

The current deployment update adds shell syntax checks to CI and a GitHub Actions workflow that builds and publishes `ghcr.io/kovitad/adpc_grp`. The container image was not built locally because Docker Desktop was not running. Confirm both workflows pass at the resulting commit before using image mode, and execute the staging smoke checks in [`deploy/BOOTSTRAP.md`](deploy/BOOTSTRAP.md).

## Configuration and security

`.env.example` contains safe staging defaults and secret file paths only. The real `.env`, architecture sources, integration captures, and provisioning correspondence are intentionally ignored and are not in the public repository.

On the server, secret values belong in root-owned files under `/srv/grp/secrets` with mode `0600`. Do not put tokens, passwords, private keys, OAuth client secrets, or database credentials in Git, `.env`, container images, logs, screenshots, or issue comments.

The staging target is Ubuntu 24.04 at `staging-risk-servir.adpc.net`, sized at 4 vCPU, 16 GB memory, and 250 GB disk. Caddy should expose HTTPS; FastAPI remains on `127.0.0.1:8000`, and PostGIS has no host port. SSH addresses and credentials must stay in the secure operations channel.

For the first server run, download the reviewed bootstrap to `/srv/grp/bootstrap/bootstrap-ubuntu.sh` and run source mode. After the GHCR package is available, use image mode for faster releases. Firewall activation remains deliberately opt-in and requires an approved SSH source CIDR.

## Next implementation slice

Proceed with Increment 1 in this order:

1. Implement the architecture-defined SQLAlchemy models and initial forward-only Alembic migration.
2. Add database isolation and migration tests against PostgreSQL/PostGIS.
3. Obtain the approved Chiang Yuen boundary, RP100 flood input, evacuation-center fixture, method, NoData rule, fingerprints, and signed expected result from the Scientific and Data Authority.
4. Add the immutable storage implementation and seed command for the approved golden case.
5. Implement assessment validation, idempotent submission, PostgreSQL queue claiming with `FOR UPDATE SKIP LOCKED`, leases, and typed failure states.
6. Implement result persistence and prove it matches the signed golden answer exactly.

Do not invent or commit placeholder scientific values. SERVIR authentication belongs to Increment 2; the SIG machine identity and evidence endpoint belong to Increment 3.

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
