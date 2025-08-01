# CouchPotato Docker Container
# Based on Python 3.12 Alpine Linux for better security and smaller size

FROM python:3.13-alpine

# Set version label
LABEL version="1.0.0"
LABEL description="CouchPotato - Automatic Movie Downloader"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_DIR=/app \
    CONFIG_DIR=/config \
    DATA_DIR=/data \
    DOWNLOADS_DIR=/downloads \
    MOVIES_DIR=/movies \
    PUID=1000 \
    PGID=1000

    # Install system dependencies
    RUN apk add --no-cache \
        bash \
        ca-certificates \
        curl \
        git \
        mediainfo \
        unzip \
        p7zip \
        shadow \
        tzdata \
        && rm -rf /var/cache/apk/*

# Create app user and group
RUN addgroup -g ${PGID} -S couchpotato \
    && adduser -u ${PUID} -S couchpotato -G couchpotato -h ${APP_DIR} -s /bin/bash

# Create directories
RUN mkdir -p ${APP_DIR} ${CONFIG_DIR} ${DATA_DIR} ${DOWNLOADS_DIR} ${MOVIES_DIR} \
    && chown -R couchpotato:couchpotato ${APP_DIR} ${CONFIG_DIR} ${DATA_DIR} ${DOWNLOADS_DIR} ${MOVIES_DIR}

# Copy application code
COPY --chown=couchpotato:couchpotato . ${APP_DIR}/

# Copy startup script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set working directory
WORKDIR ${APP_DIR}

# Install Python dependencies that might be needed for Python 3 compatibility
RUN pip install --no-cache-dir \
    six \
    future \
    configparser

# Create volumes
VOLUME ["${CONFIG_DIR}", "${DATA_DIR}", "${DOWNLOADS_DIR}", "${MOVIES_DIR}"]

# Expose port
EXPOSE 5050

# Set user
USER couchpotato

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5050/ || exit 1

# Entry point
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "CouchPotato.py", "--console_log"]