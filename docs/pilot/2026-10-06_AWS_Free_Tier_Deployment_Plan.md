# AWS free-tier deployment plan for `servir-risk.kovitad.com`

**Status:** Planned; no AWS, DNS, registry, OAuth or public-feed change has been made.  
**Target:** A temporary, low-traffic GRP staging trial on an AWS 1 GB RAM / 2 vCPU / 40 GB SSD host.  
**Domain:** `servir-risk.kovitad.com`.  
**Release method:** Build and test in GitHub Actions, publish an immutable GHCR image, and only pull/run it on AWS.

## 1. Decision and limits

The free-tier host is acceptable for a first controlled trial if it does not build the image and is not treated as production. It should prove deployment, HTTPS, health, SERVIR sign-in, a small read-only MCP workflow and one-at-a-time background work.

It is not an acceptance environment for capacity. One GB remains below the recommended full-stack staging size. PostgreSQL/PostGIS, the API and GIS worker may enter swap or be killed during imports and assessments. Upgrade to 2–4 GB if normal use repeatedly swaps, restarts containers or exceeds the thresholds below.

For the first deployment:

- use Ubuntu 24.04 **x86-64/AMD64**, because the current GitHub workflow publishes `linux/amd64` only;
- use deployment `image` mode, never source-build mode on this host;
- add 3 GB encrypted-host swap before starting the stack;
- use Langfuse Cloud rather than self-hosting Langfuse;
- keep AI optional and off until its configuration and allowance are reviewed;
- keep public flood and air-quality feed switches off;
- defer the 2.1 GB Thailand source-bundle import until the empty-stack deployment and resource measurements pass;
- run no more than one import or assessment job at once;
- do not call this production or promise availability.

## 2. Architecture

```text
GitHub push to reviewed main
          |
          v
GitHub Actions: tests + linux/amd64 image build
          |
          v
GHCR: ghcr.io/kovitad/adpc_grp:sha-<commit>
          |
          | docker pull (no compilation on AWS)
          v
AWS Ubuntu 24.04 x86-64, 1 GB RAM, 40 GB disk
  Caddy :80/:443  -> static web + /api proxy
  FastAPI          -> 127.0.0.1:8000 only
  Worker           -> internal network, one job at a time
  PostgreSQL/PostGIS -> internal network, no public port
  /srv/grp/data, /srv/grp/tmp, /srv/grp/secrets
          |
          +---- HTTPS: https://servir-risk.kovitad.com
          +---- outbound: SERVIR Global Risk MCP / OIDC
          +---- outbound: approved source APIs
          +---- outbound: Langfuse Cloud when enabled
```

## 3. Cost and account guardrail

AWS free-tier and public-IPv4 terms vary by account age, product and region. Before creating anything, confirm the console's exact monthly estimate. “Free tier eligible” does not guarantee zero cost for public IPv4, snapshots, excess egress, DNS hosting or usage after the offer ends.

Create before the instance:

1. an AWS Budget alert at a small amount such as USD 1;
2. alerts at 50%, 80% and 100%;
3. a calendar reminder for the free-period/credit expiry;
4. one project tag, for example `Project=ADPC-GRP-Trial`;
5. a written deletion list: instance, disk, snapshots, static/public IP and any Route 53 zone if one is created.

Keep DNS with the existing `kovitad.com` provider unless there is a reason to move it. A Route 53 hosted zone has a recurring charge and is not required just to create one subdomain.

## 4. Release gate before AWS

Do not deploy the current working tree directly. The current development branch contains local work and is ahead of its remote. Complete review, commit intended changes, push them and merge the approved release into `main` first.

The existing workflow `.github/workflows/container.yml`:

- runs on a push to `main` or manual dispatch;
- builds `linux/amd64` from `deploy/Dockerfile`;
- pushes `ghcr.io/kovitad/adpc_grp:main` and `sha-<commit>`;
- publishes provenance and an SBOM.

Before deployment, require:

```text
[ ] CI tests and lint pass for the exact commit
[ ] Container workflow succeeds
[ ] GHCR image digest is recorded
[ ] The SHA tag can be pulled
[ ] The GHCR package is public, or a read:packages login is prepared safely
[ ] No source data, .env file or secret is inside the image
```

Deploy the immutable `sha-<commit>` tag, not `main`. `main` can move after testing; the SHA tag identifies the exact rollback artifact.

Do not use a manual workflow run from an unreviewed feature branch if it would overwrite the shared `main` image tag.

