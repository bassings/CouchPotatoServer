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
- [x] T2: assess the ~251 MEDIUM+ findings in the rules the first pass never
      reached, HIGH first: `javascript:S3776` (7), `python:S1186` (6),
      `python:S8904` (6), `python:S5779` (5), `Web:S7927` (3),
      `python:S1143` (2), `python:S5996` (2), `python:S5797` (2), and the
      singletons `javascript:S4275`, `python:S8415`, `javascript:S3735`,
      `python:S8520`, `typescript:S5845`, `python:S5727`, `python:S6903`.
      Then the MEDIUM-only remainder. Same discipline as the first pass: assess
      before fixing, fix what should be fixed, leave the rest open with a
      recorded reason and an expiry, dismiss only genuine false positives,
      state: DONE, every MEDIUM+ finding now has a recorded disposition
      PROGRESS. COUNT CORRECTED after review: the BLOCKER is its own
      severity, not one of the 15 HIGH rules, and counting it as one made
      every tally here off by one. Two produced production
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
      - `python:S8904` (6): SUPERSEDED BY WORK THAT ALREADY EXISTED, and my
        first verdict here was wrong in the same way twice over.
        I assessed ONE site, `filmweb.py`, found it contained by the API
        dispatcher, and extrapolated "real but contained" to all six. Two
        errors. The six do not share a route: `filmweb.py` and
        `filmstarts.py` reach the caller through `userscript.add_via_url`,
        which is wrapped, but `awesomehd.py` goes through the searcher and is
        not. And a proper per-site assessment ALREADY EXISTED at
        `specs/REMEDIATION-2026-08.md:1643-1679`, which I never looked for
        before writing a worse one.
        That assessment is the record. It checked each site: THREE are real
        and unguarded (`awesomehd.py:40`, `filmweb.py:25`,
        `filmstarts.py:26`), two are guarded by an enclosing condition the
        rule did not follow (`awesomehd.py:37`, `bithdtv.py:83`), and one is
        tolerated because its own try/except leaves the parse continuing
        (`thepiratebay.py:71`). It also found a site the scan never flagged,
        `filmstarts.py:21`, taking `table` from an unguarded `find` two lines
        above. Its impact call is the right one: these are provider scrapers
        parsing a third party's markup, and the searcher tolerates a provider
        raising, so the blast radius is a dead provider rather than a crashed
        scan. Critical by rule, not urgent by impact.
        THE PROCESS LESSON, which cost more than the finding: grep `specs/`
        for a rule ID before assessing it. This is the second time today I
        assessed one instance and generalised to the rule; the first was
        claiming `movie.snatched` and `movie.downloaded` were dead.

      - `python:S5797` (2): NOISE. `while True and not self.shuttingDown()` is
        provably identical to `while not self.shuttingDown()`. Redundant rather
        than wrong, and the file is `folder_scanner.py`, which has a bad
        history, so a no-op edit there buys nothing.
      - `python:S1143` (2): REAL SMELL, NOT A CRASH. A `return` inside
        `finally` in `synology.py` swallows in-flight exceptions including
        KeyboardInterrupt. I suspected an UnboundLocalError on the error path
        and checked: `response` is initialised before the `try` in both cases,
        so there is no crash. Worth tidying, not urgent.
      ALL 15 HIGH RULES NOW ASSESSED. CORRECTED after review: an earlier
      version of this line claimed that while listing only FOURTEEN. The
      missing one was `javascript:S3776`, which is the LARGEST HIGH rule by
      count, so the claim of completeness was wrong in the least excusable
      direction. Assessed below rather than quietly renumbering.
      - `javascript:S3776` (7): SPLIT. Three are in the unserved legacy layer
        (`movie.js:188`, `list.js:648`, `wizard.js:117`) and take T4's
        disposition. Four are in the LIVE new UI:
        `settings/scripts.html:231, :293, :423` at complexity 19, 29 and 17,
        and `wizard.html:1168` at complexity 94.
        Same verdict as `python:S3776` in the previous plan, and for the same
        reason: the metric is an accurate risk map and its implied remedy,
        restructure until the number falls, is the wrong response. The
        difference here is that the live four have real E2E coverage, including
        the wizard label tests added earlier today, so an extraction driven by
        a genuine need could be verified rather than hoped at. The 94 in the
        first-run wizard is the one to look at first if anyone does.
      The remaining nine:
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
      MEDIUM TAIL STARTED. Re-scanned first against `30fad16b0`, because the
      previous scan's line numbers no longer matched `variable.py` after three
      merges to it, which is the staleness trap recorded earlier today.
      Fresh totals: 1127 open, ZERO blockers, 441 MEDIUM of which 230 are in
      rules already judged at HIGH and 211 are not (46 in the three clusters
      below, 165 in the remaining 43 rules). An earlier draft said 210, which
      did not reconcile against the dispositions; re-counted from the scan.
      - Accessibility cluster, `Web:S6850` (7), `Web:S6853` (4), `Web:S6847`
        (4): ALL 15 ARE STATIC FALSE POSITIVES, and the reason is uniform. The
        analyser cannot evaluate an Alpine binding. `wizard.html:314` reports a
        label pointing at nothing, but the input at `:334` carries
        `:id="'wizard-tracker-' + tracker.id + '-' + field.name"`, the exact
        expression the label's `:for` binds to; that is the one bound pair
        among the 61 labels fixed in A11Y-001. All four `S6847` sites are
        `onerror` on an `<img>`, falling back to a placeholder poster, and the
        rule is about mouse and keyboard handlers on non-interactive elements,
        which a resource-load event is not.
        BUT THE HEADINGS CARRY A REAL QUESTION the static rule only gestures
        at. Four are safe: two are ternaries always yielding a literal, two
        have explicit fallbacks. Three have none: `combined_basics_card.html:7`
        (`group.label`), `:13` (`subGroup._subLabel`, an underscore-prefixed
        internal field) and `settings.html:50`. If that data is ever missing
        the heading renders EMPTY, which a screen reader announces as a heading
        with no text. Whether it is reachable depends on the settings data
        shape. Worth a follow-up, not a blind fix.
        Note the correlation: these cluster in the settings templates, the
        surface #321 established has never been scanned.
      - `python:S8786` (15), super-linear regex: MEASURED rather than argued.
        Five are in `scripts/check_test_traps.py`, a dev script whose input is
        repo files. The production pair that matters is the identical
        `r'[^[]*\[([^]]*)\]'` in `scores.py` and `searcher/main.py`, applied
        to PROVIDER-SUPPLIED release names. Timed: an ordinary name is 0.00ms,
        8000 unclosed brackets 124ms, 16000 of them 496ms. Growth is
        QUADRATIC, not exponential, so the rule is right that it is
        super-linear and wrong that it is catastrophic.
        CORRECTED after review, and the correction matters: I measured ONE
        call and reasoned from it, but `sceneScore()` runs PER CANDIDATE
        (`score/main.py:66`), and a provider controls BOTH the number of
        results and the length of each name. So the exposure is the aggregate,
        not the single call. Measured over one search response:
        100 results x 8000-char names is 13.9 SECONDS; 200 x 8000 is 27.5s.
        100 results with ordinary names is 0.0000s.
        My "needs a ~100KB name" framing understated it. You do not need one
        enormous name, you need a hundred unremarkable-looking 8KB ones, which
        is both more plausible and less conspicuous. That moves this from
        "fix opportunistically" to WORTH FIXING. The fix is unchanged and
        still cheap: a length cap on release names, far above any legitimate
        one, costs nothing because realistic responses measure zero.
      - `python:S8905` (16), BeautifulSoup with no parser: REAL BUT MITIGATED.
        `lxml==6.1.2` is pinned in `requirements.txt` and the same file builds
        the image, so the parser is deterministic today. The risk is a silent
        one: if lxml ever fails to build on Alpine, BeautifulSoup falls back to
        `html.parser`, which parses malformed provider HTML differently, with
        no error. Naming the parser explicitly is a no-op today and converts
        that silent change into an immediate failure. Cheap, worth doing.
      MEDIUM TAIL CLOSED OUT. The remaining 165 findings in 43 rules now have
      a recorded disposition rather than the group judgement of "style and
      idiom", which was defensible triage but not closure: it left nothing
      saying WHY each was not acted on, so the next session would re-derive it.
      Where they live decides most of it:
      - 74 are in `tests/` or `scripts/`. LEFT OPEN. `typescript:S9332` (22,
        networkidle waits) is the same family as the S2925 fixed waits already
        fixed in the first plan and deserves the same treatment when someone is
        next in those specs. `python:S5778` (14), `python:S8997` (8, manual
        global state where monkeypatch exists) and `python:S9081` (7) are real
        pytest idiom improvements with no production reach.
      - 17 are in the unserved legacy layer under `core/**/static/`. LEFT OPEN
        with T4's expiry from the previous plan: they retire when the files are
        deleted as each port lands, not by editing dead 2015 JavaScript.
      - The remaining ~74 are production, and two rules are genuine bug classes
        rather than style. Both were checked at every site.
      `python:S1515` (13): LATENT BUG, FIX RECOMMENDED, harmless today.
        `media/_base/media/main.py:454, :544, :783-785, :793` register API views
        inside `for media_type in fireEvent(MEDIA_TYPES, merge=True)` using
        `lambda *args, **kwargs: self.listView(type=media_type, **kwargs)`.
        Each lambda captures `media_type` BY REFERENCE, so every view would
        resolve to the LAST value. Measured why it does not bite: only 'movie'
        is ever declared as a media type (`media/movie/__init__.py:6` and
        `movie/_base/main.py:94`; base classes declare None), so every iteration
        binds the same value.
        TRIGGER CONDITION: adding a second media type activates it silently.
        CORRECTED AFTER REVIEW, and the correction lowers the priority. I wrote
        that `%s.delete` would route a show delete to movies. That is FALSE on
        two counts: the route KEY is formatted per iteration, so `show.delete`
        registers under the right name, and `deleteView(self, id='', **kwargs)`
        at `media/main.py:633` takes `type` into `**kwargs` and NEVER READS IT,
        deleting by id directly. So this closure cannot cause a cross-type
        delete and there is no data-loss path here.
        What it does affect is every callback that DOES consume `type`: list,
        character and watch-history filtering would silently filter by the
        wrong media type. A wrong-results bug, not a destructive one. Still
        worth the one-token fix, since binding it as a default argument costs
        nothing and changes no behaviour today, but not for the reason I first
        gave. This is the second time in this session I overstated a data-loss
        risk without following the argument into the function that receives it.
        The three at `renamer/main.py:801` are a different shape and benign: the
        callback is invoked within the same call rather than outliving its
        iteration.
      `python:S1871` (4 production), identical branches, the copy-paste
        signature. Checked: `folder_scanner.py:829` is two branches with the
        same body that could merge with `or`, behaviour-neutral, in a file with
        a bad history where a no-op edit buys nothing. LEFT OPEN.
      - The rest is idiom with no defect behind it. Grouped by family rather
        than listed one by one, because the reason and the expiry really are
        shared within each family; a per-finding restatement would be padding,
        not rigour:
        `python:S5806` (14) builtin shadowing, and `python:S1110` (12)
          redundant parentheses. Pure readability, no behaviour. EXPIRES when
          a formatter or lint rule is adopted that enforces either, at which
          point they are fixed mechanically rather than by hand.
        `python:S3358` (5) and `javascript:S3358` (2 production) nested
          ternaries, `python:S1066` (3) collapsible ifs, `python:S8519` (4)
          `list(...)[0]`, `python:S6395` (3), `python:S8517` (2),
          `python:S3457` (2), `python:S6035` (2), `Web:S1827` (2). Local
          rewrites with no caller-visible effect. EXPIRES when someone is
          editing the enclosing function for another reason; doing them
          standalone means touching working code for no behavioural gain.
        `python:S112` (2) generic exceptions raised, `python:S125` (1)
          commented-out code, `python:S1045` (1), `python:S1854` (1) dead
          store, `python:S8513` (1), `python:S8900` (1), `Web:S5254`,
          `Web:S6821`, `Web:S6845`, `Web:S6807` (1 each). Singletons, each
          genuine and each trivial. EXPIRES on the same condition: fix in
          passing, not as a sweep.
      - `Web:PageWithoutTitleCheck` (1) is a FALSE POSITIVE, the same Jinja
        blind spot as the Alpine ones: `base.html:6` is
        `<title>{% block title %}CouchPotato{% endblock %}</title>` and child
        templates override it.
      NOTHING IN THE MEDIUM TAIL IS A LIVE DEFECT. That is the honest result and
      it differs sharply from the HIGH set, which yielded four production bugs
      from a comparable number of findings. Severity ranking earned its keep.
      NET: of 15 HIGH rules, TWO produced production fixes: `python:S5996`
      via #320 and `Web:S7927` via #322. NOT `Web:S6853`, which is the label
      `for`/`id` association rule, assessed in the MEDIUM tail above as a
      static false positive and never touched. I introduced that conflation
      IN THE EDIT THAT WAS FIXING THE PREVIOUS MISCOUNT, which is the third
      tally error in this one entry. CORRECTED after review, for the SECOND
      time in this plan: I counted `python:S3516` as a third,
      but it is a BLOCKER, a separate severity, and its change added tests
      rather than fixing code. Folding the blocker into the HIGH tally is the
      same category error the reviewer caught earlier, made again. (The S5996
      fix then needed two further rounds: a caller-shape miss and a
      `localhost` substring hole of exactly the class it had just closed), 1
      was rejected
      because complying would risk a regression, 1 was moot, and the rest are
      real-but-low-value or blocked on something else.
      The MEDIUM tail that this line once pointed forward to is closed out
      above, in the MEDIUM TAIL CLOSED OUT block. Nothing in T2 is outstanding.
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
- [~] T3: production promotion. REMOVED FROM THIS PLAN by the owner's
      decision, 2026-09-08. Not cancelled and not completed: the fourteen
      commits merged since v3.77.0 remain unreleased, including BUG-018, where
      the scanner filed every remake under the original film, and the Docker
      CVE pin. It will be released separately rather than as a task of this
      plan, and nothing else here depends on it.
      The corrected procedure is preserved below because it was wrong in three
      ways in the first draft and the corrections are the useful part:
      `./scripts/backup.sh --retain 14`, NOT the bare form, or every promotion
      adds another full database copy to the volume holding the live database
      (`docs/development-process.md:751-756`). Verify the snapshot with `PRAGMA
      integrity_check` printing `ok`, `PRAGMA foreign_key_check` returning NO
      rows, and a readable `config.ini`, because `backup.sh` warns and exits 0
      when settings are absent, so both PRAGMAs can pass on a snapshot with no
      settings in it (`docs/development-process.md:758-775`). Capture BOTH `docker inspect couchpotato
      --format '{{.Config.Image}} {{.Image}}'` and `docker exec couchpotato cat
      /app/version.py` BEFORE anything moves, since the host pulls `:latest`
      and the old target cannot be reconstructed afterwards (`docs/development-process.md:390-418`, the digest capture is at `:408-418`). Not
      `printenv CP_VERSION`, an ARG rather than an ENV and absent from the
      running container, and never a grep for /version/i, which hands you the
      interpreter version as a plausible rollback tag mid-incident.
      state: removed from this plan, released separately
