#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_VERSION="1.0.0"
readonly DEFAULT_REPOSITORY="https://github.com/kovitad/ADPC_GRP.git"
readonly DEFAULT_IMAGE="ghcr.io/kovitad/adpc_grp:main"
readonly DEFAULT_DOMAIN="staging-risk-servir.adpc.net"
readonly BASE_DIR="/srv/grp"
readonly APP_DIR="${BASE_DIR}/app"
readonly DATA_DIR="${BASE_DIR}/data"
readonly SECRETS_DIR="${BASE_DIR}/secrets"
readonly RELEASES_DIR="${BASE_DIR}/releases"
readonly BACKUP_DIR="${BASE_DIR}/backup-staging"

DEPLOY_MODE="source"
REPOSITORY="$DEFAULT_REPOSITORY"
GIT_REF="main"
IMAGE="$DEFAULT_IMAGE"
DOMAIN="$DEFAULT_DOMAIN"
DEPLOY_USER=""
ENABLE_UFW="false"
CHECK_ONLY="false"
SSH_ALLOW_CIDRS=()
APT_UPDATED="false"

log() { printf '[grp-bootstrap] %s\n' "$*"; }
warn() { printf '[grp-bootstrap] WARNING: %s\n' "$*" >&2; }
die() { printf '[grp-bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

on_error() {
    local exit_code=$?
    printf '[grp-bootstrap] ERROR: command failed at line %s (exit %s)\n' "${BASH_LINENO[0]}" "$exit_code" >&2
    exit "$exit_code"
}
trap on_error ERR

usage() {
    cat <<EOF
Usage: sudo ./bootstrap-ubuntu.sh [options]

Idempotently prepares Ubuntu and deploys GRP.

Options:
  --deploy-mode source|image  Build from source on the VM, or pull a GHCR image
  --repo URL                  Git repository (default: $DEFAULT_REPOSITORY)
  --ref REF                   Git branch or tag (default: main)
  --image IMAGE               Image used by image mode (default: $DEFAULT_IMAGE)
  --domain NAME               Public DNS name (default: $DEFAULT_DOMAIN)
  --deploy-user USER          Account that owns the checkout (default: SUDO_USER)
  --enable-ufw                Enable UFW after safe allow rules are installed
  --ssh-allow-cidr CIDR       SSH source network; repeat for multiple networks
  --check-only                Report state without changing the machine
  --help                      Show this help
EOF
}

require_option_value() {
    [ "$#" -ge 2 ] && [ -n "$2" ] || die "Option $1 requires a value"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --deploy-mode) require_option_value "$@"; DEPLOY_MODE="$2"; shift 2 ;;
        --repo) require_option_value "$@"; REPOSITORY="$2"; shift 2 ;;
        --ref) require_option_value "$@"; GIT_REF="$2"; shift 2 ;;
        --image) require_option_value "$@"; IMAGE="$2"; shift 2 ;;
        --domain) require_option_value "$@"; DOMAIN="$2"; shift 2 ;;
        --deploy-user) require_option_value "$@"; DEPLOY_USER="$2"; shift 2 ;;
        --enable-ufw) ENABLE_UFW="true"; shift ;;
        --ssh-allow-cidr)
            require_option_value "$@"
            SSH_ALLOW_CIDRS+=("$2")
            shift 2
            ;;
        --check-only) CHECK_ONLY="true"; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ "$DEPLOY_MODE" =~ ^(source|image)$ ]] || die "--deploy-mode must be source or image"
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "Invalid --domain value"
[[ "$GIT_REF" =~ ^[A-Za-z0-9._/-]+$ ]] && [[ "$GIT_REF" != -* ]] || die "Invalid --ref value"
[[ "$IMAGE" =~ ^[A-Za-z0-9._:/@-]+$ ]] || die "Invalid --image value"
[[ "$REPOSITORY" != -* ]] || die "Invalid --repo value"

if [ -z "$DEPLOY_USER" ]; then
    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
        DEPLOY_USER="$SUDO_USER"
    elif [ "$(id -u)" -ne 0 ]; then
        DEPLOY_USER="$(id -un)"
    fi
fi

