# Ubuntu staging bootstrap runbook

## Purpose and impact

Use this procedure on the dedicated Ubuntu 24.04 staging VM. It installs Docker Engine, the Compose plugin, and Caddy from their official repositories; creates the `/srv/grp` layout; checks out the application; initializes required secrets; and deploys the stack. Run as an account with `sudo` access.

The script is idempotent: reruns skip installed software, preserve secrets and `.env`, refuse to overwrite a dirty checkout, and update code only by fast-forward. It does not enable UFW unless explicitly requested.

## First run

In a PuTTY session, create a stable location and download the script:

```bash
sudo install -d -m 0755 /srv/grp/bootstrap
sudo curl -fsSL \
  https://raw.githubusercontent.com/kovitad/ADPC_GRP/main/deploy/bootstrap-ubuntu.sh \
  -o /srv/grp/bootstrap/bootstrap-ubuntu.sh
sudo chmod 0755 /srv/grp/bootstrap/bootstrap-ubuntu.sh
less /srv/grp/bootstrap/bootstrap-ubuntu.sh
```

For the initial deployment, source mode is the reliable choice:

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh --deploy-mode source
```

To install the Thailand baseline during the same deployment, prepare its protected host directory
and copy the approved external bundle first:

```bash
sudo install -d -o "$USER" -g 10001 -m 2750 /srv/grp/bootstrap-data
```

Preserve the following folder structure. `/srv/grp/bootstrap-data` is outside Git and the container
image and is mounted read-only into API/worker:

```text
/srv/grp/bootstrap-data/administrative_boundary/district_boundary/
/srv/grp/bootstrap-data/evacuation_centers/shelters/
/srv/grp/bootstrap-data/floods/flood_depth_rp100/
```

The deployment account owns the source directory, while group `10001` gives the non-root worker
read access. Do not copy secrets into it. Then deploy, provision the Admin/Hub and run the
idempotent installer:

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh \
  --deploy-mode source \
  --admin-email you@adpc.net \
  --bootstrap-thailand-data
```

The worker uses `/srv/grp/tmp` for bounded temporary GIS products so large raster conversion does
not consume a small in-memory `/tmp`. Both the data import and Admin provisioning are safe to rerun.

For a resource-constrained pilot, `--bootstrap-thailand-assessment-core` accepts a reduced bundle
containing the administrative hierarchy (village points may be absent), DDPM shelters and exactly
six RP100 GeoTIFFs. It activates the approved assessment method without requiring the display-only
vulnerability rasters or optional volunteer, warning-resource and village context. Do not combine
it with `--bootstrap-thailand-data`. Data Library reports **Assessment core ready** and continues to
show every omitted optional category as unavailable.

Normal releases can pull the prebuilt GitHub Container Registry image and avoid compiling GIS dependencies on the VM:

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh --deploy-mode image
```

For the temporary 1 GB Lightsail trial, use an Ubuntu 24.04 x86-64 instance, point DNS at its
static IPv4 address, allow inbound TCP 80/443, and deploy one immutable image. The `--small-host`
option idempotently adds 3 GB swap and bounded Docker logs; it does not make this a production-size
host. The callback-specific SERVIR client ID is non-secret. `--enable-thaiwater-shadow` is an
explicit external-call action: it prompts for the key without putting it in the command or shell
history, stores it root-owned under `/srv/grp/secrets`, and enables the worker-only shadow capture.
Omit that option on the first empty-stack run if resource behavior has not been measured.

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh \
  --deploy-mode image \
  --image ghcr.io/kovitad/adpc_grp:sha-<approved-short-sha> \
  --domain servir-risk.kovitad.com \
  --small-host \
  --servir-client-id '<callback-specific-public-client-id>' \
  --admin-email '<approved-admin-email>'
```

