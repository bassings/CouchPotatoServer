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
- [ ] T3: assess and fix `python:S9073`, composite assertions in tests (59).
      Splitting them gives better failure messages, which this repo has needed
      repeatedly today, state: queued (needs: T2)
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
      2. The rule's premise does not hold for this code. S7740 exists because
         arrow functions capture `this` lexically, making the alias
         unnecessary. These files contain zero arrow functions. Many sites are
         provably necessary even so: `trakt.js:133` aliases `this` and then
         reads `self` inside an `Api.request` callback, where ES5 `this` would
         be wrong. A heuristic pass suggested a large share might be
         technically redundant, but spot-checking showed the heuristic itself
         was wrong on its first three candidates, so no split is recorded
         here. The verdict is the same at either extreme.
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
      as finding 144. Expiry: delete each file when its port lands
      (UI-CLEANUP-02), which retires these findings without editing dead code.
      state: merged
- [ ] T5: assess and fix `python:S1192`, duplicated string literals (72), where
      extraction aids clarity rather than just satisfying the rule, state:
      queued (needs: T4)
- [ ] T6: assess `Web:S6819`, ARIA role where a semantic tag exists (44). Real
      accessibility, same family as A11Y-001, state: queued (needs: T5)
- [ ] T7: assess `python:S1172`, unused function parameters (25). Some will be
      interface contracts that must stay; expect a split verdict, state:
      queued (needs: T6)
- [ ] T8: adjudicate `python:S1542` naming convention (70) and
      `python:S3776` cognitive complexity (139) WITHOUT bulk-fixing either.
      S3776 concentrates in the renamer and scanner, which have destroyed or
      nearly destroyed data three times in one session; restructuring them to
      satisfy a metric is the trade the standards warn against. Deliverable is
      a recorded decision per cluster, not a diff, state: queued (needs: T7)
- [ ] T9: re-scan, and record the honest before/after with what was fixed,
      dismissed and deliberately left open, state: queued (needs: T8)

## Conductor log

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