show_status() {
    log "Bootstrap version: $SCRIPT_VERSION"
    log "Deployment mode: $DEPLOY_MODE"
    for command_name in git docker caddy; do
        if command -v "$command_name" >/dev/null 2>&1; then
            log "$command_name: installed"
        else
            warn "$command_name: not installed"
        fi
    done
    if command -v docker >/dev/null 2>&1; then
        docker compose version >/dev/null 2>&1 \
            && log "docker compose: installed" \
            || warn "docker compose: not installed"
    fi
    for directory in "$APP_DIR" "$DATA_DIR" "$SECRETS_DIR" "$RELEASES_DIR" "$BACKUP_DIR"; do
        [ -d "$directory" ] && log "$directory: present" || warn "$directory: missing"
    done
    if [ -d "$APP_DIR/.git" ]; then
        log "checkout: $(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || printf unknown)"
    else
        warn "checkout: missing"
    fi
    for secret_name in postgres_password database_url session_secret; do
        [ -s "$SECRETS_DIR/$secret_name" ] \
            && log "secret $secret_name: present" \
            || warn "secret $secret_name: missing"
    done
    if command -v systemctl >/dev/null 2>&1; then
        systemctl is-active --quiet docker 2>/dev/null && log "docker service: active" || warn "docker service: inactive"
        systemctl is-active --quiet caddy 2>/dev/null && log "caddy service: active" || warn "caddy service: inactive"
    fi
    curl --fail --silent --max-time 3 http://127.0.0.1:8000/api/v1/healthz >/dev/null 2>&1 \
        && log "API loopback health: healthy" \
        || warn "API loopback health: unavailable"
}

if [ "$CHECK_ONLY" = "true" ]; then
    show_status
    exit 0
fi

[ "$(id -u)" -eq 0 ] || die "Run this script with sudo"
[ -n "$DEPLOY_USER" ] || die "Use sudo from the deployment account or pass --deploy-user USER"
id "$DEPLOY_USER" >/dev/null 2>&1 || die "Deployment user does not exist: $DEPLOY_USER"
DEPLOY_GROUP="$(id -gn "$DEPLOY_USER")"

[ -r /etc/os-release ] || die "Cannot identify the operating system"
# shellcheck disable=SC1091
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || die "This bootstrap supports Ubuntu only"
case "${VERSION_ID:-}" in
    22.04|24.04) ;;
    *) die "Supported Ubuntu releases are 22.04 and 24.04; found ${VERSION_ID:-unknown}" ;;
esac

apt_update() {
    if [ "$APT_UPDATED" = "false" ]; then
        log "Refreshing APT package metadata"
        apt-get update
        APT_UPDATED="true"
    fi
}

install_packages() {
    local missing=()
    local package
    for package in "$@"; do
        dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' || missing+=("$package")
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        log "Required packages already installed: $*"
        return
    fi
    apt_update
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends "${missing[@]}"
}

install_packages ca-certificates curl git gnupg openssl debian-keyring debian-archive-keyring apt-transport-https

install_docker() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        log "Docker Engine and Compose plugin already installed"
    else
        local conflicts=()
        local package
        for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
            dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' && conflicts+=("$package")
        done
        [ "${#conflicts[@]}" -eq 0 ] || die "Conflicting container packages detected: ${conflicts[*]}. Review and remove them before installing Docker CE."

        log "Installing Docker Engine from Docker's official Ubuntu repository"
        install -d -m 0755 /etc/apt/keyrings
        curl --fail --silent --show-error --location https://download.docker.com/linux/ubuntu/gpg \
            --output /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
        APT_UPDATED="false"
        install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
    systemctl enable --now docker
    if ! id -nG "$DEPLOY_USER" | tr ' ' '\n' | grep -qx docker; then
        usermod --append --groups docker "$DEPLOY_USER"
        warn "$DEPLOY_USER was added to the docker group; reconnect before running Docker without sudo"
    fi
}

install_caddy() {
    if command -v caddy >/dev/null 2>&1; then
        log "Caddy already installed"
    else
        log "Installing Caddy from its official Debian repository"
        curl --fail --silent --show-error --location https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
            | gpg --dearmor --yes --output /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl --fail --silent --show-error --location https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
            --output /etc/apt/sources.list.d/caddy-stable.list
        chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
        APT_UPDATED="false"
        install_packages caddy
    fi
}

install_docker
install_caddy

