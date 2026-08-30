# Delivery plan: review queue, renamer memory, manual replace

Conducted plan for the remaining work on branch
`feat/review-queue-and-manual-replace`.

**Owner instruction, 2026-08-30:** run to the end without stopping. Findings
that would normally warrant a check-in are RECORDED and the run continues; the
owner reads them at the end. Decisions are taken with the default named in each
task rather than referred back.

**The one exception, and it is the owner's own written rule.** `CLAUDE.md`
rule 6: "Production deploys only by explicit agreement: never as a side effect
of finishing work." Running to the end would make the promotion exactly that
side effect. So T10 prepares the promotion, takes the backup and names the
build, and then STOPS. Everything up to and including the merge and the
automatic beta runs unattended.

## Context

- Specs: `specs/FEAT-010-review-queue-in-wanted.md` (61 criteria, BUILT),
  `specs/FEAT-011-replace-with-this-file.md` (95),
  `specs/FEAT-012-renamer-remembers-its-decisions.md` (47), plus T67 in
  `specs/REMEDIATION-2026-08.md`.
- FEAT-010 is functionally complete: seeding, the `media.done` precondition,
  the widened Wanted query and Review chip, card actions, bulk-delete skip
  message, and the accessibility pass. Not yet reviewed as a branch.
- All owner decisions are already recorded in the specs. No task below needs
  an answer that is not already written down.

## Tasks

- [x] T1: T67, the HTTP cache silently stores nothing — state: built (09818b58)
- [x] T2: FEAT-012, the renamer remembers it already decided — state: built (b314601a)
- [x] T2b: FEAT-012 remainder, the guards and the surface — state: built (19e0289a, d87e1283)
- [x] T3: FEAT-011a, the operator replace decision and destination resolution — state: built (ba1b652a)
- [x] T4: FEAT-011b, backgrounded execution, source consumption, release document — state: built (fd396423)
- [ ] T5: FEAT-011c, the picker UI, confirmation and accessibility — state: partial (700cb61e: trigger button only)
- [ ] T5b: FEAT-011c, the replacement modal — state: partial (2a405d67: dialog shell and wording, no data)
- [x] T5d: FEAT-011c, the server-side candidate listing route — state: built (a6b0592d)
- [x] T5e: FEAT-011c, wire the modal to the listing and the submit — state: built (4051c2c1)
- [x] T5c: FEAT-011c, accessibility and mobile specs for the modal — state: built (ccdf6229)
- [x] T6: whole-branch multi-lens review cycle — state: done (2 Critical, 12 High, 24 Medium, 11 Low)
- [ ] T7a: fix C1 and C2, the two criticals — state: building
- [ ] T7b: fix the 12 High findings — state: queued (needs: T7a)
- [ ] T7c: triage Medium and Low, fix or record with evidence — state: queued (needs: T7b)
- [ ] T8: full `make verify`, push, open the PR — state: queued (needs: T7)
- [ ] T9: CI green, resolve threads, merge to master — state: queued (needs: T8)
- [ ] T10: backup prod, name the beta, STAGE the promotion and STOP — state: queued (needs: T9)

## Task detail

**T1 (T67).** Bytes must round-trip through `SQLiteCache`, existing callers
unaffected, and the silent skip replaced by something visible. Must not
reintroduce pickle. The encoding choice must be stated and a non-utf-8 body
tested.

**T2 (FEAT-012).** The skip lives in `Renamer.scan` before
`fireEvent('scanner.scan', ...)`. `folder_scanner.py` must have an EMPTY diff:
it is shared with `manage.updateLibrary`, whose cleanup deletes any `done`
movie absent from the scan result, so a memory placed there deletes films from
the library. Nothing is persisted; a restart re-decides. AC-OPS-3's bound holds
independently of the memory.

**T3 to T5 (FEAT-011).** The five owner decisions are already in the spec and
are binding: not gated on `upgrade_replace`; backgrounded with progress and a
second activation refused rather than queued; the source is always consumed on
a verified swap; a release document is written; and **the destination comes
from the media's existing file record, never recomputed from the naming
template** (a lens executed that template and got `The Thing ()/The Thing.mkv`
for two different films). This is the highest-risk change in the backlog: it
deletes media files by design, on the code path that destroyed irreplaceable
files twice.

