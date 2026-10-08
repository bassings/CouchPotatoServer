# Critical SonarQube follow-ups, 2026-10-09

## Scope

Continue from the clean `master` scan at `5df3baf7d`. Its 191 critical code
smells are chiefly complexity and repeated-literal warnings. Work in bounded
groups ordered by severity, then by the consequence of a mistake. Preserve
the existing dispositions when a scanner-only change would add risk without
improving a verified contract. Production promotion is outside this plan.

## First group: NZBGet connection handling

Four methods repeat the same `writelog` connection check and five diagnostic
strings. Their eight critical findings are three `python:S3776` complexity
records and five `python:S1192` repeated-literal records. Consolidate the
common connection check without changing each caller's failure return shape,
RPC message, logging level or status and deletion behaviour.

### Acceptance criteria

1. `download`, `test`, `getAllDownloadStatus` and `removeFailed` send their
   existing `writelog` level and message and report true, false, socket and
   HTTP protocol outcomes with the same failure return shapes.
2. Authentication refusal is distinguished from other protocol errors, and
   the connection failure prevents queue writes, status reads and deletion.
   Non-401 protocol diagnostics include only the HTTP status, never the RPC
   URL, because that URL can contain downloader credentials.
3. Focused tests cover those outcomes and fail under a deliberate change to
   the shared connection result. The full repository gate and two independent
   local reviews pass before push.
4. PR CI and cloud review pass, the PR merges, and a clean-master SonarQube
   scan records exactly which of the eight issue keys closed and any new keys.

## Tasks

- [x] C1 Pin the NZBGet connection and failure contracts in focused tests.
- [x] C2 Consolidate the repeated connection check and pass local verification.
- [ ] C3 Complete independent review, PR, CI, merge and exact-master scan. — state: building (since 2026-10-08T23:28:20+00:00)
- [ ] C4 Reconcile the next critical group against the new scan and record its disposition or implementation plan.

## Conductor log

- 2026-10-09: GitHub access works and remote `master` is `8cd1f2847`. The shared checkout has unrelated changes, so work is isolated in a linked worktree. The starting scan has 668 open smells, 191 critical. The NZBGet group contains eight critical records across one repeated connection path.
- 2026-10-09: Twenty focused tests cover the four RPC messages, true and false `writelog` results, socket failure, authentication refusal and other protocol errors. They pass before and after consolidating the four connection blocks. A deliberate false-success mutation caused eight test failures; restoration returned all twenty to green. The refactor preserves an existing byte-rendered filename in the download RPC message.
- 2026-10-09: Independent review found the old non-401 protocol log exposes credentials embedded in the RPC URL and a test checked only the log format, not its argument. A revised test failed in all four callers against the unsafe helper. The helper now logs only the HTTP code; all twenty focused cases pass, and deliberately passing the exception object again made the four privacy cases fail. The first full gate was interrupted after this change; two transient failures in unrelated gate tests passed when rerun together.
- 2026-10-09: The fresh full local gate passed: 4,823 Python unit tests, 42 integration tests, 311 UI unit tests, 225 desktop, 24 phone-width and 126 accessibility browser tests, plus lint, traps and conformance. The working-tree secret scan passed. Two fresh independent reviews found no remaining material issue. The changed production file is outside configured mutation scope, so the deliberate connection-result and privacy mutations supply the load-bearing proof.
