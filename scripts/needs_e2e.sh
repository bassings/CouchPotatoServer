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

# --no-renames: with rename detection ON, `git diff --name-only` reports
# only the DESTINATION of a rename, so moving a live template out of the
# UI tree looks like a change to wherever it landed. A deletion dressed as
# a rename must not be quieter than a deletion.
if ! CHANGED="$(git diff --no-renames --name-only "$BASE"...HEAD 2>/dev/null)"; then
  echo "needs_e2e: could not diff against '$BASE', assuming YES" >&2
  exit 0
fi

if [[ -z "$CHANGED" ]]; then
  echo "needs_e2e: no changed files, assuming YES" >&2
  exit 0
fi

# Anything that can change what a browser sees, or how it is tested.
#
# `couchpotato/ui/` holds the Jinja templates and the new UI's Python views.
# `couchpotato/static/` is a SEPARATE tree, mounted at /static, holding the
# client-side JavaScript those templates load -- including movie-filter.js,
# which is exactly what tests/e2e/filters.spec.ts exercises. An earlier
# version of this comment claimed couchpotato/ui/ covered static assets; it
# does not, and the browser suites were skippable for the JS driving the UI.
# `couchpotato/templates/` is the other live Jinja render root (the login
# page). The Playwright config and fixtures decide what runs at all, and
# package-lock pins the browser itself.
UI_PATTERNS='^(couchpotato/ui/|couchpotato/static/|couchpotato/templates/|tests/e2e/|playwright\.config\.ts$|package\.json$|package-lock\.json$|scripts/verify\.sh$|scripts/needs_e2e\.sh$|\.github/workflows/)'

# A here-string, NOT a pipe, and deliberately so. `echo ... | grep -q` made
# grep exit at the first match; with enough remaining output to fill the pipe
# buffer the writer took SIGPIPE, the pipeline returned 141 under `pipefail`,
# and the `if` took the FALSE branch. The failure scaled the wrong way: the
# more files a change touched, the more likely it was to SKIP the browser
# suites. Measured on this machine: correct at 1,000 paths, wrong at 4,000.
MATCHED="$(grep -E "$UI_PATTERNS" <<< "$CHANGED" || true)"

if [[ -n "$MATCHED" ]]; then
  echo "needs_e2e: YES -- browser-visible files changed:" >&2
  sed 's/^/  /' <<< "$MATCHED" >&2
  exit 0
fi

echo "needs_e2e: no -- nothing browser-visible changed ($(echo "$CHANGED" | wc -l | tr -d ' ') file(s))" >&2
exit 1
