# CouchPotato Docker Container
# Multi-stage build for smaller image
#
# Base image: python:3.14-alpine (Alpine Linux / musl).
# Chosen over python:3.14-slim (Debian) because the Alpine base ships with 0
# known CVEs vs ~106 on Debian 13 — the Debian OS packages (perl, ncurses,
# libssh2, libcurl) repeatedly carry HIGH/CRITICAL CVEs with no upstream fix.

# Stage 1: Build dependencies
FROM python:3.14-alpine AS builder

WORKDIR /build

# Build toolchain — only needed if a dependency lacks a prebuilt musllinux
# wheel and must compile from source. Lives in the builder stage only and is
# discarded; the runtime image never sees it.
RUN apk add --no-cache \
        build-base \
        libffi-dev \
        openssl-dev \
        libxml2-dev \
        libxslt-dev \
        cargo

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip==26.1.1 \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.14-alpine

LABEL maintainer="CouchPotato"
LABEL description="CouchPotato - Automatic Movie Downloader"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CP_DOCKER=1 \
    APP_DIR=/app \
    CONFIG_DIR=/config \
    DATA_DIR=/data

# Install minimal runtime dependencies.
# - su-exec is Alpine's lightweight gosu equivalent (drops privileges in the
#   entrypoint after fixing volume ownership).
# - curl is intentionally NOT installed — the HEALTHCHECK uses Python's stdlib
#   urllib instead, avoiding libcurl and its recurring CVEs.
# - libstdc++ is required at runtime by mediainfo and some compiled wheels.
RUN apk add --no-cache \
        ca-certificates \
        su-exec \
        mediainfo \
        libstdc++

# Create app user
ARG PUID=1000
ARG PGID=1000
RUN addgroup -g ${PGID} couchpotato \
    && adduser -u ${PUID} -G couchpotato -h ${APP_DIR} -s /bin/sh -D couchpotato

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
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:5050/', timeout=5)" || exit 1

STOPSIGNAL SIGTERM

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python3", "CouchPotato.py", "--console_log", "--data_dir=/data", "--config_file=/config/config.ini"]
