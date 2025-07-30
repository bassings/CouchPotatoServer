#!/bin/bash

# CouchPotato Docker Entrypoint Script

set -e

# Handle user/group ID mapping for Docker
if [ ! -z "${PUID}" ] && [ ! -z "${PGID}" ]; then
    echo "Setting up user couchpotato with PUID=${PUID} and PGID=${PGID}"
    
    # Change user and group IDs
    usermod -u ${PUID} couchpotato
    groupmod -g ${PGID} couchpotato
    
    # Fix ownership of directories
    chown -R couchpotato:couchpotato ${CONFIG_DIR} ${DATA_DIR} ${DOWNLOADS_DIR} ${MOVIES_DIR}
fi

# Set timezone if provided
if [ ! -z "${TZ}" ]; then
    echo "Setting timezone to ${TZ}"
    ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime
    echo ${TZ} > /etc/timezone
fi

# Create default directories if they don't exist
mkdir -p ${CONFIG_DIR} ${DATA_DIR} ${DOWNLOADS_DIR} ${MOVIES_DIR}

# Set permissions
chown -R couchpotato:couchpotato ${CONFIG_DIR} ${DATA_DIR} ${DOWNLOADS_DIR} ${MOVIES_DIR}

echo "Starting CouchPotato..."
echo "Config dir: ${CONFIG_DIR}"
echo "Data dir: ${DATA_DIR}"
echo "Downloads dir: ${DOWNLOADS_DIR}"
echo "Movies dir: ${MOVIES_DIR}"

# Execute the command as the couchpotato user
exec su-exec couchpotato "$@" --data_dir=${DATA_DIR} --config_file=${CONFIG_DIR}/settings.conf