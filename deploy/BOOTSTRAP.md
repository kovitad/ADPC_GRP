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

Normal releases can pull the prebuilt GitHub Container Registry image and avoid compiling GIS dependencies on the VM:

```bash
sudo /srv/grp/bootstrap/bootstrap-ubuntu.sh --deploy-mode image
```

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

Do not delete `/srv/grp/data`, `/srv/grp/secrets`, or the Compose database volume during troubleshooting.
