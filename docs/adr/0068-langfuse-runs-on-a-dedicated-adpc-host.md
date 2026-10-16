# ADR-0068: Langfuse runs on a dedicated ADPC host

- **Status:** Accepted
- **Date:** 15 October 2026

## Context

ADR-0035 selected Langfuse Cloud Hobby while GRP's telemetry and evaluation workflow was being designed. ADPC has now provisioned a dedicated Ubuntu 24.04 VM for Langfuse at `langfuse-risk-servir.adpc.net`. The VM has 4 vCPU, 16 GiB RAM and approximately 250 GB of disk. Keeping observability separate from the GRP application hosts prevents its PostgreSQL, ClickHouse, Redis, object-storage and worker workloads from competing with operational assessment services.

The existing synthetic Cloud demonstration remains non-operational evidence. Moving it or production telemetry is a separate, explicit activity.

## Decision

Run Langfuse OSS on the dedicated ADPC VM using the upstream Docker Compose topology and these controls:

- pin the application containers to Langfuse `4.59.0`;
- retain the upstream PostgreSQL 17, ClickHouse 25.12, Redis 7 and MinIO topology;
- terminate public HTTPS with Caddy and Let's Encrypt at `langfuse-risk-servir.adpc.net`;
- publish only ports 80 and 443; bind the web diagnostic port, object storage, databases and cache to loopback;
- route path-style object requests under `/langfuse/*` to MinIO through the same HTTPS origin;
- store generated runtime secrets only in root-owned `/srv/langfuse/.env` with mode `0600`;
- disable upstream product telemetry and disable open account signup;
- initialize one owner account and a staging project headlessly, then create separate evaluation and production projects;
- run the stack through an enabled `langfuse.service` systemd unit;
- use Docker's rotating `local` log driver rather than unbounded JSON logs; and
- keep production AI export disabled until backup, retention, access review and an explicit cutover are complete.

The repository vendors the exact upstream Compose file from Langfuse tag `v4.59.0`/commit `3aa29f7b41e3e007ab1efd2856ffca50ee7a9006`. Local controls are isolated in `deploy/langfuse/compose.override.yml` and `deploy/langfuse/Caddyfile`.

## Consequences

ADPC controls trace residency and user access, and Cloud seat limits no longer constrain the team. ADPC also owns patching, certificate monitoring, capacity, backups and recovery. This single-node Compose deployment has no high availability.

The first deployment is suitable for setup and evaluation, not yet for production telemetry. Before production cutover, operators must:

1. complete and restore-test PostgreSQL, ClickHouse and MinIO backups;
2. approve retention and storage thresholds;
3. remove headless initialization secrets after the owner confirms access;
4. create narrowly scoped project API keys and rotate the existing Cloud credentials;
5. configure the GRP staging and production applications independently; and
6. prove that a Langfuse outage cannot fail a GRP response.

## Alternatives considered

- **Continue only with Langfuse Cloud.** Operationally simpler, but does not use the approved ADPC-hosted environment and retains external residency and seat dependencies.
- **Install Langfuse on a GRP application host.** Rejected because observability databases and workers would compete with operational services and increase the failure blast radius.
- **Use Kubernetes immediately.** Rejected for the initial measured volume; it adds operational complexity without a current high-availability requirement.
