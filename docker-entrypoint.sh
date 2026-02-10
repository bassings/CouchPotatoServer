#!/bin/bash
set -e

# Fix ownership of mounted volumes
# On Windows/Docker Desktop, bind mounts may not respect PUID/PGID
chown -R couchpotato:couchpotato /config /data 2>/dev/null || true

# If first arg is python3 or starts with -, treat as full command or flags
if [ "$1" = "python3" ]; then
    # Full command override (e.g. from docker-compose command:)
    exec gosu couchpotato "$@"
elif [ "${1#-}" != "$1" ] || [ -z "$1" ]; then
    # No args or flags only — run default
    exec gosu couchpotato python3 CouchPotato.py --console_log --data_dir=/data --config_file=/config/settings.conf "$@"
else
    # Unknown command, just exec it
    exec "$@"
fi
