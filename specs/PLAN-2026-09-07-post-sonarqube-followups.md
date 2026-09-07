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

- [ ] T1: pin `PrivacyFilter.filter()` returning truthy, then dismiss the
      BLOCKER. The guard must fail if any path returns a falsy value. Prove it
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
- [ ] T3: production promotion. Fourteen commits have merged since v3.77.0 and
      none are in production, including BUG-018, where the scanner filed every
      remake under the original film, and the Docker CVE pin. The backup
      trigger is a mechanical test, and it says TAKE ONE: 47 non-exempt files
      have changed since the last stable tag. So `./scripts/backup.sh` first,
      verify the snapshot exists and is non-empty, then promote the tested
      beta byte-for-byte. Owner has agreed to THIS promotion; a later one for
      the fixes below needs its own agreement, state: queued
- [ ] T4: run `make sonar` automatically after a merge to master. The pass
      found this project had not been analysed since 2026-08-10, so every line
      number in the dashboard described a tree a month stale, and that nearly
      produced a dismissal justifying the wrong function. MUST NOT be a
      blocking gate and must never fail a build: the standards are explicit
      that a scan which can fail a build creates pressure to make the number
      green rather than the code better, state: queued
- [ ] T5: issue #312, event wiring is guarded in one direction only.
      `test_event_wiring.py` catches an event fired with no listener, and
      nothing catches a listener with no sender, which is the direction that
      has actually cost this project. 38 registered names are never fired.
      Deliverable is the reverse guard plus an adjudication of the 38, with an
      allowlist that fails in both directions so it cannot become a dumping
      ground. Confirmed dead so far: `movie.snatched` and `movie.downloaded`
      (no notification on grab or completion), `media.mark_watched`, and
      `app.test`, which has four listeners including a 12-case path-safety
      table for `isSubFolder` that has not run since the FastAPI migration,
      state: queued (needs: T1)
- [ ] T6: issue #311, the Trakt OAuth device flow has no reachable UI.
      `automation.trakt.device_code` and `automation.trakt.poll_token` are
      registered API views whose only caller is `trakt.js`, which nothing
      serves. Anyone configuring Trakt today cannot complete authorisation.
      Port the control into `couchpotato/ui/`, or retire the endpoints if the
      feature is not wanted, state: queued (needs: T6)
- [ ] T7: issue #314, the folder browser announces `role="listbox"` and keeps
      none of it: no arrow keys, no `aria-selected`, no
      `aria-activedescendant`, every folder its own tab stop. Remove the ARIA
      rather than adopt the `<select>` the scanner suggested. Fold in the
      known keyboard-escape and focus-trap gap in the same modal, and consider
      the eight deferred `Web:S6819` dialog findings here since a native
      `<dialog>` solves that half properly, state: queued (needs: T4)
- [ ] T8: five films identified earlier today that are still not added to the
      library. Data task, no PR, state: queued (needs: T5)

## Conductor log