- [x] T4: make SonarQube staleness visible. DONE, merged as #328. REFRAMED AFTER REVIEW, because the
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
      state: merged #328

- [~] T5: IN PROGRESS on `fix/T5-event-wiring-reverse-guard`. Issue #312, event wiring is guarded in one direction only.
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
- [x] T6: DONE, merged as #333. Issue #311, the Trakt OAuth device flow has no reachable UI.
      `automation.trakt.device_code` and `automation.trakt.poll_token` are
      registered API views whose only caller is `trakt.js`, which nothing
      serves. Anyone configuring Trakt today cannot complete authorisation.
      Port the control into `couchpotato/ui/`, or retire the endpoints if the
      feature is not wanted.
      BUILT AS A BESPOKE PARTIAL, not a mode on the shared `buttonField`
      helper: that helper is single-shot (fetch, show a message, refresh) and
      this flow needs a start call followed by a bounded poll loop with its
      own expiry and a waiting state in between.
      The `needs: T5` this entry carried is DROPPED, and it was never real.
      T5 is a test guard over event wiring and has no bearing on whether a
      settings control can be built. I worked T6 first without noticing the
      plan said I could not, so the order was right and the declaration was
      wrong. Second phantom dependency in this plan after T7's, both written
      down and never checked.
      state: merged #333
