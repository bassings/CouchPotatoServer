#!/bin/bash
# Run tests locally in Docker before pushing
# Usage: ./scripts/test-local.sh [python-version]

set -e

PYTHON_VERSION="${1:-3.12}"
IMAGE_NAME="couchpotato-test:${PYTHON_VERSION}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "🧪 Building test image with Python ${PYTHON_VERSION}..."

docker build -t "$IMAGE_NAME" -f - "$PROJECT_DIR" <<EOF
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

# Install test dependencies
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# Set Python path
ENV PYTHONPATH=/app
EOF

echo "🔬 Running tests (mount source for live files including tests/)..."
docker run --rm \
    -v "$PROJECT_DIR:/app:ro" \
    -w /app \
    "$IMAGE_NAME" \
    pytest -v --tb=short tests/unit/

echo "✅ Tests passed!"
