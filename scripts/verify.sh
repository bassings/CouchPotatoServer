#!/usr/bin/env bash
#
# verify.sh — the canonical local gate. Mirrors what CI enforces so that
# "green here" means "green in CI". Run this before opening a PR; the
# pre-push git hook (.githooks/pre-push) runs it automatically.
#
# Stages (fail-fast, single exit code):
#   1. ruff lint
#   2. test-trap check (false-green guard — see scripts/check_test_traps.py)
#   3. UI conformance check (design-system drift — a REQUIRED CI check that this
#      gate used to omit, so "green locally" did not imply "green in CI")
#   4. Python unit tests (tests/unit, host interpreter, PYTHONPATH=libs)
#   5. Python integration tests (tests/integration, host interpreter,
#      PYTHONPATH=libs: the direct regression net for the SQLiteAdapter
#      _query_index defects; previously orphaned, never invoked by any runner)
#   6. UI unit tests (vitest)
#   7. E2E tests (Playwright/chromium: server auto-starts via playwright.config.ts)
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
       — ideally inside a venv on Python 3.10–3.14."
fi

# requirements-dev.txt pins ruff exactly (`ruff==X.Y.Z`), and ci.yml installs
# that same pin twice (lint + security-lint jobs) — see T1.5. The import check
# above only proves ruff is importable, not that it's the pinned version, so a
# developer running a stale/different local ruff got a false green here and a
# red CI once the two disagreed. The version is read out of
# requirements-dev.txt rather than hardcoded a second time in this script:
# duplicating the pin across requirements-dev.txt and ci.yml was the accepted
# trade-off; a third copy here was not.
PINNED_RUFF="$(grep -E '^ruff==' requirements-dev.txt | head -1 | sed -E 's/^ruff==//')"
if [[ -z "$PINNED_RUFF" ]]; then
  fail "requirements-dev.txt has no 'ruff==X.Y.Z' pin to check the installed ruff against."
fi
INSTALLED_RUFF="$("$PYTHON" -m ruff --version | awk '{print $2}')"
if [[ "$INSTALLED_RUFF" != "$PINNED_RUFF" ]]; then
  fail "installed ruff ($INSTALLED_RUFF) does not match the pin in requirements-dev.txt ($PINNED_RUFF).
       Fix: $PYTHON -m pip install 'ruff==$PINNED_RUFF'"
fi

# ── 1. Lint ─────────────────────────────────────────────────────────────────
step "1/7 ruff lint"
"$PYTHON" -m ruff check . || fail "ruff found issues"

# ── 2. False-green guard ────────────────────────────────────────────────────
step "2/7 test-trap check"
"$PYTHON" scripts/check_test_traps.py || fail "test-trap check found issues"

# ── 3. UI conformance ───────────────────────────────────────────────────────
step "3/7 UI conformance check"
"$PYTHON" scripts/check_conformance.py || fail "conformance check found issues"

# ── 4. Python unit tests ────────────────────────────────────────────────────
step "4/7 Python unit tests"
"$PYTHON" -m pytest tests/unit/ -q --tb=short -W ignore::SyntaxWarning \
  || fail "Python unit tests failed"

# ── 5. Python integration tests ─────────────────────────────────────────────
step "5/7 Python integration tests"
"$PYTHON" -m pytest tests/integration/ -q --tb=short -W ignore::SyntaxWarning \
  || fail "Python integration tests failed"

# ── 6. UI unit tests ────────────────────────────────────────────────────────
step "6/7 UI unit tests (vitest)"
if [[ ! -d node_modules ]]; then
  echo "node_modules missing — running npm ci..."
  npm ci
fi
npm run test:unit || fail "UI unit tests failed"

# ── 7. E2E tests ────────────────────────────────────────────────────────────
if [[ "$RUN_E2E" -eq 1 ]]; then
  step "7/7 E2E tests (Playwright: chromium + a11y + mobile)"
  # Ensure the chromium browser is present (no-op if already installed).
  npx playwright install chromium >/dev/null 2>&1 || true
  # Start from a clean data dir. This is NOT tidiness: specs delete, re-add and
  # restatus the seeded movie, so a leftover dir makes the gate's result depend
  # on what the previous run happened to leave behind. Measured: a run that had
  # deleted the seeded movie left `.e2e-data` with ZERO media docs, and the next
  # verify failed 5 FEAT-008 tests that had just passed from a clean dir — a
  # gate whose answer depends on history is not a gate. The mobile and a11y
  # stages below always did this; chromium did not.
  rm -rf .e2e-data
  npm run test:e2e -- --project=chromium || fail "E2E tests failed"
  # Small-screen coverage. AGENTS.md treats a mobile layout regression that
  # blocks a core flow as high-priority, and the mobile-chrome project existed
  # for a long time without anything running it. Scoped by testMatch to
  # *.mobile.spec.ts, so this adds seconds, not minutes.
  # Its OWN data dir: the chromium run above mutates the shared library (specs
  # delete, re-add and restatus the seeded movie), and inheriting that state
  # broke this run while it passed standalone.
  rm -rf .e2e-data-mobile
  CP_E2E_DATA_DIR=.e2e-data-mobile npm run test:e2e -- --project=mobile-chrome \
    || fail "Mobile E2E tests failed"
  # Accessibility. These have their own project (testMatch *.a11y.spec.ts) and
  # the chromium project now testIgnores them -- previously they rode along in
  # the chromium run, so without this line scoping the projects would have
  # SILENTLY DROPPED a11y from the local gate. CI has always run them as a
  # separate job (.github/workflows/ci.yml, `test:a11y`); this makes the local
  # gate mirror it, which is the whole contract of this script.
  rm -rf .e2e-data-a11y
  CP_E2E_DATA_DIR=.e2e-data-a11y npm run test:a11y || fail "Accessibility tests failed"
else
  step "7/7 E2E tests: SKIPPED (--no-e2e)"
fi

# ── Informational: static security lint (bandit S rules) ────────────────────
# Non-blocking — legacy code has many findings; surfaced for awareness only.
step "info: security lint (ruff S — non-blocking)"
"$PYTHON" -m ruff check --select S --statistics couchpotato/ CouchPotato.py 2>/dev/null \
  | tail -5 || true

printf '\n\033[1;32m✔ All checks passed — safe to open a PR.\033[0m\n'
