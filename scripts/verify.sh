#!/usr/bin/env bash
#
# verify.sh — the canonical local gate. Mirrors what CI enforces so that
# "green here" means "green in CI", with ONE deliberate exception: a browser
# test that fails and then passes on its one local retry is green here and red
# in CI (owner decision 2026-11-21), and is listed at the end of step 7 and
# again in the final summary. Run this before opening a PR; the pre-push git
# hook (.githooks/pre-push) runs it automatically.
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
#   ./scripts/verify.sh --e2e-only # run ONLY step 7 (steps 0-6 skipped). The seam
#                                  # tests/unit/test_e2e_local_retry_gate.py drives
#                                  # with a stub `npx`, so step 7 is run, not read.
#
# Env:
#   PYTHON   interpreter to use. Default: ./.venv/bin/python when it exists,
#            otherwise python3. (A bare `python` is never assumed — it does not
#            exist on a stock macOS + Homebrew setup.)

set -euo pipefail

RUN_E2E=1
E2E_ONLY=0
FLAKY_REPORT=''
FLAKY_DIR=''
[[ "${1:-}" == "--no-e2e" ]] && RUN_E2E=0
[[ "${1:-}" == "--e2e-only" ]] && E2E_ONLY=1

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

# Steps 0-6 run unless --e2e-only; the `if` closes just before step 7 and is
# deliberately not re-indented, to keep this diff reviewable.
if [[ "$E2E_ONLY" -eq 0 ]]; then
# ── 0. Preflight: required Python deps present? ─────────────────────────────
if ! "$PYTHON" -c "import bcrypt, httpx, ruff" >/dev/null 2>&1; then
  fail "Python deps missing (bcrypt/httpx/ruff). Run 'make setup' (or:
       $PYTHON -m pip install -r requirements.txt -r requirements-dev.txt)
       - inside a venv on Python 3.15."
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
if [[ ! -d node_modules/@typescript/native ||
      ! -d node_modules/@typescript/typescript6 ||
      ! -x node_modules/.bin/tsc ||
      ! -x node_modules/.bin/tsc6 ]]; then
  echo "TypeScript 7 compiler or TypeScript 6 AST compatibility API missing — running npm ci..."
  npm ci
fi
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

