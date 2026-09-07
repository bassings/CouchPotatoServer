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
- [ ] T4: assess `javascript:S7740`, variables assigned `this` (143). Largest
      single rule. Suspect many are legitimate Alpine component idiom; the
      deliverable may be mostly a dismissal with evidence, state: queued
      (needs: T3)
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
  three sessions share that directory. T3 is running in
  /Volumes/Storage/home/scott.b/repos/.wt-sonar-s9073 instead. Second, a
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
