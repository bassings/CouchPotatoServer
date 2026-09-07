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
      something enforceable rather than an argument. The project now has ZERO
      blockers. state: merged #319
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
      PROGRESS, 6 of the 15 HIGH rules assessed. Two produced production
      fixes, four produced evidenced "real but not worth acting on" verdicts.
      - `python:S3516` (1, BLOCKER): FALSE POSITIVE, dismissed, and the guard
        that makes the dismissal safe landed first as #319. Zero blockers now.
      - `python:S5996` (2): FIXED as #320, and it was THREE bugs rather than
        the one reported. See T2b.
      - `Web:S7927` (3): FIXED as #322. Real WCAG 2.5.3 failures in the live
        settings UI. The bigger finding is #321: the settings accessibility
        scan only ever sees the ACTIVE tab, because `settings.html` renders
        only `currentGroups`, so an unclicked tab contributes NO DOM at all.
        Measured: the axe rule against the page as loaded reports 0
        violations; after clicking to the Library tab it immediately flags a
        real failure that had been sitting there. Most of the settings surface
        has never been scanned by anything.
      - `python:S8904` (6): REAL BUT CONTAINED, not worth a PR on its own. A
        `.find(...)` returning None would raise, and in `filmweb.py:26` the
        try/except covers only the fetch, so it does propagate. But the path is
        live only via `userscript.add_via_url`, whose caller
        (`ui/__init__.py:405`) wraps it AND `callApiHandler` already catches
        every handler exception. So the user sees "Failed getting movie info"
        rather than anything breaking. The only real cost is a traceback in the
        log instead of a useful line. I first flagged these as crash risks;
        that was too alarming and the correction is recorded rather than
        quietly dropped. Fix opportunistically when next in those files.
      - `python:S5797` (2): NOISE. `while True and not self.shuttingDown()` is
        provably identical to `while not self.shuttingDown()`. Redundant rather
        than wrong, and the file is `folder_scanner.py`, which has a bad
        history, so a no-op edit there buys nothing.
      - `python:S1143` (2): REAL SMELL, NOT A CRASH. A `return` inside
        `finally` in `synology.py` swallows in-flight exceptions including
        KeyboardInterrupt. I suspected an UnboundLocalError on the error path
        and checked: `response` is initialised before the `try` in both cases,
        so there is no crash. Worth tidying, not urgent.
      ALL 15 HIGH RULES NOW ASSESSED. The remaining nine:
      - `python:S1186` (6): base-class stubs, `buildUrl`, `search`, `doUpdate`,
        `getFiles`, all meant to be overridden. The rule wants a comment
        explaining the emptiness, which is fair and cosmetic. Fix when next in
        those files.
      - `python:S5779` (5): three are in `couchpotato/simple_healthcheck.py`, a
        PYTHON 2 unittest module shipped inside the application package,
        referenced by nothing, while the real Docker healthcheck is an inline
        urllib one-liner (`Dockerfile:155`). Deleting it looks obvious and is
        BLOCKED: an earlier session recorded that it is the only referrer to a
        deprecated endpoint and its removal waits on AC-OPS-12's production
        grep. So the actionable item is that grep, not the deletion. One is in
        a test. The last, `browser.py:158`, uses `assert` as control flow,
        which would vanish under `python -O` and report every Windows file as
        hidden. I called that a live bug; it is not. There is no `-O` anywhere
        in the Dockerfile, compose files or Makefile, so it is latent only.
      - `javascript:S3735` (1): REJECT, and complying would risk a real
        regression. `suggestions.html:214` is `void el.offsetHeight;` with the
        comment "force the pending style/layout flush". That is the canonical
        idiom for forcing a synchronous reflow before a transition, and the
        `void` is what stops a minifier discarding an apparently useless
        property read. The rule is wrong here.
      - `python:S8415` (1): MOOT. It asks for a 403 to be documented in the
        `responses` parameter, but `couchpotato/__init__.py:1208` constructs
        `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`, so no
        schema is served at all. The parameter would document something nobody
        can fetch.
      - `typescript:S5845` (1): REAL, but it points at the wrong file. The test
        at `category-editor.spec.ts:90` asserts `form.id` is numeric `0`, which
        is correct: `category-editor.js:30` uses `?? ''` DELIBERATELY so a
        numeric `_id=0` survives. The JSDoc at `:24` says `id: string`, and
        that is the lie. Fix the annotation, not the test.
      - `python:S6903` (1): REAL and dated. `putio/main.py:99` uses
        `datetime.utcnow()`, deprecated on Python 3.12+ and this project runs
        3.14. It currently works, since both sides of the comparison are naive
        UTC, but it is on a removal path.
      - `python:S8520` (1): correct but tiny. `sum(..., [])` to flatten
        subtitle languages is quadratic over a handful of items.
      - `python:S5727` (1): `itunes.py:44` checks `data is not None` after
        `XMLTree.fromstring`, which never returns None, so it is always true.
        It is also the documented ElementTree idiom, since Elements have
        deprecated truthiness. Defensive rather than wrong. Low value.
      - `javascript:S4275` (1): in `updater.js`, the unserved legacy layer.
        Same disposition as T4's 143 findings.
      NET: of 15 HIGH rules, 3 produced production fixes, 1 was rejected
      because complying would risk a regression, 1 was moot, and the rest are
      real-but-low-value or blocked on something else. Next: the MEDIUM tail.
- [x] T2b: `isLocalIP()` recognises neither IPv6 loopback form. RAISED IN
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
      service is disabled where `127.0.0.1` would not be.
      FIX ROUND 2, because review found the first fix does not fix the bug.
      `http_client.py:203` passes `hostname:port`, not a bare address, so
      `http://[::1]:9117/api` yields `::1:9117` and the end-anchored IPv6
      alternatives never match. That is the common shape, since a self-hosted
      local service almost always has an explicit port. All 15 tests passed
      because every one used a hand-written bare address, so the suite was
      green while the real path stayed broken. Knowing where the boundary was
      did not help; nothing tested ACROSS it. MERGED as #320 after two rounds. Round two found a THIRD bug while
      writing the required must-stay-False cases: the IPv4 alternatives were
      only start-anchored, so `127.0.0.1.evil.com`, a registerable domain, was
      classified as LOCAL. That predates all of this and no scanner reported
      it. Verified on master across 25 cases including the caller shape.
      state: merged #320
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