Rerun the same command with `--enable-thaiwater-shadow` only after the empty stack is healthy. It
preserves the existing key on later reruns. PM2.5 needs no source key: its protected route works for
a signed-in member. The bootstrap records `GRP_PUBLIC_FEED_BASE_URL`, but anonymous feeds stay 404
because `.env.example` leaves every publication switch false. After provider approval, the explicit
`--enable-public-pilot-feeds` option enables only the ThaiWater and PM2.5 anonymous pilot routes;
it does not submit a Global Risk contribution. The separate `--enable-public-flood-feed` option
enables regular Floodboard pulls and the anonymous district route. That route returns 503 until a
successful timestamped roads snapshot exists, then 200. The Product Owner may explicitly add
`--enable-camera-relay` for the temporary pilot: signed-in members then receive supported BMA
Traffic and municipal snapshot pictures through the bounded protected GRP relay. The API may call
the provider over HTTP, but the browser receives the picture from GRP over same-origin HTTPS.
Pictures are rate-limited, held only briefly in memory and never stored. Omit the option outside
the approved pilot. The separate `--enable-global-risk-contributions` option enables the protected
Share Data MCP routes for Hub planning roles without enabling AI or Planning chat. Because MCP
tokens are held only in memory, every user must sign out and sign in again after that switch is
deployed. A valid submission may be auto-approved globally; enabling the route is not permission
to skip its preview and confirmation gate. Verify the feeds at:

- `/api/v1/public/flood/bangkok/government-observations/feed.json`
- `/api/v1/public/aq/sea/feed.json`
- `/api/v1/public/flood/bangkok/feed.json`

The platform health endpoint works before identity-provider setup, but login remains unavailable. Register a callback-specific SIG public PKCE client and put its non-secret ID in `SERVIR_AUTH_CLIENT_ID` in `/srv/grp/app/.env`. GRP discovers the issuer from `SIG_MCP_BASE_URL`; `SERVIR_AUTH_ISSUER` may pin the expected result. A public client has no client secret. Follow [`../docs/access-management.md`](../docs/access-management.md); a normal SIG user account is not an application credential.

Prepare future LLM configuration without enabling it. Keep `AI_FEATURE_ENABLED=false`, set provider/model/base URL as non-secret values when approved, and place the token only in `/srv/grp/secrets/ai_key_adpc` with root ownership and mode `0600`.

The `main` image is published by `.github/workflows/container.yml`. Make the package public in its GitHub package settings, or authenticate once if it remains private. Enter a token with `read:packages` without placing it in shell history:

```bash
read -rsp "GHCR token: " GHCR_TOKEN; echo
printf '%s' "$GHCR_TOKEN" | sudo docker login ghcr.io -u kovitad --password-stdin
unset GHCR_TOKEN
```

Never paste a token into this repository, `.env`, the bootstrap command, or chat.

## Firewall option

Confirm the approved administrator source network before changing a remote firewall. The script detects the active SSH daemon port and installs its allow rule before enabling UFW:

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh \
  --deploy-mode image \
  --enable-ufw \
  --ssh-allow-cidr 203.0.113.10/32
```

Replace the documentation address with the approved ADPC/VPN CIDR. The application rules allow only TCP 80 and 443. Docker publishes the API to loopback and does not publish PostgreSQL.

## Verification

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh --check-only
sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml ps
curl --fail http://127.0.0.1:8000/api/v1/healthz
sudo docker compose --env-file /srv/grp/app/.env \
  -f /srv/grp/app/deploy/compose.yml exec --no-TTY --user 10001:10001 api \
  python -m grpcli.bootstrap status
sudo journalctl -u caddy --since "15 minutes ago" --no-pager
```

Then verify `https://staging-risk-servir.adpc.net/api/v1/healthz` from an approved client. A healthy response is `{"status":"ok"}`.

After OIDC configuration, open the staging root and complete SERVIR sign-in. Bootstrap the first Platform Admin and ADPC Hub before testing an ordinary Hub Expert account, using the commands in [`../docs/access-management.md`](../docs/access-management.md).

## Recovery and troubleshooting

- Image pull denied: make the GHCR package public or repeat `docker login` with a valid `read:packages` token.
- Dirty checkout: inspect `sudo -u <user> git -C /srv/grp/app status`; preserve intentional changes before rerunning.
- TLS failure: confirm public DNS reaches the VM and TCP 80/443 are allowed, then inspect the Caddy journal.
- Service failure: run `sudo docker compose --env-file /srv/grp/app/.env -f /srv/grp/app/deploy/compose.yml logs --tail 200`.
- Database recovery: stop API and worker, restore the coordinated database and `/srv/grp/data` backup, deploy the matching code/image, run the migration, and recheck health.

Do not delete `/srv/grp/data`, `/srv/grp/bootstrap-data`, `/srv/grp/secrets`, or the Compose database volume during troubleshooting.
