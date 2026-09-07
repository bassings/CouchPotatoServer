#!/usr/bin/env bash
# Report how far the last SonarQube analysis has drifted from HEAD.
#
# WHY THIS EXISTS. A finding's line number describes the commit the server last
# analysed, and SonarQube never tells you which commit that was. On 2026-09-07
# this project's findings were a month stale: `renamer/main.py:2129` was a blank
# line, and walking back from it landed in the wrong function entirely. A
# per-site dismissal written from that would have justified unrelated code.
#
# WHY IT READS A LOCAL FILE RATHER THAN THE SERVER. The analysis token cannot
# read /api/project_analyses/search; it answers "Insufficient privileges". Only
# a global instance-administrator token can, and requiring one for a routine
# staleness check is the wrong trade: that credential can delete any project on
# the server. `make sonar` records the analysed commit here instead, so this
# check needs no token, no network and no privileges.
#
# THIS NEVER FAILS. It exits 0 whatever it finds. A scan that can fail a build
# creates pressure to make the number green rather than the code better, which
# is the one thing the project's standards are explicit about avoiding.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
STAMP="$REPO_ROOT/.sonar-last-analysis"

HEAD_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

if [ ! -r "$STAMP" ]; then
    echo "SonarQube: no local record of an analysis from this checkout."
    echo "  Findings on the dashboard may describe ANY commit, including one"
    echo "  from weeks ago. Re-fetch line numbers only after 'make sonar'."
    exit 0
fi

ANALYSED_SHA="$(head -n1 "$STAMP" | tr -d '[:space:]')"
ANALYSED_AT="$(sed -n '2p' "$STAMP" | tr -d '\r')"

if [ "$ANALYSED_SHA" = "$HEAD_SHA" ]; then
    echo "SonarQube: analysis matches HEAD (${HEAD_SHA:0:12}), recorded ${ANALYSED_AT:-unknown}."
    echo "  Line numbers describe this tree."
    exit 0
fi

if ! git cat-file -e "$ANALYSED_SHA^{commit}" 2>/dev/null; then
    echo "SonarQube: last analysed ${ANALYSED_SHA:0:12}, which is not in this"
    echo "  repository (rebased away, or analysed from another checkout)."
    echo "  Treat every line number as unverified until you re-run 'make sonar'."
    exit 0
fi

BEHIND="$(git rev-list --count "$ANALYSED_SHA..$HEAD_SHA" 2>/dev/null || echo '?')"
# Only files SonarQube actually analyses matter for line drift.
CHANGED="$(git diff --name-only "$ANALYSED_SHA..$HEAD_SHA" -- '*.py' '*.js' '*.ts' '*.html' 2>/dev/null | wc -l | tr -d ' ')"

echo "SonarQube: STALE by $BEHIND commit(s)."
echo "  analysed : ${ANALYSED_SHA:0:12}  ${ANALYSED_AT:-unknown}"
echo "  HEAD     : ${HEAD_SHA:0:12}"
echo "  $CHANGED analysed file(s) changed since."
if [ "$CHANGED" != "0" ]; then
    echo "  LINE NUMBERS IN FINDINGS ARE UNRELIABLE for those files."
    echo "  Re-run 'make sonar', then re-fetch, before adjudicating anything."
fi
exit 0