**T6 and T7.** `/review-cycle` over the whole branch diff. The bounded fix
loop applies: rounds 1 to 3 resume the same implementer, 4 to 5 use a fresh one
on a more capable model, and at 5 the remaining findings are adjudicated and
recorded rather than fixed. A round that surfaces a NEW class rather than more
instances of a known one is the signal to re-open the approach.

**T8 and T9.** `make verify` must pass in full locally before the push, per
rule 2. The `secrets` job is a required check. Conversation resolution is
required on `master`, so review threads must be answered and resolved.

**T10.** Run `./scripts/backup.sh` against production. Identify the beta tag
built from the merge commit. Write down exactly what would be promoted and what
changes for the operator. **Then stop and hand it over.**

## Standing constraints

- Never push untested code; `make verify` green locally first.
- Sub-agents commit locally and stop; the orchestrator pushes.
- A sub-agent's report is not evidence: verify against the repo.
- When a test or guard is the deliverable, break it, watch it fail, restore by
  file copy, and confirm the restore by hash. Five stand-in guards were found
  on this branch already; assume a sixth.
- Australian English, no em dashes in any artefact except where a machine-read
  format requires one.

## Conductor log

- **Tick 1, 2026-08-30.** Plan armed: `.claude/active-plan` written (gitignored,
  so it is session state rather than a committed artefact). Running under
  `/loop /conduct-plan`. Reconciled against the repo rather than memory:
  branch `feat/review-queue-and-manual-replace`, tip `b0ba8b68`, nothing
  pushed, no PR open, FEAT-010's six build tasks all committed and each
  mutation-proven. T1 (T67, the cache) is in flight as a tdd-task workflow and
  has not committed yet, so it stays `in progress` rather than being re-issued.
  T2 is unblocked but is deliberately NOT started in parallel: both tasks run
  the full Python suite and both mutate production files to prove their guards,
  and this branch has already seen parallel agents trample a shared checkout.
  Serial is the cheaper mistake. Rework rounds so far: 0 on every task.
  Armed: T1's workflow notification, plus a fallback heartbeat. Next wake
  expects T1 either committed or aborted.
- **Tick 2, 2026-08-30.** T1 (T67) built and verified independently: commit
  `09818b58`, on the right branch despite the workflow report citing a stale
  one. Bytes now round-trip via base64 inside the JSON envelope, chosen over a
  utf-8 decode because HTTP bodies are not guaranteed utf-8 and a lossy decode
  would corrupt a cached response rather than fail to cache it; the pickle CVE
  mitigation is untouched. The silent skip is now a WARNING.
  Both halves mutation-proven, cache.py restored to a matching checksum.
  **One probe of mine was not hostile and I nearly recorded its green as
  evidence**: the report call is split across lines, so a single-line pattern
  matched nothing and the suite passed because nothing had been mutated. Redone
  against the real line. That is the sixth stand-in on this branch and the
  second one that was mine.
  **Box semantics, deviation recorded:** T1 to T5 are build tasks on ONE
  branch, not separate PRs, so they tick at `built` rather than at `merged`.
  T8, T9 and T10 keep the PR-level meaning. Without this nothing ticks until
  the very end and the plan carries no progress signal.
  T2 (FEAT-012) launched. Rework rounds: T1 0, T2 0.
  Armed: T2's workflow notification plus a fallback heartbeat. Next wake
  expects T2 committed, or T2 aborted on a limit as T1's earlier sibling was.
- **Tick 3, 2026-08-30.** Quiet hold. T2 mid-flight: its RED test
  (`tests/unit/test_renamer_decision_memory.py`) is written and untracked, so
  the implement phase has not landed. Nothing acted on. T3 stays queued and
  the serial choice is now measured rather than cautious: T3 edits
  `renamer/main.py`, the same file T2 is changing, so parallel would conflict
  outright rather than merely risk contention. Rework rounds: T2 0.
  Armed: T2's workflow notification plus the heartbeat.
