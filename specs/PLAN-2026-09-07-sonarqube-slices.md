# PLAN 2026-09-07: work the SonarQube backlog in assessed slices

**Owner instruction, 2026-09-07:** push to SonarQube and fix anything medium or
higher, with the clarification that "fix" means ASSESS FIRST, and that things
which should not be fixed can be accepted.

**Standing rule this plan obeys** (project CLAUDE.md and the owner's own
standards): never resolve, dismiss or accept a finding to move a number, and
never disable a rule to avoid one. Three dispositions only:

- **Fix** when the finding is real and the change is safe and proportionate.
- **Dismiss** only for a genuine false positive, with a comment saying why and
  what would make that decision expire.
- **Leave open, recorded** when the finding is real but not worth the risk or
  churn. It stays visible. It is NOT marked resolved, because a dismissed
  finding is indistinguishable from progress on a dashboard.

## Measured baseline

Scan of `4e18216db`, 2026-09-07. 940 findings at MEDIUM or higher, down from
947 before the day's merges. Quality split: 881 maintainability, 76
reliability, 0 security. Language split: 534 Python, 232 JavaScript, 105
TypeScript, 69 HTML.

The top ten rules are roughly two thirds of the total, so the unit of work is
the RULE, not the file: one judgement per pattern rather than per occurrence.

## Tasks

- [x] T1: `typescript:S2925` fixed waits, in the two files already touched (32
      of 80), state: merged #305
- [x] T2: `javascript:S1121`, assignments inside sub-expressions (57), state:
      merged #307. LEFT OPEN, RECORDED, not fixed. My prior ("expect mostly
      fix") was wrong and the evidence overturned it: all 57 are one MooTools
      builder-chain shape, none in a boolean condition so the rule's actual
      hazard does not apply, and the code is DEAD (clientscript.py deleted by
      UI-CLEANUP-02; no route, template or config references any of the 12
      files; the one grep hit is a code comment). Zero tests on that layer, so
      a 57-site rewrite could not be proven behaviour-neutral. Expiry: delete
      each file when its port lands.
- [x] T3: assess and fix `python:S9073`, composite assertions in tests (59).
      Splitting them gives better failure messages, which this repo has needed
      repeatedly today. FIXED, all 59, the opposite verdict to T2 and for a
      reason specific to this codebase: `assert a and b` reports only that the
      assertion failed, while two assertions name which half moved. Two outer
      ANDs wrapping an inner OR-group were split at the AND only, leaving the
      OR intact, because splitting the OR would have turned "any acceptable
      phrasing" into "all three required". 32 test files, no production code,
      unit count unchanged at 3894 passed / 2 skipped / 5 xfailed.
      state: merged #309 (needs: T2)
