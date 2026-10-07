#!/bin/sh
set -eu

# Compose bind mounts retain host ownership. Copy root-owned 0600 secrets into a
# container-only tmpfs, then permanently drop privileges before starting GRP.
if [ "$(id -u)" -eq 0 ]; then
    # Keep the directory root-owned while populating it. Dedicated staging drops
    # CAP_DAC_OVERRIDE, so root cannot write through a mode-0700 directory after ownership has
    # already moved to UID 10001. Transfer each file last, then transfer the directory last.
    install -d -o 0 -g 0 -m 0700 /run/grp-secrets

    if [ -d /run/source-secrets ]; then
        for source in /run/source-secrets/*; do
            [ -f "$source" ] || continue
            name=${source##*/}
            install -o 0 -g 0 -m 0400 "$source" "/run/grp-secrets/$name"
            chown 10001:10001 "/run/grp-secrets/$name"
        done
    fi
    chown 10001:10001 /run/grp-secrets

    # Storage volumes are created root-owned. The app must be able to add new folders
    # (district previews, results); existing files keep their owner and stay readable.
    if [ -n "${STORAGE_ROOT:-}" ] && [ -d "$STORAGE_ROOT" ]; then
        chown 10001:10001 "$STORAGE_ROOT"
    fi

    exec gosu 10001:10001 "$@"
fi

exec "$@"