log "Creating GRP filesystem layout"
install -d -m 0755 "$BASE_DIR"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0755 "$APP_DIR" "$RELEASES_DIR"
install -d -o 10001 -g 10001 -m 0750 "$DATA_DIR"
install -d -o root -g root -m 0700 "$SECRETS_DIR" "$BACKUP_DIR"

normalise_repository() {
    printf '%s' "$1" | sed -E 's#/$##; s#\.git$##'
}

sync_checkout() {
    if [ -d "$APP_DIR/.git" ]; then
        local configured_repository
        configured_repository="$(runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" remote get-url origin)"
        [ "$(normalise_repository "$configured_repository")" = "$(normalise_repository "$REPOSITORY")" ] \
            || die "Existing checkout origin is $configured_repository, expected $REPOSITORY"
        [ -z "$(runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" status --porcelain)" ] \
            || die "Existing checkout has local changes; preserve or commit them before rerunning"
        log "Fetching $GIT_REF and applying a fast-forward update"
        runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" fetch --prune origin "$GIT_REF"
        if runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" show-ref --verify --quiet "refs/remotes/origin/$GIT_REF"; then
            if runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" show-ref --verify --quiet "refs/heads/$GIT_REF"; then
                runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" switch "$GIT_REF"
            else
                runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" switch --track -c "$GIT_REF" "origin/$GIT_REF"
            fi
            runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" merge --ff-only "origin/$GIT_REF"
        else
            runuser --user "$DEPLOY_USER" -- git -C "$APP_DIR" switch --detach FETCH_HEAD
        fi
    else
        [ -z "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ] \
            || die "$APP_DIR exists and is not an empty Git checkout"
        log "Cloning $REPOSITORY at $GIT_REF"
        runuser --user "$DEPLOY_USER" -- git clone --branch "$GIT_REF" --single-branch "$REPOSITORY" "$APP_DIR"
    fi
}

sync_checkout

if [ ! -f "$APP_DIR/.env" ]; then
    log "Creating non-secret configuration from .env.example"
    install -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0640 "$APP_DIR/.env.example" "$APP_DIR/.env"
else
    log "Preserving existing .env"
fi

set_env_value() {
    local key="$1"
    local value="$2"
    local escaped_value="${value//\\/\\\\}"
    escaped_value="${escaped_value//&/\\&}"
    escaped_value="${escaped_value//|/\\|}"
    if grep -q "^${key}=" "$APP_DIR/.env"; then
        sed -i "s|^${key}=.*|${key}=${escaped_value}|" "$APP_DIR/.env"
    else
        printf '%s=%s\n' "$key" "$value" >> "$APP_DIR/.env"
    fi
}

set_env_value GRP_PUBLIC_BASE_URL "https://$DOMAIN"
set_env_value SERVIR_AUTH_REDIRECT_URI "https://$DOMAIN/api/v1/auth/callback"
if [ "$DEPLOY_MODE" = "image" ]; then
    set_env_value GRP_IMAGE "$IMAGE"
else
    set_env_value GRP_IMAGE "grp-api:local"
fi
chown "$DEPLOY_USER:$DEPLOY_GROUP" "$APP_DIR/.env"
chmod 0640 "$APP_DIR/.env"

write_secret_if_missing() {
    local name="$1"
    local value="$2"
    local path="$SECRETS_DIR/$name"
    if [ -s "$path" ]; then
        log "Preserving existing secret: $name"
    else
        log "Generating secret: $name"
        (umask 077; printf '%s\n' "$value" > "$path")
    fi
    chown root:root "$path"
    chmod 0600 "$path"
}

if [ -s "$SECRETS_DIR/database_url" ] && [ ! -s "$SECRETS_DIR/postgres_password" ]; then
    die "database_url exists but postgres_password is missing; restore the matching password before rerunning"
fi
if [ -s "$SECRETS_DIR/postgres_password" ]; then
    POSTGRES_PASSWORD="$(tr -d '\r\n' < "$SECRETS_DIR/postgres_password")"
else
    POSTGRES_PASSWORD="$(openssl rand -hex 32)"
fi
write_secret_if_missing postgres_password "$POSTGRES_PASSWORD"
write_secret_if_missing database_url "postgresql+psycopg://grp:${POSTGRES_PASSWORD}@db:5432/grp"
write_secret_if_missing session_secret "$(openssl rand -hex 48)"
unset POSTGRES_PASSWORD