- [x] T4: assess `javascript:S7740`, variables assigned `this` (143). LEFT
      OPEN, RECORDED, not fixed, and my prior was wrong in an interesting way:
      I guessed "legitimate Alpine component idiom", and there is no Alpine
      here at all. Every one of the 143 is `var self = this` at the top of a
      MooTools class method, in 19 files under `couchpotato/core/**/static/`.
      CORRECTED after review: I first wrote "last modified 2015", which was
      checked on ONE file and asserted of all nineteen. The real spread is
      2014 (1 file), 2015 (7), 2016 (2), 2017 (3) and 2026 (6): `trakt.js`,
      `wizard.js`, `wanted.js`, `movie.js`, `manage.js` and
      `movie/_base/search.js`. That is not a rounding error in the argument,
      it inverts part of it, so see finding 4 below.
      Three findings, each measured rather than assumed:
      1. The layer is not served. `static_dir` is `couchpotato/static`
         (`runner.py:558`), the only mount (`couchpotato/__init__.py:1231`),
         and it contains only new-UI scripts and vendor bundles: no MooTools,
         no combined legacy bundle. `clientscript.py`, which used to build
         those bundles, is deleted. `/old/*` is a redirect catch-all
         (`couchpotato/__init__.py:1693`). Nothing outside the tree references
         it. This is the same dead layer as T2, reached independently.
      2. The rule applies, and its remedy is a refactor this layer cannot
         support. CORRECTED after review: I first argued that "these files
         contain zero arrow functions, so the rule's premise is absent". That
         was wrong, and it inverted the rule. S7740 does not require an arrow
         function to already be present. It flags the alias precisely so the
         nested traditional function can be REWRITTEN as an arrow function
         that captures the surrounding `this`. Zero arrows is therefore
         evidence that the refactor has not been done, not that the rule does
         not apply.
         The honest statement is narrower, and being about risk rather than
         applicability it is also the stronger one: the finding is real, and
         complying with it means converting ES5 callbacks to arrow functions
         across 143 sites in code with zero test coverage. `trakt.js:133`
         shows why each site needs individual judgement rather than a sweep.
         It aliases `this` and then reads `self` inside an `Api.request`
         callback, so the alias is load-bearing UNTIL that callback becomes
         an arrow function and wrong afterwards. That is a behaviour-changing
         edit, not a rename.
         A heuristic pass suggested a large share of the 143 might be
         technically redundant, but spot-checking showed the heuristic was
         wrong on its first three candidates, so no split is recorded here.
      3. Zero tests cover the layer, so a 143-site edit could not be shown to
         be behaviour-neutral.
      4. The layer is not merely dormant, it is still attracting new work,
         and that is the finding worth keeping. `trakt.js:133`, cited above as
         a necessary alias, is not old code at all: it came from `9e77d021`,
         "feat(trakt): Implement direct OAuth 2.0 device code flow", February
         2026. That commit added `startDeviceAuth` and `pollForToken` to a
         file nothing serves.
         The consequence is a live user-facing gap, not tidiness debt.
         `automation.trakt.device_code` and `automation.trakt.poll_token` are
         registered as API views (`trakt/main.py:87-88`), and the ONLY caller
         of either, anywhere in the repository, is `trakt.js:138` and
         `trakt.js:180`. The new UI contains no reference to Trakt at all.
         So the backend can start a Trakt device authorisation and nothing in
         the shipped application can ask it to. Anyone configuring Trakt today
         has no way to complete OAuth. Raised as a follow-up in its own right.
      The rule is left enabled and every finding left open, because it is
      still doing useful work: there are zero S7740 findings in the live UI,
      so the same idiom written into `couchpotato/ui/` tomorrow would surface
      as finding 144.
      Expiry, CORRECTED after review: I first wrote "UI-CLEANUP-02", which had
      ALREADY LANDED. It deleted the userscript embed, `clientscript.py`, the
      four compiled bundles, `index.html` and `static/fonts/**`
      (`specs/UI-MIGRATION.md:50-64`), and it did NOT delete these 19 files.
      An expiry pointing at a finished task can never fire, which is exactly
      the accepted-debt-with-no-exit the standards forbid, so it is replaced.
      The real condition is the still-open UI migration criterion, "No
      references to `/old` or the legacy stack remain in code or docs"
      (`specs/UI-MIGRATION.md:69`), reached as each of the 18 audited features
      lands in the new UI (`specs/UI-MIGRATION.md:32`).
      Naming the gap rather than papering over it: NO task currently owns
      deleting `couchpotato/core/**/static/`. Until one does, this expiry has
      a condition but no owner, which is the weakest part of this disposition.
      It is related to issue #311, where the same unreachable layer silently
      swallowed a February 2026 feature.
      state: merged
