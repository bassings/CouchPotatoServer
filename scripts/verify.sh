#!/usr/bin/env bash
#
# verify.sh — the canonical local gate. Mirrors what CI enforces so that
# "green here" means "green in CI". Run this before opening a PR; the
# pre-push git hook (.githooks/pre-push) runs it automatically.
#
# Stages (fail-fast, single exit code):
#   1. ruff lint
#   2. Python unit tests (tests/unit, host interpreter, PYTHONPATH=libs)
#   3. UI unit tests (vitest)
#   4. E2E tests (Playwright/chromium — server auto-starts via playwright.config.ts)
#
# Usage:
#   ./scripts/verify.sh            # full gate
#   ./scripts/verify.sh --no-e2e   # skip the slow E2E stage (lint + unit only)
#
# Env:
#   PYTHON   interpreter to use (default: python3)

set -euo pipefail

PYTHON="${PYTHON:-python3}"
RUN_E2E=1
[[ "${1:-}" == "--no-e2e" ]] && RUN_E2E=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

export PYTHONPATH="${PROJECT_DIR}/libs${PYTHONPATH:+:$PYTHONPATH}"

step() { printf '\n\033[1;34m▶ %s\033[0m\n' "$1"; }
fail() { printf '\n\033[1;31m✖ %s\033[0m\n' "$1" >&2; exit 1; }

# ── 0. Preflight: required Python deps present? ─────────────────────────────
if ! "$PYTHON" -c "import bcrypt, httpx, ruff" >/dev/null 2>&1; then
  fail "Python deps missing (bcrypt/httpx/ruff). Run 'make setup' (or:
       $PYTHON -m pip install -r requirements.txt -r requirements-dev.txt)
       — ideally inside a venv on Python 3.10–3.13."
fi

# ── 1. Lint ─────────────────────────────────────────────────────────────────
step "1/4 ruff lint"
"$PYTHON" -m ruff check . || fail "ruff found issues"

# ── 2. Python unit tests ────────────────────────────────────────────────────
step "2/4 Python unit tests"
"$PYTHON" -m pytest tests/unit/ -q --tb=short -W ignore::SyntaxWarning \
  || fail "Python unit tests failed"

# ── 3. UI unit tests ────────────────────────────────────────────────────────
step "3/4 UI unit tests (vitest)"
if [[ ! -d node_modules ]]; then
  echo "node_modules missing — running npm ci..."
  npm ci
fi
npm run test:unit || fail "UI unit tests failed"

# ── 4. E2E tests ────────────────────────────────────────────────────────────
if [[ "$RUN_E2E" -eq 1 ]]; then
  step "4/4 E2E tests (Playwright/chromium)"
  # Ensure the chromium browser is present (no-op if already installed).
  npx playwright install chromium >/dev/null 2>&1 || true
  npm run test:e2e -- --project=chromium || fail "E2E tests failed"
else
  step "4/4 E2E tests — SKIPPED (--no-e2e)"
fi

printf '\n\033[1;32m✔ All checks passed — safe to open a PR.\033[0m\n'