- [x] T7: DONE, merged as #329. Issue #314, the folder browser announced `role="listbox"` and keeps
      none of it: no arrow keys, no `aria-selected`, no
      `aria-activedescendant`, every folder its own tab stop. Remove the ARIA
      rather than adopt the `<select>` the scanner suggested. Fold in the
      known keyboard-escape and focus-trap gap in the same modal, and consider
      the eight deferred `Web:S6819` dialog findings here since a native
      `<dialog>` solves that half properly.
      CORRECTED: this entry claimed the
      modal has no keyboard escape and no focus trap. It has BOTH,
      `modals.html:53` closes on Escape and `:55-66` is a working focus trap
      with shift-tab cycling. That claim came from a summary carried into the
      session and was repeated without opening the file.
      The `needs: T6` this entry carried is dropped: T7 merged as #329 while T6
      was still open, so the dependency was never real.
      state: merged #329
- [ ] T8: five films identified earlier today that are still not added to the
      library. Data task, no PR, state: queued (needs: T7)

## Conductor log

- 2026-09-09 T6 merged as #333 after the owner chose to restructure rather
  than land with each variant guarded. The restructure replaced five pieces
  of state, each needing to be correct at six suspension points, with one run
  token. Evidence it is structural rather than a better guard: reintroducing
  the exact defect that broke the old code, the flag claimed after the await,
  now leaves the double-click test passing. A late review round then found a
  real bypass of the verification-URL host pin: no slash before a query
  string meant `https://evil.example?x=fake.trakt.tv` computed a host ending
  in `.trakt.tv` and was returned unchanged. Fixed with a real URL parser.