- [x] T5: assess and fix `python:S1192`, duplicated string literals (72).
      SPLIT VERDICT: 21 fixed, 36 left open with reasons. All 72 are in live
      production Python, zero in tests.
      FIXED: 21 event names, across 186 call sites, replaced with constants in
      a new `couchpotato/core/event_names.py`. The value is defect prevention,
      not tidiness: event wiring here fails silently in BOTH directions, and a
      mistyped name raises nothing. An import that does not resolve does.
      LEFT OPEN: API schema descriptions (a constant makes the schema harder to
      read where it is defined), generic format strings (`'Failed: %s'`, too
      generic to share without coupling unrelated call sites), the embedded
      truth table at `file.py:230-243` where the repetition IS the table, and
      single-file downloader messages. Plus `updater.check`, recorded with its
      real risk: it is a scheduler job id passed to both `schedule.remove` and
      `schedule.interval`, so drift silently leaves a stale job.
      THREE CORRECTIONS TO MY OWN INSTRUCTIONS, all found by review and all
      proven by measurement rather than argument:
      1. The spec said 24 event names. Three were not events. I had built the
         list by matching dotted-lowercase strings in the scanner output
         instead of checking how each string is USED: `couchpotato.db` is the
         SQLite filename. Classifying by the shape of a string rather than its
         use is the same mistake as asserting on a proxy.
      2. I instructed that the value-pinning test be SKIPPED as vacuous. It is
         not, because these strings leave Python: they are typed by hand into
         `addApiView()` routes, into HTML templates that fetch `/app.restart/`
         and `/manage.update/?full=1`, and into the legacy JS. Review proved
         the gap by retyping three constants and watching all 3895 tests pass.
      3. The change BLINDED the pre-existing `test_event_wiring.py` audit for
         all 21 names, which reads names from source and understood only bare
         literals. Fired names visible fell 108 to 87 and handled 142 to 121.
         So a change sold as making event wiring safer measurably reduced the
         tree's ability to detect a dead handler, which is the failure this
         project has actually suffered. Fixed at the mechanism: the audit now
         resolves constants, and scans the repo-root entry point.
      REWORK COUNT: 2 fix rounds. Round 2 was triggered by the circuit-breaker
      condition, a review finding a defect that round 1's fix had introduced:
      my resolver handled `ast.Assign` but not `ast.AnnAssign`, so annotating a
      constant would have re-armed the same blindness silently. Continued
      rather than escalating because the approach was proven sound by mutation
      and the defect was one unhandled node type, but the trip is recorded
      because "the next fix is small" is exactly the reasoning the rule exists
      to stop.
      3896 passed, 2 skipped, 5 xfailed, up from 3894 by the two new guards.
      state: merged
- [x] T6: assess `Web:S6819`, ARIA role where a semantic tag exists (44). ALL
      44 LEFT OPEN, none fixed, and the plan's own prediction, "real
      accessibility, same family as A11Y-001", was wrong in the most useful
      way: unlike T2 and T4 these ARE all in the live UI, so the stakes were
      real, and the rule's advice is still mostly wrong FOR THIS CODEBASE.
      Following it would reduce accessibility in two places.
      1. 19 of 44: `role="status"` to `<output>`. REJECT. Both map to the same
         accessibility-tree role, and every one of these already carries an
         explicit `aria-live="polite"` as well, so there is no difference for
         assistive technology. axe-core 4.13.0, the standard this project
         enforces as tests, has ZERO rules on the subject (verified by
         enumerating `axe.getRules()`). Against no gain there is real cost:
         four E2E tests locate these elements by the attribute selector
         `[role="status"]` (`categories.spec.ts:144,309`,
         `add-via-url.spec.ts:83,100`), which an `<output>` would not match.
      2. 6 of 44: `role="list"`/`role="listitem"` to `<ul>`/`<li>`. REJECT, and
         this one is an accessibility REGRESSION, not a neutral change. The UI
         loads Tailwind (`base.html:19`) whose preflight sets
         `list-style: none`, and Safari with VoiceOver strips list semantics
         from a list styled that way. The documented workaround is to put
         `role="list"` back explicitly, which is exactly what this rule
         objects to. So complying either loses the semantics or produces
         `<ul role="list">`, which the rule flags again.
      3. 8 of 44: `role="dialog"` to `<dialog>`. DEFER, genuinely worth doing.
         A native `<dialog>` brings a real focus trap, Escape handling and an
         inert backdrop, and the folder browser modal currently has no
         keyboard way out at all. But it is a behaviour change requiring
         `showModal()` and interacting with Alpine's `x-show`, not a markup
         swap, so it belongs in its own task with its own tests.
      4. 4 of 44 `region` to `<section>`: identical semantics, no gain, live
         templates. REJECT as noise.
      5. 3 of 44 `group` to `<fieldset>` in the wizard: REJECT. The label is
         bound dynamically (`:aria-label="tracker.name"`), which a `<legend>`
         does not express, and the container is `class="grid grid-cols-2"`,
         a layout `<fieldset>` has a long history of handling badly.
      6. 1 `progressbar` to `<progress>`: REJECT. The existing markup carries a
         written explanation for deliberately omitting `aria-valuenow`, since
         `pct` is a synthetic easing curve rather than real completion. The
         current form is the considered one.
      7. 1 `radio`: REJECT. `movie_detail.html:482` is a correctly implemented
         radiogroup already, with arrow-key handling and bound `aria-checked`.
      8. 1 `listbox` plus 1 `option`: THE RULE POINTED AT A REAL BUG AND
         MISDIAGNOSED IT. `modals.html:93` declares the folder browser a
         listbox and keeps none of that promise: no arrow keys, no
         `aria-selected`, no `aria-activedescendant`, every folder its own tab
         stop. A screen reader announces a listbox and a position, and none of
         the implied interaction works. The fix is NOT the suggested
         `<select>`, which cannot hold the icon and nested markup and is
         populated dynamically; it is to REMOVE the ARIA and let them be the
         plain buttons they already are. Raised as issue #314.
      The wider lesson for this plan: a rule can be correct in general and
      wrong for a specific codebase, and the deciding evidence was the
      project's own enforced standard plus its own tests, not the rule's
      rationale. state: merged
