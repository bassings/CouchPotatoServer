# PLAN: the work the SonarQube pass uncovered

The scanner pass closed on 2026-09-07 with 1267 open findings down to 1131 and
nothing dismissed to move a number. Its real output was four user-facing
defects that no rule reported, found by reading code while assessing findings
that mostly did not need fixing. This plan carries those, plus two pieces of
overdue hygiene the pass exposed.

Explicitly OUT OF SCOPE, by the owner's instruction: the seven merged library
records on the production server. Not touched by this plan.

## Scope correction, 2026-09-07

The owner's scope was "assess and resolve anything MEDIUM or higher". The
first pass worked through the nine largest rules BY VOLUME instead, which
overlaps that scope but is not it. Measured against the fresh scan:

| | count |
|---|---|
| open findings | 1131 |
| MEDIUM or higher | 804 |
| of those, in rules already assessed | 553 |
| **MEDIUM+ never looked at** | **~251** |
| HIGH never looked at | 40, across 15 rules |
| BLOCKER never looked at | 1 |

So the scanner work is NOT finished. Ranking by rule volume put 143 findings in
dead JavaScript ahead of a BLOCKER in the logger, which is the wrong order by
the owner's stated priority.

The BLOCKER is already assessed as part of writing this: `python:S3516` at
`couchpotato/core/logger.py:245`, "refactor this method to not always return
the same value", against `PrivacyFilter.filter()`. It is a FALSE POSITIVE.
`logging.Filter.filter()` returns truthy to KEEP a record, and a redacting
filter must keep every record; the code's own comment says a filter that
swallows the line removes the reason the line was logged. Both return paths
correctly return True.
BUT engaging with it found a gap worth closing, though NOT as bad as first
recorded. CORRECTED after measuring instead of asserting: no test asserts that
return value EXPLICITLY, which is true, but the suite does not stay green.
Mutating the final `return True` to `return False` fails TWO tests, and the
second is pre-existing: `test_privacy_filter_applied_via_child_logger` asserts
a redacted message reaches the log, and a falsy return means no record reaches
the log at all. So the danger was overstated. The explicit guard is still worth
having, because an incidental failure in a redaction test does not tell the
next person that the RETURN VALUE is the contract they broke, and it covers
only one of the two return paths. That guard is T1 below.

## Tasks

- [x] T1: pin `PrivacyFilter.filter()` returning truthy, then dismiss the
      BLOCKER. DONE. Merged as #319, two tests pinning both return paths, each
      proven by mutating that path to `return False` and watching that specific
      test fail, restored byte-identical. `python:S3516` then marked false
      positive with a comment naming those tests, so the dismissal cites
      something enforceable. The project now has ZERO blockers. The guard must fail if any path returns a falsy value. Prove it
      by making one path return False and watching it fail. Only then mark
      `python:S3516` false positive, with the guard named in the comment so the
      dismissal cites something enforceable rather than an argument, state:
      queued
- [ ] T2: assess the ~251 MEDIUM+ findings in the rules the first pass never
      reached, HIGH first: `javascript:S3776` (7), `python:S1186` (6),
      `python:S8904` (6), `python:S5779` (5), `Web:S7927` (3),
      `python:S1143` (2), `python:S5996` (2), `python:S5797` (2), and the
      singletons `javascript:S4275`, `python:S8415`, `javascript:S3735`,
      `python:S8520`, `typescript:S5845`, `python:S5727`, `python:S6903`.
      Then the MEDIUM-only remainder. Same discipline as the first pass: assess
      before fixing, fix what should be fixed, leave the rest open with a
      recorded reason and an expiry, dismiss only genuine false positives,
      state: queued (needs: T1)
- [ ] T2b: `isLocalIP()` recognises neither IPv6 loopback form. RAISED IN
      REVIEW: the first draft described this defect in the PR body and then
      never scheduled it, so it would have been lost. TWO bugs, and the second
      is the one that matters: the regex is a JavaScript literal pasted into
      Python so its delimiters are literal characters, AND the preceding
      `ip.lstrip('htps:/')` takes a CHARACTER SET rather than a prefix, so
      `'::1'.lstrip('htps:/')` returns `'1'` and eats the loopback marker
      before the regex ever runs. Fixing only the regex would not have fixed
      the bug. The same line mangled any hostname starting with h, t, p or s.
      Its one caller, `http_client.py:131`, exempts local hosts from being
      permanently disabled after repeated failures, so an IPv6-only local
      service is disabled where `127.0.0.1` would not be, state: in-flight
