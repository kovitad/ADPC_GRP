# Staging deployment foundation

The staging host runs Ubuntu 24.04. Caddy is installed as a host systemd service. FastAPI, the worker, and PostGIS run with Docker Compose. Only ports 80 and 443 are application-facing; Docker publishes the API to host loopback only and does not publish PostgreSQL.

## Required server paths

```text
/srv/grp/app/                    repository checkout
/srv/grp/data/                   rasters, accepted uploads, and locked results
/srv/grp/releases/               release manifests
/srv/grp/secrets/                root-owned files, mode 0600
/srv/grp/backup-staging/         temporary encrypted backup files
```

Create these secret files before starting Compose:

```text
database_url                    postgresql+psycopg://grp:<password>@db:5432/grp
postgres_password               password matching database_url
session_secret                  cryptographically random session signing value
servir_auth_client_secret       required in Increment 2
sig_service_token_hash          staging fallback only, required in Increment 3
ai_key_adpc                     required only after Increment 6 approval
langfuse_secret_key             required only when AI monitoring is enabled
```

Never store raw secrets in `.env`, Git, container images, logs, shell history, or screenshots. Production requires separate keys, database, files, certificates, SIG machine identity, AI allowance, and backup set.

## Release outline

1. Record the image digest and migration revision.
2. Take a backup.
3. Run `docker compose ... run --rm api alembic upgrade head` once.
4. Start the API and worker.
5. Check loopback readiness and public liveness.
6. Run golden and contract tests when those layers are implemented.

Rollback is code-only when database compatibility is preserved. Otherwise restore the coordinated database and file backup.