## 5. Create the AWS host

Use either a free-tier-eligible EC2 instance or a free-trial Lightsail bundle that actually shows the intended price in the owner's console.

Required host properties:

- Ubuntu 24.04 LTS;
- x86-64/AMD64 architecture;
- 1 GB RAM, 2 vCPU and 40 GB SSD for this trial;
- one stable public IPv4 address for DNS;
- automatic OS security updates or a patch routine;
- no public database port.

A normal ephemeral EC2 public IP may change after stop/start. Use a stable address for the subdomain. Check the displayed AWS charge for an Elastic IP/public IPv4. A Lightsail static IP is normally attached to its instance, but the current account's pricing remains authoritative.

### Network rules

Allow inbound:

| Port | Source | Purpose |
| --- | --- | --- |
| SSH port (normally 22) | Owner's current public IP `/32`, or approved VPN CIDR | Administration |
| TCP 80 | `0.0.0.0/0` and `::/0` only if IPv6 is configured | Caddy ACME redirect/challenge |
| TCP 443 | `0.0.0.0/0` and `::/0` only if IPv6 is configured | HTTPS application |

Do not allow inbound 5432, 8000 or Docker daemon ports. FastAPI remains bound to `127.0.0.1:8000`; PostgreSQL remains on the internal Compose network.

Use an SSH key, disable password SSH, and store the private key outside Git and the VM backups.

## 6. Point `servir-risk.kovitad.com` at AWS

After assigning the stable IPv4 address, create this record at the current DNS provider:

```text
Type: A
Name/Host: servir-risk
Value: <AWS stable public IPv4>
TTL: 300 during setup
```

Add an `AAAA` record only if the instance, security rules and Caddy path are intentionally configured for IPv6. A wrong `AAAA` record can make TLS appear intermittently broken.

Check before bootstrap:

```bash
dig +short servir-risk.kovitad.com A
```

It must return the AWS address. If the DNS provider offers HTTP proxying, use DNS-only for the first Caddy certificate test. Proxying can be enabled later with an explicitly reviewed TLS mode.

Caddy will request and renew the certificate automatically after DNS resolves and ports 80/443 reach the VM.

## 7. Prepare the 1 GB host

Connect with SSH and patch first:

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo reboot
```

Reconnect, then create 3 GB swap:

```bash
sudo fallocate -l 3G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
printf '/swapfile none swap sw 0 0\n' | sudo tee -a /etc/fstab
printf 'vm.swappiness=20\n' | sudo tee /etc/sysctl.d/99-grp-small-host.conf
sudo sysctl --system
free -h
```

Swap is emergency protection, not extra performance. Heavy swapping means the instance should be upgraded.

Bound Docker log growth on this dedicated trial host before containers start:

```bash
sudo install -d -m 0755 /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "local",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
JSON
```

The bootstrap installs Docker later; the configuration will be picked up when Docker starts. If Docker is already running, validate the file and restart Docker during a maintenance window.

## 8. Deploy with the existing reviewed bootstrap

Download and inspect the script from the approved `main` release:

```bash
sudo install -d -m 0755 /srv/grp/bootstrap
sudo curl -fsSL \
  https://raw.githubusercontent.com/kovitad/ADPC_GRP/main/deploy/bootstrap-ubuntu.sh \
  -o /srv/grp/bootstrap/bootstrap-ubuntu.sh
sudo chmod 0755 /srv/grp/bootstrap/bootstrap-ubuntu.sh
less /srv/grp/bootstrap/bootstrap-ubuntu.sh
```

If GHCR is private, authenticate interactively with a token that has only `read:packages`; never put it in the command, repository, `.env` or chat:

```bash
read -rsp "GHCR token: " GHCR_TOKEN; echo
printf '%s' "$GHCR_TOKEN" | sudo docker login ghcr.io -u kovitad --password-stdin
unset GHCR_TOKEN
```

Deploy the exact image:

```bash
export GRP_RELEASE_SHA='<approved-commit-sha>'
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh \
  --deploy-mode image \
  --image "ghcr.io/kovitad/adpc_grp:sha-${GRP_RELEASE_SHA:0:7}" \
  --domain servir-risk.kovitad.com
