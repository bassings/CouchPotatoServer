#!/bin/sh
# -u as well as -e. This is PID 1 in the shipped image, so an unset variable
# expanding to empty does not fail a script -- it execs a subtly wrong
# command as root and the container comes up looking healthy.
#
# -u cannot simply be added, which is the trap: `$1` is unset on the default
# `docker run` with no arguments, so `set -eu` on the original produced
# `$1: unbound variable` and exit 1 before anything started. Hence `first`
# below. Behaviour is pinned by tests/unit/test_docker_entrypoint.py.
set -eu

# Fix ownership of mounted volumes
# On Windows/Docker Desktop, bind mounts may not respect PUID/PGID
chown -R couchpotato:couchpotato /config /data 2>/dev/null || true

# Resolved once, so the three tests below cannot disagree about it and none
# of them has to repeat the :- default.
first="${1:-}"

# If first arg is python3 or starts with -, treat as full command or flags
# su-exec drops root to the couchpotato user (Alpine's lightweight gosu)
if [ "$first" = "python3" ]; then
    # Full command override (e.g. from docker-compose command:)
    exec su-exec couchpotato "$@"
elif [ "${first#-}" != "$first" ] || [ -z "$first" ]; then
    # No args or flags only — run default
    exec su-exec couchpotato python3 CouchPotato.py --console_log --data_dir=/data --config_file=/config/config.ini "$@"
else
    # Unknown command, just exec it
    exec "$@"
fi