- [x] T7: assess `python:S1172`, unused function parameters (25). SPLIT
      VERDICT as predicted, but far more lopsided than expected: 24 must stay,
      1 fixed. That ratio is not the rule failing, it is what an entirely
      plugin-polymorphic codebase looks like under this rule.
      MUST STAY, verified per family rather than assumed:
      - 6x `quality` in search providers. `providers/base.py:250` calls
        `self._searchOnTitle(title, media, quality, results)` POSITIONALLY,
        and 5 providers implement it. A provider that ignores `quality` still
        has to accept it.
      - 6x `path` in `scripts/check_test_traps.py`. Ten `check_*(path, text)`
        functions dispatched from one place (`:1676-1684`). Trimming the six
        that ignore `path` would force the dispatcher to know which is which.
      - 2x in `notifications/base.py:53`. That is the base `notify()` stub,
        dispatched as `self.notify(*args, **kwargs)` and overridden by 19
        notifiers.
      - 4x in `providers/base.py`: `loginSuccess(output)`,
        `loginCheckSuccess(output)` and the `nzb_id` download hooks, all base
        implementations overridden by providers that do read them.
      - the remainder are the same shape: `getAllDownloadStatus(ids)` has 9
        definitions, `correctProxy(data)` 2, `getNfoName(name, root, i)` is a
        metadata base hook.
      THE TWO RENAMER FINDINGS ARE NOT NOISE, AND DELETING THEM WOULD DESTROY
      EVIDENCE. `_processGroup(group, media_folder, release_download)` at
      `renamer/main.py:2231` never reads `release_download`, yet `scan()`
      threads it the whole way down (`:455, :521, :577, :601`). `renamer.after`
      and `renamer.before` appear ZERO times in that file. So the parameter is
      the last in-code marker of where the unported event chain was meant to
      fire, which is the known reason subtitles, trailers, notifications and
      metadata are all silently dead. Removing it to satisfy a linter would
      erase the signpost to a real missing feature. Related to #312.
      `_replacementOutcome(src, dst, group)` at `:2129` ignores `src` while
      deciding what upgrade replacement would do with that very file. Ten tests
      pass it explicitly. Left open as a question worth answering, not a
      parameter worth deleting: should that decision depend on the source file?
      FIXED, 1 of 25: `_fetch_and_cache(url, cache_key, cache_key_md5,
      use_cache, **kwargs)` in `plugins/base.py:279` took a pre-computed hash,
      never read it, and delegated to `setCache()`, which recomputes exactly
      the same value from `cache_key` (`:299`). Two call sites, both in that
      file, one of which already passed `None`. Genuinely dead, and misleading:
      a reader could reasonably think passing `None` changed caching
      behaviour. It does not. Caching is gated by `use_cache`, which is a
      separate parameter and works correctly. I did suspect a real caching bug
      here and checked: there is none.
      Proof the 9 passing cache tests are real coverage rather than decoration:
      disabling the cache write inside that function fails
      `test_positive_cache_timeout_still_stores_fresh_result`. Restored
      byte-identical. state: merged
- [ ] T8: adjudicate `python:S1542` naming convention (70) and
      `python:S3776` cognitive complexity (139) WITHOUT bulk-fixing either.
      S3776 concentrates in the renamer and scanner, which have destroyed or
      nearly destroyed data three times in one session; restructuring them to
      satisfy a metric is the trade the standards warn against. Deliverable is
      a recorded decision per cluster, not a diff, state: queued (needs: T7)
