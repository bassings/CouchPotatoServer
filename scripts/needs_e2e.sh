#!/usr/bin/env bash
#
# Does this change need the browser suites (E2E, accessibility, mobile)?
#
# THE SINGLE SOURCE OF TRUTH for that question. The pre-push hook and the CI
# workflow both call this, and that is the whole point: two copies of "what
# counts as a UI change" drift, and when they drift the quieter side silently
# stops covering something. `tests/unit/test_needs_e2e.sh_contract.py` fails if
# either caller stops using it.
#
# Exit 0  = run the browser suites.
# Exit 1  = they can be skipped for this change.
#
# Usage:  scripts/needs_e2e.sh <base-ref>
#
# Erring: when in ANY doubt -- no base ref, an unreadable diff, an unrecognised
# path -- this exits 0. A slow gate is an annoyance; a skipped gate that should
# have run is how a UI regression reaches master.
set -euo pipefail

BASE="${1:-}"

if [[ -z "$BASE" ]]; then
  echo "needs_e2e: no base ref given, assuming YES" >&2
  exit 0
fi

if ! CHANGED="$(git diff --name-only "$BASE"...HEAD 2>/dev/null)"; then
  echo "needs_e2e: could not diff against '$BASE', assuming YES" >&2
  exit 0
fi

if [[ -z "$CHANGED" ]]; then
  echo "needs_e2e: no changed files, assuming YES" >&2
  exit 0
fi

# Anything that can change what a browser sees, or how it is tested.
#
# `couchpotato/ui/` covers templates, static assets and the new UI's Python
# views. `couchpotato/templates/` is the other live Jinja render root (the
# login page). The Playwright config and fixtures decide what runs at all, and
# package-lock pins the browser itself.
UI_PATTERNS='^(couchpotato/ui/|couchpotato/templates/|tests/e2e/|playwright\.config\.ts$|package\.json$|package-lock\.json$|scripts/verify\.sh$|scripts/needs_e2e\.sh$|\.github/workflows/)'

if echo "$CHANGED" | grep -qE "$UI_PATTERNS"; then
  echo "needs_e2e: YES -- browser-visible files changed:" >&2
  echo "$CHANGED" | grep -E "$UI_PATTERNS" | sed 's/^/  /' >&2
  exit 0
fi

echo "needs_e2e: no -- nothing browser-visible changed ($(echo "$CHANGED" | wc -l | tr -d ' ') file(s))" >&2
exit 1