- **Tick 4, 2026-08-31.** T2 reported DONE; reconciling against the repo says
  PARTIAL, so it is recorded that way rather than ticked. Commit `b314601a`
  adds 163 lines of production logic to `renamer/main.py` guarded by exactly
  ONE test, against a 47-criterion spec. The core skip is real and the key is
  sounder than the spec feared: it signs the whole scan folder (names, sizes,
  mtimes) rather than title-and-year, so the collision the spec warned about
  ("two different downloads both reduce to minions and monsters 2015") cannot
  arise by construction.
  **The gap that matters: AC-SIMP-2, the data-loss guard, is a promise and not
  a test.** `folder_scanner.py` IS untouched today, and nothing asserts it
  stays that way, so a later change to the module that can delete a film's
  library entry lands unnoticed. The task said "assert the empty diff as a
  test, not as a promise" and that instruction was not followed. Also missing:
  every invalidation trigger, the restart-re-decides case, AC-OPS-3's bound
  proven with the memory DISABLED, and the notify surface.
  This is NOT a rework round. Nothing built was wrong; the scope delivered was
  narrower than the scope asked for, which is a different failure and does not
  trip the circuit-breaker. Rework rounds: T2 0, T2b 0.
  T2b launched to close all five. Armed: T2b's workflow plus the heartbeat.
- **Tick 5, 2026-08-31.** Quiet hold, T2b mid-flight and progressing: the
  memory test file has gone from 1 test to 7, plus a new
  `test_renamer_decision_memory_invalidation.py`. Nothing acted on.
  **Flagged for the pre-push check:** an untracked `a-different-library-root/`
  directory has appeared at the REPO ROOT, presumably a fixture for the
  destination-changed invalidation case. A test that writes into the repo root
  rather than `tmp_path` leaves debris that a later `git add -A` commits, and
  this branch has already spent a day on artefacts reaching places nobody
  intended. If it survives T2b, it is either moved to `tmp_path` or gitignored
  with a reason, not left loose. Rework rounds: T2b 0.
  Armed: T2b's workflow plus the heartbeat.
- **Tick 6, 2026-08-31.** T2b returned BLOCKED at three implementation
  attempts, and I OVERRODE that rather than stopping. Recorded because it
  overrides this plan's own circuit-breaker.
  The evidence said the frame was fine: all 13 of its tests passed, and the
  suite failed on ONE unrelated repo guard,
  `test_fixtures_do_not_leak_gitdir`, because the new file made two subprocess
  git calls without `env=sanitized_git_env()`. That guard is correct and its
  incident is recorded: git exports GIT_DIR into a pre-push hook launched from
  a worktree, so an unsanitised call operates on the REAL repository rather
  than its own cwd. Two arguments. Fixed directly rather than spending a fourth
  agent round.
  The rule exists to stop wasted iteration on a WRONG SHAPE. The shape was
  right and the diagnosis was unambiguous, so stopping would have cost the
  owner a decision they do not need to make. Had the diagnosis been unclear, or
  had the fix touched the mechanism rather than the test harness, stopping was
  the correct move. Rounds are NOT reset by this: T2b stands at 3.
  **AC-SIMP-2 is now a real test and is mutation-proven.** Appending a comment
  to `folder_scanner.py` fails `TestFolderScannerIsUntouched`; restoring gives
  a matching checksum. That is the guard between a renamer optimisation and a
  film's library entry disappearing, and until this tick it was a sentence.
  The stray `a-different-library-root/` flagged at tick 5 was cleaned up by the
  task; tree is clean.
  Suite 3643 passed, ruff clean. T3 (FEAT-011a) launched, the highest-risk
  task in the plan. Rework rounds: T2 0, T2b 3 (resolved), T3 0.
- **Tick 7, 2026-08-31.** T3 built (`ba1b652a`) and verified: 375 insertions,
  ZERO deletions, so the automatic path is structurally untouched rather than
  merely asserted to be. Three named outcomes, and the decision reads the
  film's recorded file rather than computing one.
  Both refusals mutation-proven. Resolving ambiguity by taking the first
  candidate fails two tests including the one that runs the same pair in both
  orders; treating "nothing recorded" as permission to proceed fails six.
  replacement.py restored to a matching checksum.
  Noted from the RED verifier and NOT fixed, because it is cosmetic and the
  test carries its load elsewhere: one closing assertion compares two
  fixture-supplied paths that differ by construction, so that line alone is
  near-tautological. Recorded here so the branch review can judge it rather
  than rediscover it.
  T4 launched: the layer that actually deletes the file. Every safety property
  in its prompt has its own test demanded, including that the destroyed path is
  never caller-supplied, proven by handing it a decoy victim file and hashing
  that file before and after.
  Rework rounds: T3 0, T4 0. Armed: T4's workflow plus the heartbeat.
