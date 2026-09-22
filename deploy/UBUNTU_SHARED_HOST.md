# Ubuntu shared-host demo

Use this runbook when GRP shares an Ubuntu machine with another application that already owns ports 80 and 443. It starts the same demo-oriented stack used by Docker Desktop, binds GRP only to `127.0.0.1:8000`, and does not install or change Caddy. The production staging bootstrap remains the correct choice for a dedicated VM.

## Prerequisites

Install Docker Engine with the Compose v2 plugin, clone the repository, and enter it. The launcher uses `sudo docker` if the current account is not in the Docker group.

```bash
git clone https://github.com/kovitad/ADPC_GRP.git
cd ADPC_GRP
chmod +x scripts/docker-ubuntu.sh
```

## First start

This command builds the images, registers a localhost SERVIR/SIG OAuth client, securely prompts for the OpenAI key, starts PostGIS/API/worker, runs migrations, seeds the synthetic demo, and provisions the specified administrator:

```bash
./scripts/docker-ubuntu.sh \
  --register-sig-client \
  --configure-ai \
  --admin-email you@adpc.net \
  --hub-admin-email you@adpc.net
```

The script is safe to rerun. Existing generated secrets and Docker volumes are kept. For later rebuilds, use the same command without `--register-sig-client` and `--configure-ai`.

If SIG registration has already supplied a client ID, use `--servir-client-id CLIENT_ID` instead. The client is public and its ID is not a password, but it is still stored only in the ignored local configuration.

## Open the application safely

Keep AWS security groups closed for port 8000. In PuTTY, configure `Connection > SSH > Tunnels` with source port `8000`, destination `127.0.0.1:8000`, and type **Local**. Connect, then open `http://127.0.0.1:8000` on your computer. The localhost URL also matches the registered OAuth callback.

```bash
./scripts/docker-ubuntu.sh --status
./scripts/docker-ubuntu.sh --down
```

`--down` stops only the `grp-desktop` Compose project and preserves its data volumes.

## Secret handling

Do not put `OPENAI_API_KEY` or other raw secrets in `.env`. Although `.env` is Git-ignored, it can still be copied, backed up, or read by other accounts. `--configure-ai` writes the key without displaying it to `.local/docker/secrets/ai_key_adpc`, and the launcher applies mode `0600`; `.local/` is also Git-ignored. Non-secret interpolation values are stored in `.local/ubuntu-compose.env`.

Restrict access to the Ubuntu account, protect the SSH key, and never paste secret values into Git, issue trackers, shell history, or chat. To rotate the AI key, rerun with `--configure-ai`.

This shared-host mode is for testing. It enables development-only features and draft methods. Do not expose it directly to the internet or treat it as the production staging deployment.
