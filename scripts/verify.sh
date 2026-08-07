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
# `|| true`: under `set -euo pipefail` a pipeline whose grep matches nothing
# returns 1, which aborts the script AT THIS ASSIGNMENT, so the guard below
# never runs and the gate exits 1 having printed nothing at all. Verified in
# bash (this script's shell); zsh does not reproduce it.
PINNED_RUFF="$(grep -E '^ruff==' requirements-dev.txt | head -1 | sed -E 's/^ruff==//' || true)"
if [[ -z "$PINNED_RUFF" ]]; then
  fail "requirements-dev.txt has no 'ruff==X.Y.Z' pin to check the installed ruff against."
fi
# Same `|| true` and same reason as the line above -- this construct was left
# unguarded one line after the comment explaining why it is dangerous, which is
# the "fix the instance, miss the class" shape. The import preflight further up
# only proves `import ruff` works; a ruff whose CLI entry point is broken (a
# partial install, a stale console-script shim) passes that and then kills the
# gate here with no output at all. The -z guard turns "unexpected --version
# format" into a named failure instead of the nonsense "installed ruff () does
# not match the pin".
INSTALLED_RUFF="$("$PYTHON" -m ruff --version 2>/dev/null | awk '{print $2}' || true)"
if [[ -z "$INSTALLED_RUFF" ]]; then
  fail "could not read the installed ruff version ('$PYTHON -m ruff --version' produced nothing).
       Fix: $PYTHON -m pip install 'ruff==$PINNED_RUFF'"
fi
if [[ "$INSTALLED_RUFF" != "$PINNED_RUFF" ]]; then
  fail "installed ruff ($INSTALLED_RUFF) does not match the pin in requirements-dev.txt ($PINNED_RUFF).
       Fix: $PYTHON -m pip install 'ruff==$PINNED_RUFF'"
fi

# ── 1. Lint ─────────────────────────────────────────────────────────────────
step "1/7 ruff lint"
"$PYTHON" -m ruff check . || fail "ruff found issues"

# ── 2. False-green guard ────────────────────────────────────────────────────
step "2/7 test-trap check"
"$PYTHON" scripts/check_test_traps.py --require-git || fail "test-trap check found issues"

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
  # T1.7: no `rm -rf .e2e-data*` here any more. tests/e2e/fixtures.ts gives
  # every Playwright WORKER its own server, port and data dir
  # (.e2e-w<N>-data/), seeded fresh at worker startup and deleted at worker
  # teardown through scripts/e2e_worker_data.py's guarded helper -- there is
  # no fixed-name dir left over between runs to clean up, and the fixture
  # deliberately FAILS (AC-DATA-26) rather than silently reusing or wiping
  # one if it ever finds a directory already there. A directory surviving
  # to the start of the NEXT run means a previous run crashed before its own
  # teardown ran; that is a real problem to go look at, not something this
  # script should paper over by deleting it for you.
  #
  # --fail-on-flaky-tests (AC-A11Y-4/QA-56): a no-op HERE, since
  # playwright.config.ts sets `retries: 0` locally and nothing can be
  # classified flaky (failed once, passed on retry) without a retry ever
  # happening -- passed for parity with the CI invocations of this exact
  # command, where retries: 2 makes it load-bearing: a test that fails then
  # passes on retry must still fail CI rather than quietly going green,
  # which is what let a 1-in-5 shared-state race pass as "the suite is
  # green" for a long time.
  # `npx playwright test`, NOT `npm run test:e2e -- --project=...`.
  # Playwright UNIONS repeated --project flags, and test:e2e now names its
  # own three projects (it had to: a bare `npx playwright test` also selects
  # the isolation project, which cannot pass at workers: 1). Composing on top
  # of it therefore WIDENS this step instead of scoping it -- measured, this
  # line ran chromium + accessibility + mobile-chrome, 158 tests, and the
  # three separate steps below then re-ran two of them. The gate must name
  # exactly what each step runs.
  npx playwright test --project=chromium --fail-on-flaky-tests \
    || fail "E2E tests failed"
  # AC-QA-50's isolation proof, pinned to 2 workers because it only
  # demonstrates anything when the mutating and asserting specs land on
  # different workers. The chromium project above runs at workers: 1
  # (AC-SIMP-12), so this cannot ride along with it.
  npx playwright test --project=isolation --workers=2 --fail-on-flaky-tests \
    || fail "E2E worker-isolation proof failed"
  # Small-screen coverage. AGENTS.md treats a mobile layout regression that
  # blocks a core flow as high-priority, and the mobile-chrome project existed
  # for a long time without anything running it. Scoped by testMatch to
  # *.mobile.spec.ts, so this adds seconds, not minutes.
  npx playwright test --project=mobile-chrome --fail-on-flaky-tests \
    || fail "Mobile E2E tests failed"
  # Accessibility. These have their own project (testMatch *.a11y.spec.ts) and
  # the chromium project now testIgnores them -- previously they rode along in
  # the chromium run, so without this line scoping the projects would have
  # SILENTLY DROPPED a11y from the local gate. CI has always run them as a
  # separate job (.github/workflows/ci.yml, `test:a11y`); this makes the local
  # gate mirror it, which is the whole contract of this script.
  npx playwright test --project=accessibility --fail-on-flaky-tests \
    || fail "Accessibility tests failed"
else
  step "7/7 E2E tests: SKIPPED (--no-e2e)"
fi

# ── Informational: static security lint (bandit S rules) ────────────────────
# Non-blocking — legacy code has many findings; surfaced for awareness only.
step "info: security lint (ruff S — non-blocking)"
"$PYTHON" -m ruff check --select S --statistics couchpotato/ CouchPotato.py 2>/dev/null \
  | tail -5 || true

printf '\n\033[1;32m✔ All checks passed — safe to open a PR.\033[0m\n'