- **Tick 8, 2026-08-31.** Quiet hold, T4 mid-flight with a new
  `test_replacement_operator_execution.py` and edits to `renamer/main.py`.
  Checked the one thing worth checking mid-flight: `replacement.py` shows 18
  insertions and ZERO deletions, so T4 is adding beside T3's decision rather
  than rewriting it, which is what the task required and what the isolation
  argument depends on. Journal last written 11 minutes before this tick, which
  is within normal for an agent mid-implementation, so no liveness action.
  Rework rounds: T4 0. Armed: T4's workflow plus the heartbeat.
- **Tick 9, 2026-08-31.** T4 built (`fd396423`), 20 tests, suite 3679.
  The property that matters is proven the right way. I injected the EXACT
  AC-SEC-1 vulnerability, making `operatorReplaceView` honour a caller-supplied
  `destination`, and the guard failed on a SHA256 comparison of a decoy file
  that should never have been touched. That is the difference between a test
  that checks a return value and one that checks whether a file was harmed.
  `renamer/main.py` restored to a matching checksum.
  Design confirmed in source as well as by test: the view reads only
  `media_id` and `source`, the destination is resolved server-side from T3's
  decision, and the destructive step goes through `replace_atomically` so every
  symlink and size refusal stays reachable.
  T5 launched, the last build task. Its prompt carries the two accessibility
  measurements this branch has already produced as evidence that class names
  are not a proxy for rendered values: a chip at 23px against a 24px floor and
  a badge at 1.92:1 against 4.5:1, both with correct-looking Tailwind tokens.
  Rework rounds: T4 0, T5 0. Armed: T5's workflow plus the heartbeat.
- **Tick 10, 2026-08-31.** T5 reported DONE; the repo says PARTIAL and
  substantially so. Commit `700cb61e` is 27 template lines and a trigger
  button that opens nothing. No modal, no candidate listing, no progress, no
  second-activation refusal, and NO `*.a11y.spec.ts` or `*.mobile.spec.ts`
  files at all, which were named explicitly in the prompt as the only place
  those assertions can run.
  **This is the second task to report DONE while delivering the first slice
  (T2 was the first), and the fault is mine rather than the agent's.** The T5
  prompt asked for three substantial deliverables plus accessibility across two
  Playwright projects in a single task. That is three tasks' worth, and an
  agent facing it builds the first thing and reports success. The lesson is a
  scoping one and it applies to the tasks still queued: one deliverable per
  task, and if the prompt needs the word "plus", split it.
  Split accordingly into T5b (modal and listing) and T5c (progress, refusal,
  accessibility). T5b launched.
  Not counted as a rework round: nothing built was wrong. Rework rounds: T5 0,
  T5b 0, T5c 0. Armed: T5b's workflow plus the heartbeat.
- **Tick 11, 2026-08-31.** T5b reported DONE; PARTIAL again, and this time the
  cause is diagnosable rather than just "too big".
  Commit `2a405d67` delivers a real design-system dialog: teleported, focus
  trapped, focus returned to the trigger on close, and it names what will be
  DESTROYED ("current library copy and put the file you..."). That half is
  genuinely good and was the highest-risk wording in the feature.
  What is absent: candidate loading, the submit, and the server listing route.
  `operatorReplaceModal()` has `isOpen`, `open`, `close` and `trapFocus`, and
  nothing else. The dialog opens onto no data and cannot submit.
  **ROOT CAUSE, and it is mine: I pointed the task at
  `test_operator_replace_trigger_ui_template.py`, a Jinja RENDER-level pattern.
  A render test cannot exercise a fetch, a route, or a confinement rule.** The
  agent built precisely what its tests could verify, which was markup, and
  passed a full gate doing it. Splitting the task at tick 10 was the right
  move for the wrong reason: the size was not the problem, the TEST TIER was.
  Correction applied to the remaining work: every task now names its test tier
  explicitly, and T5d's prompt says in terms why a render test would let a
  route that returns nothing ship green.
  Third partial, still not a rework round: nothing built is wrong.
  Rework rounds: T5b 0, T5d 0, T5e 0.
