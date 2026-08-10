#!/usr/bin/env bash
#
# Does this change need the browser suites (E2E, accessibility, mobile)?
#
# THE SINGLE SOURCE OF TRUTH for that question. The pre-push hook and the CI
# workflow both call this, and that is the whole point: two copies of "what
# counts as a UI change" drift, and when they drift the quieter side silently
# stops covering something. `tests/unit/test_hybrid_gate.py`
# (TestBothCallersUseTheSharedScript) fails if either caller stops using it.
#
# Exit 0  = run the browser suites.
# Exit 1  = they can be skipped for this change.
#
# Usage:  scripts/needs_e2e.sh <base-ref>
#
# Erring: when in ANY doubt -- no base ref, an unreadable diff, a pattern the
# classifier itself cannot apply -- this exits 0. A slow gate is an annoyance; a skipped gate that should
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

# What CANNOT reach a browser. Everything else runs the suites.
#
# This is inverted from the original design, and the measurement is the
# reason. The first version listed what a browser COULD see and skipped the
# rest. It was wrong twice in review, and the second time showed it could not
# be made right: the UI calls the API from TEMPLATES as well as from Python --
# 33 endpoints across 16 namespaces (app, category, collection, directory,
# download, logging, manage, media, movie, profile, provider, quality,
# release, search, settings, updater). That is the whole application, so an
# honest allowlist would have been `couchpotato/`.
#
# The saving was therefore not independence between backend and UI; it came
# from under-covering. `renamer`, `searcher`, `updater` and `quality` all
# skipped while the browser called every one of those namespaces.
#
# Measured cost of inverting: of the last 60 commits, 6 touch only the paths
# below. That is the real saving, and it is smaller than the original claim.
# What changed is the failure DIRECTION -- an unrecognised path now runs the
# suites instead of skipping them, which is how every other uncertainty in
# this script already resolves.
SKIP_PATTERNS='^(docs/|specs/|QA/|tests/unit/|\.claude/|[^/]*\.md$)'

# Files that could NOT be shown to be irrelevant.
#
# `set +e` around the grep, because `set -e` at the top would abort the script
# on grep's own exit status before the handler below could read it -- and
# aborting means a non-zero exit, which the callers read as "skip". The one
# place the classifier could break would therefore have skipped the suites,
# which is the exact fail-open this block exists to prevent.
set +e
RELEVANT="$(grep -vE "$SKIP_PATTERNS" <<< "$CHANGED")"
GREP_RC=$?
set -e

# grep -v exits 1 when it filters everything out, which is the ordinary
# "nothing relevant" answer, not an error. Only >=2 means grep itself broke.
if [[ "$GREP_RC" -gt 1 ]]; then
  echo "needs_e2e: the classifier itself failed (grep exit $GREP_RC), assuming YES" >&2
  exit 0
fi

if [[ -n "$RELEVANT" ]]; then
  echo "needs_e2e: YES -- files that could reach a browser changed:" >&2
  sed 's/^/  /' <<< "$RELEVANT" >&2
  exit 0
fi

echo "needs_e2e: no -- every changed file is documentation, a plan, a QA note, a unit test or agent scratch ($(echo "$CHANGED" | wc -l | tr -d ' ') file(s))" >&2
exit 1
