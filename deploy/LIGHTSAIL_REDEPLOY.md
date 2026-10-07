# Lightsail redeployment commands

Use these commands in the AWS Lightsail browser terminal. Copy and run **one code block at a
time**. Every command is one physical line; terminal display wrapping does not create a newline.

Do not delete `/srv/grp`, Docker volumes, the database or secret files.

## 1. Confirm sudo works

```bash
sudo -v
```

Enter the Ubuntu account password if prompted. A successful command normally prints nothing.

## 2. Ensure the bootstrap directory exists

```bash
sudo mkdir -p /srv/grp/bootstrap
```

## 3. Download the current deployment script

```bash
sudo curl -fsSL https://raw.githubusercontent.com/kovitad/ADPC_GRP/main/deploy/bootstrap-ubuntu.sh -o /srv/grp/bootstrap/bootstrap-ubuntu.sh
```

## 4. Deploy the approved pilot image and enable both public pilot feeds

```bash
sudo bash /srv/grp/bootstrap/bootstrap-ubuntu.sh --deploy-mode image --image ghcr.io/kovitad/adpc_grp:sha-d29b465 --domain servir-risk.kovitad.com --small-host --enable-public-pilot-feeds
```

The bootstrap preserves the existing database, `/srv/grp/secrets`, OAuth settings, ThaiWater
capture configuration and Caddy certificate. Wait until it finishes before running verification.

## 5. Verify the deployment

```bash
sudo docker compose --env-file /srv/grp/app/.env -f /srv/grp/app/deploy/compose.yml ps
```

```bash
curl -i https://servir-risk.kovitad.com/api/v1/healthz
```

```bash
curl -i https://servir-risk.kovitad.com/api/v1/public/flood/bangkok/government-observations/feed.json
```

```bash
curl -i https://servir-risk.kovitad.com/api/v1/public/aq/sea/feed.json
```

Expected results are HTTP `200` for health and both public feeds. Confirm the map-header fix too:

```bash
curl -sI https://servir-risk.kovitad.com/flood.html | grep -i '^Referrer-Policy:'
```

The expected value is `strict-origin-when-cross-origin`. If it still says `no-referrer`, Caddy has
not applied the map fix. Never paste API keys, OAuth tokens, cookies or secret-file contents into
the terminal command, documentation or chat.

## Troubleshooting sudo

If `sudo -v` says the account is not allowed to use sudo, stop and use the original Lightsail
Ubuntu administration account. Do not work around it by changing permissions on `/srv/grp/secrets`.

If a command fails, copy only its error message. Do not include `.env` values, keys, tokens or
cookies.
