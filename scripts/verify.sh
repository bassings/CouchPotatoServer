#!/usr/bin/env bash
#
# verify.sh — the canonical local gate. Mirrors what CI enforces so that
# "green here" means "green in CI". Run this before opening a PR; the
# pre-push git hook (.githooks/pre-push) runs it automatically.
#
# Stages (fail-fast, single exit code):
#   1. ruff lint
#   2. test-trap check (false-green guard — see scripts/check_test_traps.py)
#   3. Python unit tests (tests/unit, host interpreter, PYTHONPATH=libs)
#   4. UI unit tests (vitest)
#   5. E2E tests (Playwright/chromium — server auto-starts via playwright.config.ts)
#
# Usage:
#   ./scripts/verify.sh            # full gate
#   ./scripts/verify.sh --no-e2e   # skip the slow E2E stage (lint + unit only)
#
# Env:
#   PYTHON   interpreter to use. Default: ./.venv/bin/python when it exists,
#            otherwise python3. (A bare `python` is never assumed — it does not
#            exist on a stock macOS + Homebrew setup.)

set -euo pipefail

RUN_E2E=1
[[ "${1:-}" == "--no-e2e" ]] && RUN_E2E=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Prefer the project venv so the gate runs with no env var and no ceremony. The
# app's deps (bcrypt, httpx) live there, not in a system python3, and requiring
# `PYTHON=.venv/bin/python make verify` to be remembered is how the gate ends up
# skipped. Exported so the Playwright webServer (playwright.config.ts) starts the
# app with the SAME interpreter that ran the unit tests.
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    PYTHON="${PROJECT_DIR}/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi
export PYTHON

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
step "1/5 ruff lint"
"$PYTHON" -m ruff check . || fail "ruff found issues"

# ── 2. False-green guard ────────────────────────────────────────────────────
step "2/5 test-trap check"
"$PYTHON" scripts/check_test_traps.py || fail "test-trap check found issues"

# ── 3. Python unit tests ────────────────────────────────────────────────────
step "3/5 Python unit tests"
"$PYTHON" -m pytest tests/unit/ -q --tb=short -W ignore::SyntaxWarning \
  || fail "Python unit tests failed"

# ── 4. UI unit tests ────────────────────────────────────────────────────────
step "4/5 UI unit tests (vitest)"
if [[ ! -d node_modules ]]; then
  echo "node_modules missing — running npm ci..."
  npm ci
fi
npm run test:unit || fail "UI unit tests failed"

# ── 5. E2E tests ────────────────────────────────────────────────────────────
if [[ "$RUN_E2E" -eq 1 ]]; then
  step "5/5 E2E tests (Playwright/chromium)"
  # Ensure the chromium browser is present (no-op if already installed).
  npx playwright install chromium >/dev/null 2>&1 || true
  npm run test:e2e -- --project=chromium || fail "E2E tests failed"
else
  step "5/5 E2E tests — SKIPPED (--no-e2e)"
fi

# ── Informational: static security lint (bandit S rules) ────────────────────
# Non-blocking — legacy code has many findings; surfaced for awareness only.
step "info: security lint (ruff S — non-blocking)"
"$PYTHON" -m ruff check --select S --statistics couchpotato/ CouchPotato.py 2>/dev/null \
  | tail -5 || true

printf '\n\033[1;32m✔ All checks passed — safe to open a PR.\033[0m\n'