- [ ] T3: production promotion. Fourteen commits have merged since v3.77.0 and
      none are in production, including BUG-018, where the scanner filed every
      remake under the original film, and the Docker CVE pin.
      CORRECTED AFTER REVIEW. The first draft said "backup.sh first, verify the
      snapshot exists and is non-empty". That is not the documented procedure
      and it is not sufficient. Three separate findings, all real:
      1. Use `./scripts/backup.sh --retain 14`, NOT the bare form.
         `docs/development-process.md:751-756`: without retention, every risky
         promotion adds one more full database plus settings snapshot, forever,
         to the volume that also holds the live database. That is a slow way to
         reproduce the disk-full failure the snapshots exist to survive.
      2. "Exists and non-empty" is exactly the check that passes on a useless
         snapshot. `docs/development-process.md:758-775` requires three things:
         `PRAGMA integrity_check` must print `ok`; `PRAGMA foreign_key_check`
         must return NO ROWS, because integrity_check does not check foreign
         keys and this schema declares them, so an orphaned row passes the
         first check and fails recovery; and `config.ini` must be readable,
         because `backup.sh` deliberately WARNS and exits 0 when it cannot find
         the settings file. Both PRAGMAs can pass on a snapshot containing no
         settings at all, and the database alone does not restore a working
         install. If `sqlite3` is absent on the host, use the Python
         interpreter fallback the script itself uses.
      3. Record what is running BEFORE restarting, or there is no rollback
         target. `docs/development-process.md:391-418`: the host pulls
         `:latest` and promotion moves that tag, so the old target cannot be
         reconstructed afterwards. Capture BOTH
         `docker inspect couchpotato --format '{{.Config.Image}} {{.Image}}'`
         and `docker exec couchpotato cat /app/version.py`. NOT
         `printenv CP_VERSION`, which is an ARG rather than an ENV and is
         absent from the running container, and never a grep for /version/i,
         which returns PYTHON_VERSION and hands you the interpreter version as
         a rollback tag, silently and plausibly, mid-incident.
      Only then promote the tested beta byte-for-byte. Owner has agreed to THIS
      promotion; a later one for the fixes below needs its own agreement,
      state: queued

- [ ] T4: make SonarQube staleness visible. REFRAMED AFTER REVIEW, because the
      first draft was unbuildable. It said "run `make sonar` automatically after
      a merge". Every job under `.github/workflows/**` runs on GitHub-hosted
      `ubuntu-latest`, which cannot reach the scanner at a private RFC1918
      address, and it needs `$HOME/.sonar-token`. `CLAUDE.md:66` also states the
      scan must NEVER run in CI. So a conventional post-merge workflow can
      neither reach the service nor be allowed to.
      The actual requirement is narrower than "automate the scan": the
      dashboard must not SILENTLY describe a stale commit. It was a month stale
      today and nothing said so, which nearly attached a false-positive
      justification to the wrong function.
      Deliverable: a local, non-blocking staleness check that compares the
      project's last analysed revision against HEAD and says so out loud, plus
      whatever prompts a human to run `make sonar`. It must never fail a build,
      per the standing rule that a scan which can fail a build creates pressure
      to make the number green rather than the code better,
      state: queued

- [ ] T5: issue #312, event wiring is guarded in one direction only.
      `test_event_wiring.py` catches an event fired with no listener, and
      nothing catches a listener with no sender, which is the direction that
      has actually cost this project. 38 registered names are never fired.
      Deliverable is the reverse guard plus an adjudication of the 38, with an
      allowlist that fails in both directions so it cannot become a dumping
      ground. CORRECTED AFTER REVIEW: I listed `movie.snatched` and
      `movie.downloaded` as confirmed dead. THEY ARE NOT. Both are dispatched
      with a runtime-built name, `release/main.py:554` fires
      `'%s.snatched' % data['type']` and `media/main.py:873` fires
      `'%s.downloaded' % m.get('type','movie')`, which resolve to exactly those
      names for a movie. I hand-checked by grepping the literal string, a method
      that by construction cannot match a templated name, and which this very
      plan had already recorded as insufficient. Issue #312 is corrected.
      That RAISES the bar for this task: any reverse guard MUST resolve
      templated dispatch, or it will report working notifications as dead and
      send someone rewiring a feature that already works, which is worse than
      the gap it closes. Still orphaned after re-checking against templated
      dispatch: `media.mark_watched`, and
      `app.test`, which has four listeners including a 12-case path-safety
      table for `isSubFolder` that has not run since the FastAPI migration,
      state: queued (needs: T1)
- [ ] T6: issue #311, the Trakt OAuth device flow has no reachable UI.
      `automation.trakt.device_code` and `automation.trakt.poll_token` are
      registered API views whose only caller is `trakt.js`, which nothing
      serves. Anyone configuring Trakt today cannot complete authorisation.
      Port the control into `couchpotato/ui/`, or retire the endpoints if the
      feature is not wanted, state: queued (needs: T5)
- [ ] T7: issue #314, the folder browser announces `role="listbox"` and keeps
      none of it: no arrow keys, no `aria-selected`, no
      `aria-activedescendant`, every folder its own tab stop. Remove the ARIA
      rather than adopt the `<select>` the scanner suggested. Fold in the
      known keyboard-escape and focus-trap gap in the same modal, and consider
      the eight deferred `Web:S6819` dialog findings here since a native
      `<dialog>` solves that half properly, state: queued (needs: T6)
- [ ] T8: five films identified earlier today that are still not added to the
      library. Data task, no PR, state: queued (needs: T7)

## Conductor log
