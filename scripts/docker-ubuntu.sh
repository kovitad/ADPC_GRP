#!/usr/bin/env bash
set -Eeuo pipefail

IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPOSITORY_ROOT/deploy/compose.desktop.yml"
LOCAL_ROOT="$REPOSITORY_ROOT/.local"
SECRET_ROOT="$LOCAL_ROOT/docker/secrets"
CONFIG_FILE="$LOCAL_ROOT/ubuntu-compose.env"
CLIENT_ID_FILE="$LOCAL_ROOT/servir_auth_client_id"

declare -a ADMIN_EMAILS=()
declare -a HUB_ADMIN_EMAILS=()
declare -a DOCKER_COMMAND=()
ACTION="up"
CONFIGURE_AI=false
REGISTER_SIG_CLIENT=false
SERVIR_CLIENT_ID=""

usage() {
    cat <<'EOF'
Build and run the local GRP demo stack on an Ubuntu host.

Usage:
  ./scripts/docker-ubuntu.sh [options]

Options:
  --admin-email EMAIL       Make an existing SERVIR email a Platform Admin.
                            May be supplied more than once.
  --hub-admin-email EMAIL   Make an email an ADPC Hub Admin. Requires at least
                            one --admin-email. May be supplied more than once.
  --configure-ai            Prompt without echo for the OpenAI API key and save
                            it in the ignored, mode-0600 local secret directory.
  --register-sig-client     Register a localhost public PKCE client with SIG.
  --servir-client-id ID     Use an already registered non-secret SIG client ID.
  --status                  Show container and health status without rebuilding.
  --down                    Stop this stack. Docker volumes and data are kept.
  -h, --help                Show this help.

The API binds only to 127.0.0.1:8000. Ports 80 and 443 are not used.
EOF
}

log() {
    printf '[GRP] %s\n' "$*"
}

warn() {
    printf '[GRP] WARNING: %s\n' "$*" >&2
}

die() {
    printf '[GRP] ERROR: %s\n' "$*" >&2
    exit 1
}

require_value() {
    local option="$1"
    local value="${2:-}"
    [ -n "$value" ] || die "$option requires a value"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --admin-email)
            require_value "$1" "${2:-}"
            ADMIN_EMAILS+=("$2")
            shift 2
            ;;
        --hub-admin-email)
            require_value "$1" "${2:-}"
            HUB_ADMIN_EMAILS+=("$2")
            shift 2
            ;;
        --configure-ai)
            CONFIGURE_AI=true
            shift
            ;;
        --register-sig-client)
            REGISTER_SIG_CLIENT=true
            shift
            ;;
        --servir-client-id)
            require_value "$1" "${2:-}"
            SERVIR_CLIENT_ID="$2"
            shift 2
            ;;
        --status)
            ACTION="status"
            shift
            ;;
        --down)
            ACTION="down"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1 (use --help)"
            ;;
    esac
done

[ "$(uname -s)" = "Linux" ] || die "This launcher is for Linux/Ubuntu. Use scripts/docker-desktop.ps1 on Windows."
command -v docker >/dev/null 2>&1 || die "Docker Engine and the Docker Compose plugin are required."

if docker info >/dev/null 2>&1; then
    DOCKER_COMMAND=(docker)
elif command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    DOCKER_COMMAND=(sudo docker)
else
    die "Docker is not running or this account cannot use it. Start Docker or add the account to the docker group."
fi

"${DOCKER_COMMAND[@]}" compose version >/dev/null 2>&1 \
    || die "The Docker Compose v2 plugin is required ('docker compose')."

mkdir -p "$SECRET_ROOT" "$LOCAL_ROOT/data-in"
chmod 700 "$LOCAL_ROOT" "$SECRET_ROOT"

if [ ! -f "$CONFIG_FILE" ]; then
    umask 077
    cat >"$CONFIG_FILE" <<'EOF'
# Non-secret interpolation values for deploy/compose.desktop.yml.
SERVIR_AUTH_CLIENT_ID=
AI_MODEL=gpt-5.2
LANGFUSE_HOST=
LANGFUSE_PUBLIC_KEY=
EOF
fi
chmod 600 "$CONFIG_FILE"

compose() {
    "${DOCKER_COMMAND[@]}" compose \
        --env-file "$CONFIG_FILE" \
        -f "$COMPOSE_FILE" \
        "$@"
}

set_config_value() {
    local key="$1"
    local value="$2"
    local temporary

    [[ "$key" =~ ^[A-Z0-9_]+$ ]] || die "Invalid configuration key: $key"
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || die "Configuration values must fit on one line"
    temporary="$(mktemp "$LOCAL_ROOT/ubuntu-compose.env.XXXXXX")"
    awk -v key="$key" -v value="$value" '
        BEGIN { replaced = 0 }
        index($0, key "=") == 1 { print key "=" value; replaced = 1; next }
        { print }
        END { if (!replaced) print key "=" value }
    ' "$CONFIG_FILE" >"$temporary"
    chmod 600 "$temporary"
    mv -f "$temporary" "$CONFIG_FILE"
}

random_hex() {
    local byte_count="$1"
    od -An -N "$byte_count" -tx1 /dev/urandom | tr -d ' \n'
}

write_secret_once() {
    local name="$1"
    local value="$2"
    local path="$SECRET_ROOT/$name"

    if [ ! -s "$path" ]; then
        umask 077
        printf '%s\n' "$value" >"$path"
    fi
    chmod 600 "$path"
}

write_secret_once "postgres_password" "$(random_hex 32)"
POSTGRES_PASSWORD="$(tr -d '\r\n' <"$SECRET_ROOT/postgres_password")"
write_secret_once "database_url" "postgresql+psycopg://grp:${POSTGRES_PASSWORD}@db:5432/grp"
write_secret_once "session_secret" "$(random_hex 48)"
unset POSTGRES_PASSWORD