- **Tick 12, 2026-08-31.** T5d COMPLETE, not partial, and the difference is
  the correction from tick 11: the prompt named the test tier and said why a
  render test would let a route that returns nothing ship green. Seven
  route-and-plugin-level tests, both methods, a REAL symlink rather than a
  mocked one.
  The property that matters is proven: it reuses `_resolveOperatorSource`, the
  already mutation-proven confinement, as the SOLE gate rather than writing a
  second copy of a security rule. Neutering that gate (`if False:`) fails two
  tests including the escaping-symlink case. `main.py` restored to a matching
  checksum.
  Returns bare names only, never paths, which is both the privacy rule and
  what stops the client sending a path back.
  T5e launched, again naming its tier: PLAYWRIGHT E2E, because a fetch, a click
  and a request count cannot be tested any other way. It must assert the submit
  carries EXACTLY media_id and source by intercepting the request, so an extra
  parameter cannot creep in later unnoticed.
  Rework rounds: T5d 0, T5e 0. Armed: T5e's workflow plus the heartbeat.
- **Tick 13, 2026-08-31.** Quiet hold, T5e mid-flight and active: journal
  written two minutes before this tick, `tests/e2e/operator-replace-modal.spec.ts`
  created, `scripts/seed_e2e_data.py` being modified (it needs a candidate file
  under the watch folder for the listing to return). No action.
  Worth watching rather than acting on: the seed script is shared
  infrastructure, and its own guard test
  (`tests/unit/test_seed_e2e_data_guard.py`) should catch a bad edit. If that
  guard goes red, it is a real finding, not noise.
  Rework rounds: T5e 0. Armed: T5e's workflow plus the heartbeat.
- **Tick 14, 2026-08-31.** T5e COMPLETE (`4051c2c1`), 8 E2E tests, second
  consecutive full delivery since the test-tier correction. The modal now loads
  server-supplied candidates as radios, disables confirm until one is chosen,
  distinguishes an EMPTY listing from a FAILED one (different situations, and
  the spec required they read differently), re-fetches rather than reloading,
  and refuses a second submit rather than queueing it.
  The property worth proving was proven: I smuggled a `destination` parameter
  onto the destructive submit URL, and exactly ONE test failed, the
  exactly-two-parameters assertion. Seven others stayed green, so the probe
  discriminates rather than reddening everything. Template restored to a
  matching checksum, all 8 pass.
  That matters because the never-caller-supplied-path property is enforced at
  BOTH ends now: the server ignores every other key (mutation-proven at tick 9)
  and the client is pinned to sending exactly two (mutation-proven here).
  **Second-activation refusal was in scope here and is done**, so T5c reduces
  to the accessibility floor, which is what it is now building. Progress
  reporting beyond the in-flight refusal is NOT built and is recorded as debt
  for the branch review to judge rather than silently dropped.
  Rework rounds: T5e 0, T5c 0. Armed: T5c's workflow plus the heartbeat.
- **Tick 15, 2026-08-31.** Quiet hold. T5c's journal had been silent for 24
  minutes, the longest gap of the run, so I checked liveness rather than
  assuming either way: it is mid-Playwright-run on the accessibility project
  (`operator-replace-modal.a11y.spec.ts`), load 5.4. The silence was one long
  tool call, not a death. Two background jobs HAVE died silently on this branch,
  so the check was worth making rather than waiting out.
  Both spec files exist with the correct names
  (`*.a11y.spec.ts`, `*.mobile.spec.ts`), which is the thing that determines
  whether these assertions run at all.
  Rework rounds: T5c 0. Armed: T5c's workflow plus the heartbeat.