fi  # end of steps 0-6 (skipped by --e2e-only)

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
  # Local differs from CI on purpose (owner decision, 2026-11-21): each
  # invocation below RETRIES a failed test ONCE (--retries=1) and does NOT pass
  # --fail-on-flaky-tests. A test that fails twice fails the gate exactly as
  # before. A test that fails and then passes does not, but it is never hidden:
  # every invocation also writes Playwright's JSON report, and
  # scripts/e2e_flaky_summary.py lists every test whose own status is "flaky"
  # at the end of this step and again in the final summary. CI is unchanged:
  # playwright.config.ts gives it `retries: 2` and every ci.yml invocation
  # keeps --fail-on-flaky-tests (AC-A11Y-4/QA-56), so a test that fails then
  # passes still fails CI rather than quietly going green, which is what let a
  # 1-in-5 shared-state race pass as "the suite is green" for a long time.
  # Locally the config's `retries` stays 0, so a plain `npx playwright test`
  # run is unchanged and the retry comes from this script alone.
  # tests/unit/test_e2e_local_retry_gate.py pins all of this.
  #
  # The summary is given the four report files by name, never a glob: an
  # invocation that wrote no report must read as UNKNOWN, not as "none flaky".
  FLAKY_DIR="$(mktemp -d)"
  # The list is also printed when the gate FAILS in step 7: a test that only
  # passed on retry in an earlier invocation must not vanish because a later
  # one failed. It runs from the EXIT trap, before the reports are removed, and
  # exit status is kept (the trap does not call `exit`). Reports for
  # invocations that never ran read as UNKNOWN: a missing file cannot tell
  # "did not run" from "ran and wrote nothing", so it is not guessed.
  flaky_summary() {
    "$PYTHON" scripts/e2e_flaky_summary.py "$FLAKY_DIR/chromium.json" "$FLAKY_DIR/isolation.json" "$FLAKY_DIR/mobile-chrome.json" "$FLAKY_DIR/accessibility.json" \
      || echo 'UNKNOWN: the flaky-test summary itself failed to run.'
  }
  on_exit() {
    local status=$?
    if [[ "$status" -ne 0 ]]; then
      printf '\n%s\n' "$(flaky_summary)"
    fi
    rm -rf "$FLAKY_DIR"
  }
  trap on_exit EXIT
  # The html reporter is kept (CI uploads it); `never` stops it opening a
  # browser on a failed run, which the config's own reporter entry does too.
  export PLAYWRIGHT_HTML_OPEN=never
  # `npx playwright test`, NOT `npm run test:e2e -- --project=...`.
  # Playwright UNIONS repeated --project flags, and test:e2e now names its
  # own three projects (it had to: a bare `npx playwright test` also selects
  # the isolation project, which cannot pass at workers: 1). Composing on top
  # of it therefore WIDENS this step instead of scoping it -- measured, this
  # line ran chromium + accessibility + mobile-chrome, 158 tests, and the
  # three separate steps below then re-ran two of them. The gate must name
  # exactly what each step runs.
  PLAYWRIGHT_JSON_OUTPUT_NAME="$FLAKY_DIR/chromium.json" \
  npx playwright test --project=chromium --trace=retain-on-failure --retries=1 --reporter=list,html,json \
    || fail "E2E tests failed"
  # AC-QA-50's isolation proof, pinned to 2 workers because it only
  # demonstrates anything when the mutating and asserting specs land on
  # different workers. The chromium project above runs at workers: 1
  # (AC-SIMP-12), so this cannot ride along with it.
  PLAYWRIGHT_JSON_OUTPUT_NAME="$FLAKY_DIR/isolation.json" \
  npx playwright test --project=isolation --workers=2 --trace=retain-on-failure --retries=1 --reporter=list,html,json \
    || fail "E2E worker-isolation proof failed"
  # Small-screen coverage. AGENTS.md treats a mobile layout regression that
  # blocks a core flow as high-priority, and the mobile-chrome project existed
  # for a long time without anything running it. Scoped by testMatch to
  # *.mobile.spec.ts, so this adds seconds, not minutes.
  PLAYWRIGHT_JSON_OUTPUT_NAME="$FLAKY_DIR/mobile-chrome.json" \
  npx playwright test --project=mobile-chrome --trace=retain-on-failure --retries=1 --reporter=list,html,json \
    || fail "Mobile E2E tests failed"
  # Accessibility. These have their own project (testMatch *.a11y.spec.ts) and
  # the chromium project now testIgnores them -- previously they rode along in
  # the chromium run, so without this line scoping the projects would have
  # SILENTLY DROPPED a11y from the local gate. CI has always run them as a
  # separate job (.github/workflows/ci.yml, `test:a11y`); this makes the local
  # gate mirror it, which is the whole contract of this script.
  PLAYWRIGHT_JSON_OUTPUT_NAME="$FLAKY_DIR/accessibility.json" \
  npx playwright test --project=accessibility --trace=retain-on-failure --retries=1 --reporter=list,html,json \
    || fail "Accessibility tests failed"
  FLAKY_REPORT="$(flaky_summary)"
  printf '\n%s\n' "$FLAKY_REPORT"
else
  step "7/7 E2E tests: SKIPPED (--no-e2e)"
fi

# ── Informational: static security lint (bandit S rules) ────────────────────
# Non-blocking — legacy code has many findings; surfaced for awareness only.
step "info: security lint (ruff S — non-blocking)"
"$PYTHON" -m ruff check --select S --statistics couchpotato/ CouchPotato.py 2>/dev/null \
  | tail -5 || true

printf '\n\033[1;32m✔ All checks passed — safe to open a PR.\033[0m\n'
if [[ "$RUN_E2E" -eq 1 ]]; then
  printf '%s\n' "$FLAKY_REPORT"
fi