unset GRP_RELEASE_SHA
```

Confirm the actual tag emitted by `docker/metadata-action`; use the registry's displayed immutable digest if there is any doubt. Do not copy a real secret into shell history.

The bootstrap will:

- install Docker Engine, Compose and Caddy;
- create `/srv/grp` directories;
- clone the repository for Compose, web assets and deployment files;
- generate PostgreSQL and session secrets under `/srv/grp/secrets`;
- set `GRP_PUBLIC_BASE_URL=https://servir-risk.kovitad.com`;
- set the callback to `https://servir-risk.kovitad.com/api/v1/auth/callback`;
- pull the image;
- start PostGIS;
- run `alembic upgrade head` separately;
- start API and worker;
- check loopback health;
- configure Caddy and HTTPS.

Do not pass `--bootstrap-thailand-data` during the first free-tier deployment.

## 9. Configure SERVIR sign-in

The new public callback is:

```text
https://servir-risk.kovitad.com/api/v1/auth/callback
```

Register or request a callback-specific public PKCE client for that exact URI. A normal SERVIR user login is not an application client credential. Put only the non-secret client ID in `/srv/grp/app/.env` as `SERVIR_AUTH_CLIENT_ID`. Keep any supported confidential client secret in `/srv/grp/secrets`, never `.env`.

Then rerun image deployment; the script preserves secrets and `.env` while updating approved values:

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh \
  --deploy-mode image \
  --image 'ghcr.io/kovitad/adpc_grp:sha-<approved-short-sha>' \
  --domain servir-risk.kovitad.com
```

Provision the first Platform Admin and ADPC Hub only with the approved administrator email, following `docs/access-management.md`. Do not write the email into this public plan.

## 10. First verification: empty stack

Run on the VM:

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh \
  --deploy-mode image \
  --image 'ghcr.io/kovitad/adpc_grp:sha-<approved-short-sha>' \
  --domain servir-risk.kovitad.com \
  --check-only

sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml ps

curl --fail http://127.0.0.1:8000/api/v1/healthz
curl --fail https://servir-risk.kovitad.com/api/v1/healthz
sudo journalctl -u caddy --since '15 minutes ago' --no-pager
free -h
df -h /
sudo docker stats --no-stream
```

From an outside browser/network:

1. open `https://servir-risk.kovitad.com`;
2. confirm the certificate matches the hostname;
3. confirm HTTP redirects to HTTPS;
4. confirm `/api/v1/healthz` returns `{"status":"ok"}`;
5. confirm `/api/v1/readyz` is not public through Caddy;
6. complete SERVIR sign-in after the callback client is configured;
7. confirm the correct person, Hub and role;
8. test a read-only page and one read-only Global Risk MCP workflow;
9. confirm public feed routes still return 404 while their switches are off;
10. inspect browser console and API/worker logs for errors without exposing tokens.

## 11. Free-tier resource acceptance gate

Observe for at least 30 minutes idle and through one bounded read-only MCP lookup. Then, separately, run one small background assessment only after the empty stack is stable.

Continue on the free host only if:

- no container restarts or OOM-killed state;
- at least about 150 MB RAM remains available at idle, or swap use is stable and small;
- normal read-only use does not continuously swap;
- root disk remains below 70%;
- API health remains responsive while the worker is idle;
- one background job completes without making health checks fail;
- p95 response and job durations are acceptable for a trial;
- logs remain bounded.

Upgrade or separate services if:

- a container is OOM-killed once during normal operation;
- swap grows continuously or exceeds about 1 GB during ordinary use;
- health checks fail during one job;
- the database or worker repeatedly restarts;
- disk exceeds 80%;
- two users cannot perform normal read-only work reliably.

Useful commands:

```bash
free -h
vmstat 1 10
sudo docker stats --no-stream
sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml ps
sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml logs --tail 200
df -h /
sudo du -sh /var/lib/docker /srv/grp/data /srv/grp/tmp 2>/dev/null
```

If only the website and read-only API are being demonstrated, the worker may be stopped temporarily to preserve memory, but queued assessments/imports will not run:

```bash
sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml stop worker
```

Restart it before testing any background workflow.

## 12. Two live-data pilots: PM2.5 and ThaiWater

The temporary host will exercise both real sources while the development team's long-term environment is pending. They have different contracts and must remain visibly separate.