- 2026-09-09 A `status: blocked-on-human` marker was committed to this file
  by accident: it was written onto the Trakt branch and merged with it, so
  the hourly status alert reported the plan as awaiting a decision that had
  already been made and acted on. The marker is a working-copy device and
  must not be committed. Noticed by the owner from the alert, not by me.


- 2026-09-08 T2/T4/T7 closeout merged as #331. Five review findings, all mine,
  the largest being a data-loss claim that was not one: `deleteView` takes
  `type` into `**kwargs` and never reads it, so the late-bound closure cannot
  route a show deletion to movies. It is a wrong-results bug in list and
  watch-history filtering. Merge was blocked with every check green because
  `master` requires review threads to be RESOLVED, not merely replied to,
  which surfaces only as `BLOCKED` with no reason.
- 2026-09-08 T6 built, then two review passes on the branch, run in parallel
  and independently. Both found the same top defect by different routes: the
  poll loop outlived the component that owned it, so switching settings tabs
  mid-authorisation and clicking Start again ran two loops, and when the user
  finished authorising, one consumed the code and the other reported "no
  device code" into the visible status. The user was told authorisation had
  failed at the moment it succeeded.
- 2026-09-08 The more valuable finding was that the tests could not SEE that
  defect. Setting the code box to never display, so no user could ever read
  the code they are told to type in, left all seven specs passing, including
  the one named "displays the code and URL". Assertions read `textContent`,
  which is present while hidden, and the accessibility scan skips hidden
  subtrees, so "zero violations" had quietly become "nothing was scanned".
- 2026-09-08 Three fix rounds on T6, which is the circuit-breaker limit, so
  the last two items were finished directly rather than dispatched a fourth
  time. Round two's teardown looked complete and closed half the hole: a
  request already in flight still resolved on the destroyed component and
  restarted the chain. Proven by restoring round two's version verbatim, at
  which point the navigate-away test passes and the in-flight test fails with
  Expected 2, Received 4.
- 2026-09-08 One item cut from T6's scope and raised as #332 instead: four
  copies of a lookup on `__x_panel`, which is read four times in the whole
  repository and written zero times, so the walk always fails and the
  fallback always fires. Real, but pre-existing, working today, and not this
  branch's code.
- 2026-09-08 T8 cannot proceed as written: it names five films and records
  none of their titles, and they appear nowhere in the repository. Blocked on
  the owner for the list rather than on any work.
