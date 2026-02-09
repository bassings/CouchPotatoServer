#!/bin/bash
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Update user/group IDs if changed
if [ "$(id -u couchpotato)" != "${PUID}" ]; then
    usermod -u ${PUID} couchpotato
fi
if [ "$(id -g couchpotato)" != "${PGID}" ]; then
    groupmod -g ${PGID} couchpotato
fi

# Set timezone if provided
if [ -n "${TZ}" ]; then
    ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime
    echo ${TZ} > /etc/timezone
fi

# Ensure directories exist with correct ownership
mkdir -p ${CONFIG_DIR} ${DATA_DIR}
chown -R couchpotato:couchpotato ${CONFIG_DIR} ${DATA_DIR}

echo "Starting CouchPotato (uid=$(id -u couchpotato), gid=$(id -g couchpotato))..."

exec gosu couchpotato "$@" --data_dir=${DATA_DIR} --config_file=${CONFIG_DIR}/settings.conf
