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
  --configure-langfuse \
  --admin-email you@adpc.net \
  --hub-admin-email you@adpc.net
```

The script prompts without echo for the OpenAI key, OpenAI model, Langfuse Cloud URL, public key, secret key and environment. Press Enter to accept the displayed defaults for the model (`gpt-5.2`), Langfuse URL (`https://cloud.langfuse.com`) and environment (`development`). The script is safe to rerun. Existing generated secrets and Docker volumes are kept. For later rebuilds, use the same command without the three setup flags.

## Install the Thailand baseline

Copy the approved data bundle into the ignored `.local/data-in` directory, preserving these paths:

```text
.local/data-in/administrative_boundary/district_boundary/
.local/data-in/evacuation_centers/shelters/
.local/data-in/floods/flood_depth_rp100/
```

Then run the idempotent installer. It hashes the source bytes, queues boundaries, shelters and
RP100 in dependency order, waits for the worker, and activates those exact versions:

```bash
./scripts/docker-ubuntu.sh \
  --admin-email you@adpc.net \
  --bootstrap-thailand-data
```

A rerun reuses the import recorded for the same source bytes and importer version. It can safely
requeue an unpublished failed attempt. Check the result under **Data library** in the application,
or run `docker compose --env-file .local/ubuntu-compose.env -f deploy/compose.desktop.yml exec -T api python -m grpcli.bootstrap status`.

If SIG registration has already supplied a client ID, use `--servir-client-id CLIENT_ID` instead. The client is public and its ID is not a password, but it is still stored only in the ignored local configuration.

## Open the application safely

Keep AWS security groups closed for port 8000. In PuTTY, configure `Connection > SSH > Tunnels` with source port `8000`, destination `127.0.0.1:8000`, and type **Local**. Connect, then open `http://127.0.0.1:8000` on your computer. The localhost URL also matches the registered OAuth callback.

```bash
./scripts/docker-ubuntu.sh --status
./scripts/docker-ubuntu.sh --down
```

`--down` stops only the `grp-desktop` Compose project and preserves its data volumes.

## Secret handling

Do not put `OPENAI_API_KEY`, `LANGFUSE_SECRET_KEY` or other raw secrets in `.env`. Although `.env` is Git-ignored, it can still be copied, backed up, or read by other accounts. `--configure-ai` writes the OpenAI key to `.local/docker/secrets/ai_key_adpc`; `--configure-langfuse` writes its secret key to `.local/docker/secrets/langfuse_secret_key`. The launcher never displays either value and applies mode `0600`; `.local/` is also Git-ignored. The model, Langfuse URL, public key and environment are non-secret interpolation values stored in `.local/ubuntu-compose.env`.

Restrict access to the Ubuntu account, protect the SSH key, and never paste secret values into Git, issue trackers, shell history, or chat. To rotate credentials, rerun the corresponding configure option.

This shared-host mode is for testing. It enables development-only features and draft methods. Do not expose it directly to the internet or treat it as the production staging deployment.
