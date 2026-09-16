# Staging deployment

The Ubuntu 24.04 staging host uses Caddy as a systemd service and Docker Compose for FastAPI, the worker, and PostGIS. Caddy is the only public application entry point. FastAPI binds to `127.0.0.1:8000`; PostgreSQL has no host port.

Start with the operational runbook in [`BOOTSTRAP.md`](BOOTSTRAP.md). The bootstrap supports two release paths:

- `source` (default) builds the container on the VM. It is slower but works before a registry image exists.
- `image` pulls `ghcr.io/kovitad/adpc_grp:main`, built by GitHub Actions. This is the faster normal release path after the package is available.

## Server layout

```text
/srv/grp/bootstrap/       downloaded bootstrap script
/srv/grp/app/             repository checkout and non-secret .env
/srv/grp/data/            rasters, uploads, and locked results
/srv/grp/releases/        release manifests and Caddy backups
/srv/grp/secrets/         root-owned secret files, mode 0600
/srv/grp/backup-staging/  temporary encrypted backup files
```

The bootstrap creates `postgres_password`, `database_url`, and `session_secret` without overwriting existing values. Later increments require operator-supplied `servir_auth_client_secret`, `sig_service_token_hash`, `ai_key_adpc`, and `langfuse_secret_key` files.

Compose mounts host secrets read-only. A root entrypoint copies them into a container-only tmpfs with ownership for UID `10001`, then starts GRP as that non-root user. Secret values must never appear in `.env`, Git, images, logs, shell history, or screenshots.

## Release and rollback rules

Each deployment validates Compose, starts PostGIS, applies `alembic upgrade head` once, starts the API and worker, checks loopback health, and records a manifest under `/srv/grp/releases`.

Before a release that changes persistent data, take a coordinated database and file backup. Roll back code by deploying a previously tested Git ref or immutable image digest. If a migration is not backward compatible, restore the matching database and files; never improvise a downgrade on staging.

Production must use separate keys, database, files, certificates, SIG machine identity, AI allowance, and backups.