| Pilot | Upstream access | GRP behavior | Safe first AWS use | Public Global Risk feed |
| --- | --- | --- | --- | --- |
| Southeast Asia PM2.5 | Anonymous AQ Tracker public API | On-demand protected route; optional anonymous GRP compatibility feed with 10-minute cache | Signed-in read and source/expiry/order validation | Technically ready but stays off until redistribution and credit wording are confirmed |
| ThaiWater water level and 24-hour rainfall | Keyed ThaiWater API | Worker-only shadow capture; immutable fetch lineage; protected health/coverage only | Controlled pull and reviewed 6-hour shadow window | Not approved; no public measurement feed exists |

The common rule is: source retrieval readiness is not publication approval. The deployment may test both sources without submitting either one to Global Risk.

### 12.1 PM2.5 pilot

The existing PM2.5 adapter reads AQ Tracker's anonymous endpoint and corrects two compatibility problems for Global Risk: it copies the document-level forecast time into every province row and orders rows so the highest-concern provinces are retained by the platform's default tail. It also adds `valid_until` and an explicitly indicative US EPA category.

The AWS paths are:

```text
Protected signed-in read:
https://servir-risk.kovitad.com/api/v1/air-quality/sea/latest

Anonymous compatibility feed, only after its switch is approved:
https://servir-risk.kovitad.com/api/v1/public/aq/sea/feed.json
```

Set the permanent non-secret base address during deployment so Share data can prepare the correct manifest, but leave the public route off initially:

```dotenv
GRP_PUBLIC_FEED_BASE_URL=https://servir-risk.kovitad.com
AIR_QUALITY_FEED_PUBLIC=false
```

The protected endpoint can be tested immediately after SERVIR sign-in. Validate:

- 351 province records unless the source's documented coverage has changed;
- source `init_date` and `forecast_time` copied consistently to rows;
- `valid_until` is three hours after the selected forecast step;
- missing/zero source values remain no data rather than a fabricated clean-air measurement;
- records are least concern first and highest concern last for the current Global Risk reader;
- Bangkok, Nonthaburi and other checked provinces are not duplicated;
- GRP's 10-minute cache prevents excessive upstream calls;
- a source failure returns a typed unavailable response rather than old invented values;
- source, retrieval and validity times are displayed separately.

The source API is public and keyless, but the current licence/redistribution and required credit wording remain unconfirmed. Therefore the anonymous GRP route remains 404 until that confirmation and explicit Product Owner approval are recorded. After approval, set `AIR_QUALITY_FEED_PUBLIC=true`, restart API, and test the exact public URL from outside AWS. This enables the endpoint only; it does not submit the manifest to Global Risk.

Do not send the feed to Global Risk until its approved-feed retirement/version path is confirmed. The connected deployment auto-approved the temporary tests, and those dead test records still require maintainer retirement.

### 12.2 ThaiWater shadow pilot

The reason for the ThaiWater part of this trial is to exercise the real keyed source while preserving the Stage 0 boundary already approved in ADR-0065 and ADR-0066.

The data path is:

```text
twa-api-public.thaiwater.net
        | outbound HTTPS from the idle worker
        v
GRP shadow capture -> immutable raw-fetch lineage + normalized station states
        |
        v
Protected signed-in health/coverage view at servir-risk.kovitad.com
```

This is **not** the same as publishing a ThaiWater feed to Global Risk. Global Risk's generic-feed reader fetches anonymously, while ThaiWater uses a key. The key must never appear in a public URL, browser response, manifest, log or contributed feed. A future public adapter would require explicit redistribution, retention, freshness and display approval.

### 12.3 ThaiWater pilot scope

The AWS trial may:

- make bounded worker-only requests to the two already approved ThaiWater products;
- store retrieval attempts and raw-response hashes;
- normalize only stations inside the Bangkok–Nonthaburi pilot;
- show protected capture health and station/district coverage without measurements;
- run the metadata-only window analyzer;
- measure cadence, response size, changes, station continuity, observation lag, clock state and provider-quality coverage.

It must not:

- expose the API key or keyed source route;
- create an anonymous measurement API or public map layer;
- publish or contribute ThaiWater measurements to Global Risk;
- calculate district averages;
- treat absent provider quality as good quality;
- change incident confidence, create an operator watch or issue a warning;
- infer a value for a district without a station;
- claim ThaiWater and Floodboard are independent corroboration before sensor origins are mapped.

### 12.4 Configure the ThaiWater key after the empty-stack gate

Migration `20261005_0028` is applied by the normal `alembic upgrade head` deployment step. Do not enable capture until the empty stack is healthy and memory/disk baselines have been recorded.

Create the key file without putting its value in shell history:

```bash
read -rsp 'ThaiWater API key: ' THAIWATER_KEY; echo
printf '%s' "$THAIWATER_KEY" | sudo tee /srv/grp/secrets/thaiwater_api_key >/dev/null
unset THAIWATER_KEY
sudo chown root:root /srv/grp/secrets/thaiwater_api_key
sudo chmod 0600 /srv/grp/secrets/thaiwater_api_key
```

Use `sudoedit /srv/grp/app/.env` to set these non-secret values:

```dotenv
THAIWATER_SHADOW_ENABLED=true
THAIWATER_API_KEY_FILE=/run/grp-secrets/thaiwater_api_key
THAIWATER_API_BASE_URL=https://twa-api-public.thaiwater.net
THAIWATER_POLL_MINUTES=15
```

The host mounts `/srv/grp/secrets` read-only as `/run/source-secrets`. The container entrypoint copies each secret into the non-root container-only tmpfs at `/run/grp-secrets`; the application setting must point to that copied path. The deployment example and its regression test enforce this.

Restart only through Compose after editing:

```bash
sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml up -d --no-build worker api
```

The idle worker should make the first due capture shortly after startup. Do not repeatedly restart it to force requests.

### 12.5 Observe one ThaiWater pull before leaving persistent capture on

Watch safe logs without printing configuration or secret files:

```bash
sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml logs -f --tail 100 worker
```

Require for each of the two products:

- one HTTP-successful attempt or a typed safe failure;
- a plausible national feature count and bounded response size;
- pilot station/state counts;
- no key, authorization header or measurement value in logs;
- API and database health throughout the pull;
- no OOM, container restart or sustained swap growth.

After the first pull, sign in and inspect:

```text
/api/v1/pilot/flood/bangkok/government-observations/status
```

This protected endpoint reports readiness, lineage, timing and coverage, not measurements. Confirm an anonymous request is denied and a permitted ADPC user receives only the approved metadata contract.

If the first capture destabilizes the 1 GB host, set `THAIWATER_SHADOW_ENABLED=false`, restart worker/API and upgrade the host before further capture.

### 12.6 Bounded ThaiWater observation window

If the first pull passes, leave the 15-minute cadence enabled for an initial 6-hour window. That should produce up to about 24 due attempts per product, subject to worker priority and source availability. Extend to 24 hours only after reviewing disk, memory, logs and provider behavior.

At the end, disable persistent capture before analysis if no one is supervising it:

```dotenv
THAIWATER_SHADOW_ENABLED=false
```

Restart worker/API, then run the metadata-only analyzer inside the worker container with explicit UTC bounds:

```bash
sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml exec --no-TTY worker \
  python -m grpcli.thaiwater analyze \
  --pilot bangkok \
  --start '<inclusive-UTC-ISO-time>' \
  --end '<inclusive-UTC-ISO-time>' \
  --output /srv/grp/data/thaiwater-shadow-analysis.json
```

The report must say `publication_approved=false`, `contains_measurement_values=false` and `network_requests_made=false`. Review attempts, distinct raw responses, changes, missingness, corrections, observation lag, future clocks, quality coverage and area coverage.

### 12.7 Combined live-data pilot acceptance

The temporary live-feed pilot passes when:

```text
[ ] Protected PM2.5 route returns the expected bounded, ordered and time-qualified records
[ ] Anonymous PM2.5 route remains off until redistribution/credit approval
[ ] PM2.5 source failure and cache behavior are observed without excessive source calls
[ ] ThaiWater key exists only in the root-owned secret file and container tmpfs copy
[ ] Both approved products have controlled retrieval records
[ ] Repeated unchanged source states are idempotent
[ ] Protected status works and anonymous access fails
[ ] No measurement is exposed publicly
[ ] 6-hour metadata-only report is complete and reviewed
[ ] API/database remain healthy and no container is OOM-killed
[ ] Disk, memory, swap and source response sizes are recorded
[ ] Capture is disabled after the window unless a named person owns continued monitoring
[ ] Neither source creates a Global Risk contribution or public receipt
```

Only a later documented decision may authorize station measurements, a map layer, redistribution or warning use.

## 13. Thailand data is phase two

The complete Thailand bundle is external to Git and images. It is about 2.1 GB at source and materializes additional database and stored files. The current local completed release includes 77 provinces, 928 districts, 7,436 sub-districts, 10,303 shelters and other national layers.

Do not import it merely to prove HTTPS. After the free-tier resource gate passes:

1. take a database and `/srv/grp/data` backup or accept in writing that this trial is rebuildable;
2. securely copy the approved source bundle to `/srv/grp/bootstrap-data` with the documented structure;
3. verify ownership and free disk;
4. start the worker and ensure no other job runs;
5. run the idempotent installer through the reviewed bootstrap/CLI;
6. monitor memory, swap, disk and worker logs continuously;
7. stop and upgrade the host if health fails or swapping becomes sustained;
8. verify bootstrap status and one assessment;
9. never copy source bytes into Git or the container image.

A prebuilt application image avoids compilation; it does not eliminate the runtime RAM and disk required by GIS import and assessment.

## 14. Langfuse phase

Use separate Langfuse Cloud projects/environments for development, evaluation and this AWS trial. Configure telemetry only after the application is healthy.

The first target is metadata-only tracing:

- one trace per user question/evaluation case;
- client-side MCP spans with tool name, duration and typed outcome;
- model generations with version, prompt version, token-use status and cost;
- release SHA, environment, area code, hazard and evidence-reuse state;
- no access token, cookie, raw private tool payload or personal data.

Langfuse failure must never make the GRP answer fail. Use a short export timeout, safe warning and dropped-telemetry counter. The custom app can observe its client-side MCP span; it cannot see Global Risk's internal processing or Claude Desktop usage without cross-system trace propagation.

Do not run contribution or public-publication tools in the deployment pipeline. CI and post-deploy checks use fixtures, sandbox records or bounded read-only calls.

## 15. Normal release and rollback

For each later release:

1. merge the reviewed commit to `main`;
2. require CI and image publication to pass;
3. record the SHA tag and digest;
4. back up database and `/srv/grp/data` before persistent-data changes;
5. run bootstrap in `image` mode with the immutable SHA tag;
6. let the script run `alembic upgrade head` once;
7. run loopback and public health checks;
8. run the bounded read-only acceptance;
9. retain the previous known-good digest.

Roll back code by redeploying the previous tested image digest. If a migration is not backward-compatible, restore the matching coordinated database and file backup. Never improvise an Alembic downgrade on the trial server.

## 16. Public-feed gate

`servir-risk.kovitad.com` is a suitable future permanent source hostname, but deployment does not approve public data redistribution.

Keep `FLOOD_FEED_PUBLIC=false` and `AIR_QUALITY_FEED_PUBLIC=false` initially. Before enabling or contributing either feed:

- confirm licence, redistribution and attribution;
- confirm the route contains only approved public fields;
- set monitoring, cache/freshness semantics and an incident owner;
- test from outside AWS;
- confirm Global Risk has an approved-feed disable/retirement path;
- obtain explicit Product Owner approval for the exact URL and manifest;
- use a production dataset name only once the endpoint is intended to remain available.

Do not repoint or resubmit the three dead temporary Global Risk test feeds without maintainer coordination and a version/retirement decision.

## 17. Trial completion checklist

```text
[ ] AWS cost estimate and budget alerts checked
[ ] Ubuntu 24.04 x86-64 host created
[ ] Stable IPv4 assigned and only SSH/80/443 allowed
[ ] servir-risk.kovitad.com A record resolves correctly
[ ] 3 GB swap enabled and Docker logs bounded
[ ] Reviewed GHCR SHA image available
[ ] Bootstrap image mode completes without source build
[ ] Loopback and public HTTPS health pass
[ ] SERVIR callback-specific client configured
[ ] Correct user/Hub/role sign-in passes
[ ] Public feed switches remain off
[ ] Read-only MCP smoke passes
[ ] Controlled ThaiWater pull and protected status pass
[ ] Six-hour metadata-only ThaiWater window is reviewed
[ ] One small background job passes separately
[ ] No OOM/restarts; memory, swap and disk meet trial thresholds
[ ] Langfuse metadata trace passes when enabled
[ ] Backup and rollback method recorded before data import
[ ] Upgrade trigger and AWS deletion date recorded
```

## 18. Recommended first stopping point

The safest first evening ends after:

- AWS host and DNS exist;
- Caddy serves valid HTTPS at `servir-risk.kovitad.com`;
- empty API/database/worker stack is healthy from the immutable GHCR image;
- public feeds remain off;
- no Thailand source import has started.

Sign-in, the controlled ThaiWater window, MCP acceptance, Langfuse and baseline import should be separate measured steps. This makes failures understandable and keeps the free-tier experiment reversible.
