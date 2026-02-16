# CouchPotato Docker Container
# Multi-stage build for smaller image

# Stage 1: Build dependencies
FROM python:3.14-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.14-slim

LABEL maintainer="CouchPotato"
LABEL description="CouchPotato - Automatic Movie Downloader"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CP_DOCKER=1 \
    APP_DIR=/app \
    CONFIG_DIR=/config \
    DATA_DIR=/data

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gosu \
        mediainfo \
    && rm -rf /var/lib/apt/lists/*

# Create app user
ARG PUID=1000
ARG PGID=1000
RUN groupadd -g ${PGID} couchpotato \
    && useradd -u ${PUID} -g couchpotato -d ${APP_DIR} -s /bin/bash couchpotato

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=couchpotato:couchpotato . ${APP_DIR}/

# Embed version and build date into version.py
ARG CP_VERSION=dev
RUN python3 -c "import time; f=open('${APP_DIR}/version.py','w'); f.write('VERSION = \'%s\'\nBRANCH = \'master\'\nBUILD_DATE = %d\n' % ('${CP_VERSION}'.lstrip('v'), int(time.time()))); f.close()"

# Create directories
RUN mkdir -p ${CONFIG_DIR} ${DATA_DIR} \
    && chown -R couchpotato:couchpotato ${CONFIG_DIR} ${DATA_DIR}

WORKDIR ${APP_DIR}

VOLUME ["${CONFIG_DIR}", "${DATA_DIR}"]

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -sf http://localhost:5050/ || exit 1

STOPSIGNAL SIGTERM

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python3", "CouchPotato.py", "--console_log", "--data_dir=/data", "--config_file=/config/config.ini"]