if [ -n "$SERVIR_CLIENT_ID" ]; then
    [[ "$SERVIR_CLIENT_ID" =~ ^[A-Za-z0-9._~-]+$ ]] \
        || die "The SIG client ID contains unexpected characters"
    set_config_value "SERVIR_AUTH_CLIENT_ID" "$SERVIR_CLIENT_ID"
    umask 077
    printf '%s\n' "$SERVIR_CLIENT_ID" >"$CLIENT_ID_FILE"
    chmod 600 "$CLIENT_ID_FILE"
elif [ -s "$CLIENT_ID_FILE" ]; then
    SERVIR_CLIENT_ID="$(tr -d '\r\n' <"$CLIENT_ID_FILE")"
    set_config_value "SERVIR_AUTH_CLIENT_ID" "$SERVIR_CLIENT_ID"
fi

if $CONFIGURE_AI; then
    [ -t 0 ] || die "--configure-ai needs an interactive terminal so the key can be entered securely"
    read -r -s -p "OpenAI API key (input hidden): " AI_KEY
    printf '\n'
    [ -n "$AI_KEY" ] || die "No API key was entered"
    umask 077
    printf '%s\n' "$AI_KEY" >"$SECRET_ROOT/ai_key_adpc"
    chmod 600 "$SECRET_ROOT/ai_key_adpc"
    unset AI_KEY
    log "Saved the AI key in the ignored local secret directory (value not displayed)."
elif [ ! -s "$SECRET_ROOT/ai_key_adpc" ]; then
    warn "No AI key is configured. The application will run, but AI calls will report unavailable."
fi

if [ -f "$REPOSITORY_ROOT/.env" ]; then
    warn "A repository .env exists. This launcher does not read it; keep raw API keys in .local/docker/secrets instead."
fi

case "$ACTION" in
    status)
        compose ps
        if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 5 http://127.0.0.1:8000/api/v1/healthz >/dev/null; then
            log "Health check passed: http://127.0.0.1:8000/api/v1/healthz"
        else
            warn "The API health check is not responding on 127.0.0.1:8000."
        fi
        exit 0
        ;;
    down)
        compose down
        log "GRP stopped. Its Docker volumes were kept."
        exit 0
        ;;
esac

if [ "${#HUB_ADMIN_EMAILS[@]}" -gt 0 ] && [ "${#ADMIN_EMAILS[@]}" -eq 0 ]; then
    die "--hub-admin-email requires at least one --admin-email to act as Platform Admin"
fi

RUNNING_API="$(compose ps -q api 2>/dev/null || true)"
if [ -z "$RUNNING_API" ] && command -v ss >/dev/null 2>&1 \
    && ss -H -ltn | awk '{print $4}' | grep -Eq '(^|:)8000$'; then
    die "Port 8000 is already in use. Stop that process or change its port before starting GRP."
fi

if $REGISTER_SIG_CLIENT; then
    if [ -s "$CLIENT_ID_FILE" ]; then
        log "Reusing the existing SIG public client ID."
    else
        log "Building the API image before registering the localhost SIG client..."
        compose build api
        "${DOCKER_COMMAND[@]}" run --rm \
            --user "$(id -u):$(id -g)" \
            --volume "$LOCAL_ROOT:/local" \
            grp-api:desktop \
            python -m grpcli.oauth register-client \
            --redirect-uri "http://127.0.0.1:8000/api/v1/auth/callback" \
            --client-name "ADPC GRP Ubuntu local" \
            --output-file /local/servir_auth_client_id
    fi
    [ -s "$CLIENT_ID_FILE" ] || die "SIG registration did not create $CLIENT_ID_FILE"
    SERVIR_CLIENT_ID="$(tr -d '\r\n' <"$CLIENT_ID_FILE")"
    set_config_value "SERVIR_AUTH_CLIENT_ID" "$SERVIR_CLIENT_ID"
fi

if ! grep -Eq '^SERVIR_AUTH_CLIENT_ID=.+$' "$CONFIG_FILE"; then
    warn "No SIG client ID is configured. Health will work, but SERVIR sign-in will be unavailable."
fi

log "Building and starting GRP on 127.0.0.1:8000..."
compose up -d --build --wait
compose exec -T api python -m grpcli.seed synthetic-rp100

for email in "${ADMIN_EMAILS[@]}"; do
    compose exec -T api python -m grpcli.admin bootstrap-platform-admin --email "$email"
    compose exec -T api python -m grpcli.admin ensure-hub \
        --actor-email "$email" --code adpc --name "ADPC Hub"
done

for email in "${HUB_ADMIN_EMAILS[@]}"; do
    compose exec -T api python -m grpcli.admin assign-member \
        --actor-email "${ADMIN_EMAILS[0]}" --email "$email" \
        --hub-code adpc --role admin
done

if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 10 http://127.0.0.1:8000/api/v1/healthz >/dev/null \
        || die "Containers started, but the API health check failed. Run this script with --status and inspect the logs."
fi

cat <<'EOF'

GRP is running only on the Ubuntu host's loopback address: 127.0.0.1:8000.
It did not use or change ports 80/443, Caddy, or your other Docker application.

From PuTTY, add this SSH tunnel before connecting:
  Connection > SSH > Tunnels
  Source port: 8000
  Destination: 127.0.0.1:8000
  Select Local, click Add, then connect.

Then open on your own computer:
  http://127.0.0.1:8000

Useful commands:
  ./scripts/docker-ubuntu.sh --status
  docker compose --env-file .local/ubuntu-compose.env -f deploy/compose.desktop.yml logs -f api worker
  ./scripts/docker-ubuntu.sh --down
EOF
