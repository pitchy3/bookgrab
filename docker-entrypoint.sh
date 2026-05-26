#!/bin/sh
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" -eq 0 ]; then
    if getent group app >/dev/null 2>&1; then
        current_gid="$(getent group app | cut -d: -f3)"
        if [ "$current_gid" != "$PGID" ]; then
            if getent group "$PGID" >/dev/null 2>&1; then
                existing_group="$(getent group "$PGID" | cut -d: -f1)"
                usermod -g "$existing_group" app
            else
                groupmod -g "$PGID" app
            fi
        fi
    elif ! getent group "$PGID" >/dev/null 2>&1; then
        groupadd -g "$PGID" app
    fi

    if getent passwd app >/dev/null 2>&1; then
        current_uid="$(id -u app)"
        if [ "$current_uid" != "$PUID" ]; then
            usermod -u "$PUID" app
        fi
    elif ! getent passwd "$PUID" >/dev/null 2>&1; then
        useradd --uid "$PUID" --gid "$PGID" --create-home --shell /usr/sbin/nologin app
    fi

    chown -R "$PUID:$PGID" /config
    exec su app -s /bin/sh -c "$*"
fi

exec "$@"
