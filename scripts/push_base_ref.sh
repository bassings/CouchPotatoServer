#!/usr/bin/env bash
#
# Which ref should a pre-push change-surface check diff against?
#
# The answer is the branch this work will MERGE INTO, and that is not
# `@{upstream}`. Once a branch has been pushed, `@{upstream}` is its own
# remote-tracking ref, so diffing against it narrows the question from "what
# does this PR change" to "what did I change since my last push". A branch
# whose first commit touches the UI and whose second is Python-only then takes
# the fast path, even though the cumulative PR still changes the UI.
#
# CI has never had this problem: it diffs `github.base_ref` explicitly. That
# made the drift worse rather than better, because the two callers of the
# single source of truth were asking it different questions.
#
# Prints one ref on stdout. Errs towards a base that is FURTHER back (more
# files in the diff, more likely to run the browser suites) rather than nearer.
set -euo pipefail

# What the remote itself calls its default branch, when that is known.
if DEFAULT="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)"; then
  if git rev-parse --verify --quiet "$DEFAULT" >/dev/null; then
    echo "$DEFAULT"
    exit 0
  fi
fi

for candidate in origin/master origin/main master main; do
  if git rev-parse --verify --quiet "$candidate" >/dev/null; then
    echo "$candidate"
    exit 0
  fi
done

# Nothing resolvable. Print the empty string: needs_e2e.sh treats a missing
# base ref as "assume YES", which is the safe end of this decision.
echo ""
