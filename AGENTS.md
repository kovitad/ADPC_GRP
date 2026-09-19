# Repository Guidelines

## Current state

Read [`handovers.md`](handovers.md) first. It has the current branch (`codex/sig-embedded-flood-map`), how to run the Docker Desktop stack, the architecture map, known gaps and the recommended next work. Record decisions in `docs/adr/` and update `handovers.md` at the end of each work session.

## Project Structure & Module Organization

The implementation follows the approved GRP boundaries. `api/` contains FastAPI modules for authentication, access, Admin, catalogs, uploads, assessments, AI, audit, health, and `integrations/sig`. `worker/` owns background GIS execution; web requests must never perform GIS work. `core/` holds shared domain models, validation, result invariants, database metadata, and the replaceable storage protocol. Alembic changes live in `migrations/`. Static frontend files are in `web/`; Ubuntu deployment assets are in `deploy/`. Tests are separated into `tests/fast`, `contract`, `golden`, `live`, and `load`. Record architecture changes in `docs/adr/`.

## Build, Test, and Development Commands

Use Python 3.12. Common commands are:

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m uvicorn api.main:app --reload
docker compose --env-file .env -f deploy/compose.yml config
```

`make install`, `make test`, `make lint`, and `make compose-config` provide the same workflows. Run `alembic upgrade head` separately during deployment; the application must not migrate automatically at startup.

## Coding Style & Naming Conventions

Use four-space Python indentation, type annotations, small modules, and Ruff-compatible formatting. Module and function names use `snake_case`; classes and enums use `PascalCase`; environment variables use `UPPER_SNAKE_CASE`. Keep API paths under `/api/v1`. Every documented operation must declare `x-grp-access` as `public`, `protected`, or `internal`. Use sentence-case Markdown headings and language-tagged code fences.

## Testing Guidelines

Name tests `test_<behavior>.py` and test observable rules, including success, failure, and permission cases. Fast tests run offline on every push. Contract tests cover schemas, route classification, SIG fixtures, and cross-Hub denial. Golden expected values require scientific approval and must never be changed merely to pass CI. Live tests require staging credentials and must not issue public receipts automatically.

## Commit & Pull Request Guidelines

Use concise, imperative, scoped subjects such as `feat: add assessment queue contract` or `test: enforce route access labels`. Pull requests must explain the behavior, identify the architecture section or ADR, list validation performed, and call out migrations, security events, configuration, and API changes.

## Security & Configuration

Never commit `.env`, secret files, tokens, cookies, private keys, raw uploads, or provisioning correspondence. Keep secrets in `/srv/grp/secrets` with root ownership and mode `0600`; configuration references them through `_FILE` variables. Fail closed on unknown users, Hubs, areas, fingerprints, and upstream data.
