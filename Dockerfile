# CouchPotato Docker Container
# Multi-stage build for smaller image

# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

LABEL maintainer="CouchPotato"
LABEL description="CouchPotato - Automatic Movie Downloader"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_DIR=/app \
    CONFIG_DIR=/config \
    DATA_DIR=/data

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        mediainfo \
        gosu \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN groupadd -g 1000 couchpotato \
    && useradd -u 1000 -g couchpotato -d ${APP_DIR} -s /bin/bash couchpotato

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=couchpotato:couchpotato . ${APP_DIR}/

# Create directories
RUN mkdir -p ${CONFIG_DIR} ${DATA_DIR} \
    && chown -R couchpotato:couchpotato ${CONFIG_DIR} ${DATA_DIR}

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR ${APP_DIR}

VOLUME ["${CONFIG_DIR}", "${DATA_DIR}"]

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -sf http://localhost:5050/ || exit 1

# Use SIGTERM for graceful shutdown
STOPSIGNAL SIGTERM

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "CouchPotato.py", "--console_log"]