configure_caddy() {
    local candidate
    candidate="$(mktemp)"
    sed "1s|^[^ ]* {|$DOMAIN {|" "$APP_DIR/deploy/Caddyfile" > "$candidate"
    caddy validate --config "$candidate" --adapter caddyfile
    if [ ! -f /etc/caddy/Caddyfile ] || ! cmp --silent "$candidate" /etc/caddy/Caddyfile; then
        if [ -f /etc/caddy/Caddyfile ]; then
            cp --preserve=mode,ownership,timestamps /etc/caddy/Caddyfile \
                "$RELEASES_DIR/Caddyfile.$(date -u +%Y%m%dT%H%M%SZ).bak"
        fi
        install -o root -g root -m 0644 "$candidate" /etc/caddy/Caddyfile
        log "Installed Caddy configuration for $DOMAIN"
        systemctl enable --now caddy
        systemctl reload caddy
    else
        log "Caddy configuration is already current"
        systemctl enable --now caddy
    fi
    rm -f "$candidate"
}

configure_caddy

if [ "$ENABLE_UFW" = "true" ]; then
    [ "${#SSH_ALLOW_CIDRS[@]}" -gt 0 ] \
        || die "--enable-ufw requires at least one --ssh-allow-cidr to avoid SSH lockout"
    install_packages ufw
    SSH_PORT="$(/usr/sbin/sshd -T 2>/dev/null | awk '$1 == "port" {print $2; exit}')"
    [ -n "$SSH_PORT" ] || die "Could not detect the SSH daemon port"
    for cidr in "${SSH_ALLOW_CIDRS[@]}"; do
        ufw allow from "$cidr" to any port "$SSH_PORT" proto tcp comment 'GRP SSH'
    done
    ufw allow 80/tcp comment 'GRP HTTP'
    ufw allow 443/tcp comment 'GRP HTTPS'
    ufw --force enable
    log "UFW enabled; SSH port $SSH_PORT is restricted to the supplied source network(s)"
else
    warn "UFW was not changed. Re-run with --enable-ufw and approved --ssh-allow-cidr values after validation."
fi

COMPOSE=(docker compose --env-file "$APP_DIR/.env" -f "$APP_DIR/deploy/compose.yml")
"${COMPOSE[@]}" config --quiet

if [ "$DEPLOY_MODE" = "source" ]; then
    log "Building the GRP image from the checked-out source"
    "${COMPOSE[@]}" build --pull api worker
else
    log "Pulling prebuilt image $IMAGE"
    docker pull "$IMAGE" || die "Image pull failed. For a private package, run 'docker login ghcr.io' with a read:packages token and retry."
fi

log "Starting PostGIS"
"${COMPOSE[@]}" up --detach db
for attempt in $(seq 1 30); do
    if "${COMPOSE[@]}" exec --no-TTY db pg_isready -U grp -d grp >/dev/null 2>&1; then
        break
    fi
    [ "$attempt" -lt 30 ] || die "PostGIS did not become ready within 150 seconds"
    sleep 5
done

log "Applying forward database migrations"
"${COMPOSE[@]}" run --rm --no-deps api python -m alembic upgrade head

log "Starting API and worker"
"${COMPOSE[@]}" up --detach --no-build --remove-orphans api worker

for attempt in $(seq 1 30); do
    if curl --fail --silent --max-time 5 http://127.0.0.1:8000/api/v1/healthz >/dev/null; then
        break
    fi
    [ "$attempt" -lt 30 ] || die "GRP API did not become healthy within 150 seconds"
    sleep 5
done

RELEASE_TIME="$(date -u +%Y%m%dT%H%M%SZ)"
RELEASE_FILE="$RELEASES_DIR/release-$RELEASE_TIME.txt"
{
    printf 'deployed_at=%s\n' "$RELEASE_TIME"
    printf 'mode=%s\n' "$DEPLOY_MODE"
    printf 'git_commit=%s\n' "$(git -C "$APP_DIR" rev-parse HEAD)"
    printf 'image=%s\n' "$(grep '^GRP_IMAGE=' "$APP_DIR/.env" | cut -d= -f2-)"
} > "$RELEASE_FILE"
chmod 0644 "$RELEASE_FILE"

log "Deployment complete: https://$DOMAIN"
log "Release manifest: $RELEASE_FILE"
show_status