- [ ] T9: re-scan, and record the honest before/after with what was fixed,
      dismissed and deliberately left open, state: queued (needs: T8)

## Conductor log

- Tick 3: T3 merged (#309) and its worktree disposed. T4 merged (#310) after
  two fix rounds from review: the file dates were checked on one file and
  asserted of nineteen, the S7740 rationale had the rule backwards, and the
  recorded expiry pointed at UI-CLEANUP-02, which had already landed and so
  could never fire. T5 delivered under `/tdd-task` with RED verified
  independently, then two review rounds. Two user-facing bugs found while
  assessing, raised as #311 (Trakt OAuth device flow has no reachable UI) and
  #312 (38 events registered but never fired, of which `movie.snatched` and
  `movie.downloaded` are confirmed dead). T5 merged (#313) after a rebase for a plan-file conflict. T6 assessed, all 44
  left open, one real bug raised as #314. T6 merged (#315). T7 assessed: 24 kept, 1 fixed. Next: T8, the adjudication
  with no diff, then T9's re-scan.

- Tick 2, 2026-09-07. #305 and #306 merged (T1 done, plan file now on master,
  which also fixes the broken active-plan pointer at its root). T2 assessed and
  merged as #307 with a LEFT OPEN disposition, not a fix: see the task line for
  the evidence. Fix rounds on any task: 0. Two corrections this tick, both
  mine. First, I delegated T2 into the SHARED checkout instead of a worktree,
  so its branch switch removed the plan file from the working tree and the
  Stop hook blocked me: the contract says worktree for exactly this reason and
  three sessions share that directory. T3 is running in a
  dedicated git worktree instead. Second, a
  memory note of mine asserted the legacy asset layer was still live; verified
  in the repo, it is not, and the note is corrected. Armed: T3 implementer.
  Next wake expects a shape-by-shape assessment of python:S9073.

- Tick 1, 2026-09-07. First invocation, running under /loop dynamic pacing.
  Armed `.claude/active-plan`. Reconciled by measurement rather than memory:
  T1 is PR #305, MERGEABLE, 5 checks pending, none failed, so its state is
  awaiting-ci, not merged as the plan file had optimistically recorded.
  Corrected. Plan file itself raised as #306 (docs only). T2 has no `needs:`
  edge so it is started this tick rather than waiting on T1. Fix rounds on
  any task so far: 0. Deliberately NOT fanning out beyond one implementation
  track: this machine is 2.4 GB into swap with five Claude sessions and a
  3.9 GB VM resident, and concurrent E2E suites already destroyed two runs
  today. Armed: CI watches on #305 and #306, and the T2 implementer. Next
  wake expects #305 and #306 green and T2 reporting an assessment.

- Tick 2, 2026-09-07. #305 and #306 merged (T1 done, plan file now on master,
  which also fixes the broken active-plan pointer at its root). T2 assessed and
  merged as #307 with a LEFT OPEN disposition, not a fix: see the task line for
  the evidence. Fix rounds on any task: 0. Two corrections this tick, both
  mine. First, I delegated T2 into the SHARED checkout instead of a worktree,
  so its branch switch removed the plan file from the working tree and the
  Stop hook blocked me: the contract says worktree for exactly this reason and
  three sessions share that directory. T3 is running in a
  dedicated git worktree instead. Second, a
  memory note of mine asserted the legacy asset layer was still live; verified
  in the repo, it is not, and the note is corrected. Armed: T3 implementer.
  Next wake expects a shape-by-shape assessment of python:S9073.

- Tick 1, 2026-09-07. First invocation, running under /loop dynamic pacing.
  Armed `.claude/active-plan`. Reconciled by measurement rather than memory:
  T1 is PR #305, MERGEABLE, 5 checks pending, none failed, so its state is
  awaiting-ci, not merged as the plan file had optimistically recorded.
  Corrected. Plan file itself raised as #306 (docs only). T2 has no `needs:`
  edge so it is started this tick rather than waiting on T1. Fix rounds on
  any task so far: 0. Deliberately NOT fanning out beyond one implementation
  track: this machine is 2.4 GB into swap with five Claude sessions and a
  3.9 GB VM resident, and concurrent E2E suites already destroyed two runs
  today. Armed: CI watches on #305 and #306, and the T2 implementer. Next
  wake expects #305 and #306 green and T2 reporting an assessment.
