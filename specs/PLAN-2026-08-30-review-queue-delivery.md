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
- [ ] T2: FEAT-012, the renamer remembers it already decided — state: partial (b314601a: core skip only)
- [ ] T2b: FEAT-012 remainder, the guards and the surface around the skip — state: building (needs: T2)
- [ ] T3: FEAT-011a, the operator replace decision and destination resolution — state: queued
- [ ] T4: FEAT-011b, backgrounded execution, source consumption, release document — state: queued (needs: T3)
- [ ] T5: FEAT-011c, the picker UI, confirmation and accessibility — state: queued (needs: T4)
- [ ] T6: whole-branch multi-lens review cycle — state: queued (needs: T2, T5)
- [ ] T7: fix every confirmed review finding, re-review until clean — state: queued (needs: T6)
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