- **Tick 16, 2026-08-31. ALL BUILD TASKS COMPLETE.** T5c committed
  (`ccdf6229`) and it earned its keep: the accessibility pass found REAL
  defects in code that had already passed every other gate.
  - The confirm control, the one that DESTROYS a file, rendered at 32px,
    under the target floor.
  - Its danger-token contrast composited to 4.46:1 against a 4.5:1 floor, the
    same 8% tint bug already fixed once on the review-queue card control.
  - The candidate radios had NO arrow-key handling at all, so they were radios
    in appearance and not in behaviour.
  - And it found that identical contrast bug PRE-EXISTING on the release
    table's own "Mark failed" control, which nothing on this branch had
    touched. That is the third time on this branch that measuring a rendered
    value has contradicted correct-looking classes.
  T6 launched: the whole-branch review cycle, ADVERSARIAL, against master.
  Deliberately BEFORE `make verify` rather than after: the review is the thing
  most likely to demand changes, and a verify run spent on a tree that is about
  to change is a verify run wasted.
  Rework rounds: all tasks 0. Armed: the review workflow plus the heartbeat.
- **Tick 17, 2026-08-31.** Quiet hold, T6 converging: 11 lens results recorded
  and the worktree count has fallen from 8 to 3 as lenses finish and remove
  their own checkouts. That self-cleanup is worth noting because leftover
  worktrees were a recorded problem earlier in this session, and five had to be
  removed by hand after PR #291.
  No action. Rework rounds: all 0. Armed: the review workflow plus the
  heartbeat.
- **Tick 18, 2026-08-31.** Quiet hold, but checked properly rather than waited
  out: the review journal had not moved in 30 minutes, results stuck at 11 and
  worktrees at 3, which is the shape of a stall.
  Evidence says otherwise. Three lens worktrees are still checked out
  (`-3`, `-4`, `-10`), 15 agent processes are live, load is 2.9, and the last
  journal entry is `started` rather than a result. A lens mid-analysis writes
  nothing, and this branch diff is far larger than the ones whose lenses took
  18 to 35 minutes earlier in the session. Alive, not hung.
  **Decision rule set so this is not waited out indefinitely:** if the NEXT
  tick shows the journal still at 11 results with no new worktree activity, the
  run is treated as hung. The correct response then is NOT to kill it blind: it
  is to read the per-lens results already in the journal, which are durable, and
  re-run only the lenses that never reported. Forty-five minutes of completed
  lens work should not be thrown away to restart a fan-out.
  Rework rounds: all 0. Armed: the review workflow plus the heartbeat.
- **Tick 19, 2026-08-31. REVIEW COMPLETE: 2 Critical, 12 High, 24 Medium, 11
  Low across 8 lenses.** Full report saved to
  `QA/branch-review-2026-08-31-review-queue.md`.
  **C1: the destructive replacement is reachable CROSS-ORIGIN.** Two lenses
  independently EXECUTED it: a GET carrying `Origin: https://evil.example`
  returned 200, the library file's sha256 changed, and the operator's source
  was deleted. Any page a logged-in operator visits could destroy a film.
  **C2: the source-size guard compares a fresh stat with ITSELF**, so it can
  never disagree. Measured: append 75,000 bytes after the operator sees the
  candidate list, and a 112,000-byte library file becomes 102,000 bytes, then
  the partial source is deleted. BOTH COPIES OF THE FILM ARE GONE.
  **C2 is a miss in MY OWN verification and it is the seventh stand-in of this
  session.** At tick 9 I mutation-proved that `expected_source_size` was
  PRESENT and not None. The review proved it is MEANINGLESS. The existing test
  asserts `expected_source_size is not None`, and rewriting the argument to a
  literal `os.path.getsize(source)` leaves all 36 operator tests green. I
  proved an argument was passed; I never proved it carried information.
  The review names the class, and it is architectural rather than two bugs:
  the operator path has NO SERVER-SIDE DECISION STEP, so every "compare against
  the value captured at decision time" guard degenerates into comparing a value
  with itself. M6 is the same defect on `destination_identity`.
  T7 split by severity. T7a launched to fix the class, not the instances, and
  to reuse the origin helper that already exists at `couchpotato/__init__.py:778`
  rather than invent a second security mechanism.
  Also recorded from the review and NOT yet actioned: six of seven lenses hit
  CHECKOUT DRIFT, finding the worktree on the wrong branch, and one recorded
  that the local branch ref was deleted and recreated beneath it by another
  session. That is a process defect independent of the code.
  Rework rounds: T7a is round 1 of the fix loop.
