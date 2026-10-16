# Langfuse self-hosted operations

This directory records the dedicated ADPC deployment selected by [ADR-0068](../../docs/adr/0068-langfuse-runs-on-a-dedicated-adpc-host.md).

## Deployed host

- URL: <https://langfuse-risk-servir.adpc.net>
- Internal SSH: `ubuntu@10.4.0.210:22`
- External SSH: `ubuntu@147.50.36.42:2100` (the external mapping was not reachable during installation)
- OS: Ubuntu Server 24.04
- Application: Langfuse OSS 4.59.0
- Install root: `/srv/langfuse`
- Service: `langfuse.service`

The repository does not contain server passwords, Langfuse API keys, application passwords or generated infrastructure secrets.

## Files

- `compose.upstream.yml` is the unchanged upstream file from Langfuse `v4.59.0`, commit `3aa29f7b41e3e007ab1efd2856ffca50ee7a9006`.
- `compose.override.yml` pins the Langfuse patch release, adds Caddy, disables open signup and binds non-public services to loopback.
- `Caddyfile` terminates HTTPS and proxies path-style MinIO requests.

Both Compose files must be supplied together:

```bash
docker compose \
  -f compose.upstream.yml \
  -f compose.override.yml \
  config --quiet
```

## Routine checks

From an authorized workstation:

```bash
curl --fail https://langfuse-risk-servir.adpc.net/api/public/health
ssh ubuntu@10.4.0.210 'systemctl is-active langfuse; docker ps'
```

The public health response must be HTTP 200. Only ports 80 and 443 are public application ports. Ports 3000, 3030, 9090, 9091, 5432, 6379, 8123 and 9000 must not be externally reachable.

For logs:

```bash
ssh ubuntu@10.4.0.210
sudo journalctl -u langfuse --since today
cd /srv/langfuse
sudo docker compose -f compose.upstream.yml -f compose.override.yml logs --tail 200 langfuse-web langfuse-worker caddy
```

## Authentication handoff

Google OAuth is enabled for verified `adpc.net` and `sig-gis.com` accounts. Ordinary username/password authentication is disabled. Account creation is temporarily enabled through Google only so the two approved owners can establish their accounts. Google account linking is enabled because the provider verifies email ownership.

The initial owner is `kovitad.janlakhon@adpc.net`. A generated bootstrap password remains temporarily at `/home/ubuntu/langfuse-initial-admin.txt`, but password authentication is disabled. Delete this file after Google sign-in is proven.

After both approved owners have signed in with Google, set `AUTH_DISABLE_SIGNUP=true` in root-only `/srv/langfuse/.env` and recreate `langfuse-web`. Existing Google users will continue to sign in, while new account creation will be blocked. Do not print the environment file.

Headless initialization values also remain in `/srv/langfuse/.env`. Remove every `LANGFUSE_INIT_*` entry after owner access and project API-key custody are confirmed.

## Current projects

The `ADPC GRP` organization has separate projects:

- `GRP Staging`
- `GRP Evaluation`
- `GRP Production`

Creating a project does not authorize telemetry. Production remains unconnected until the ADR-0068 gates are complete.

## Upgrade

Do not change the floating upstream `:4` references alone. Review a specific Langfuse release, vendor its Compose file, update both pinned application images in the override, validate the merged configuration, take backups and then perform a controlled pull/recreate. Record the tested release and rollback result.

## Backup gap

No backup or restore rehearsal is implemented yet. PostgreSQL, ClickHouse and MinIO volumes all contain required state; Docker volume copies while services are writing are not a valid backup design. Do not enable production export until a consistent backup procedure and restore test are recorded.
