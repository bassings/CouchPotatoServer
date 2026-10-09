# SonarQube compute-task poll recovery, 2026-10-09

## Finding

The critical `python:S3776` issue in `scripts/sonar_scan.py:poll_ce_task`
covers a real operability failure. A prior clean-master upload reached a
successful Compute Engine task, but a single unreadable poll response made
the local command fail before it could write its freshness stamp. Retrying
the entire scan costs coverage generation and can obscure whether the first
upload completed.

## Acceptance criteria

1. A transient unreadable JSON response, transport failure or HTTP 5xx during
   CE polling is retried within the existing bounded poll deadline. A later
   `SUCCESS` writes the freshness stamp for the exact checkout revision.
2. Repeated transient failures reach the deadline and leave the prior stamp
   unchanged. No response body, URL query, token or private path is logged.
3. HTTP 401/403, other non-retryable HTTP responses, malformed task data,
   unknown statuses and terminal `FAILED`/`CANCELED` remain fail-fast and do
   not write a new stamp.
4. Split request decoding from poll state handling so the critical complexity
   finding closes without weakening the clean-master and post-upload checks.
   New tests fail before the fix, pass after it and fail under a deliberate
   retry-policy mutation. Complete the repository gate, two local reviews,
   PR, CI, merge and exact-master SonarQube confirmation.

## Tasks

- [x] P1 Add failing transient-retry and bounded-failure tests.
- [x] P2 Implement bounded retries and pass focused and full gates.
- [ ] P3 Complete independent review, PR, CI, merge and post-merge scan; state: building

## Conductor log

- 2026-10-09: The `poll_ce_task` critical complexity warning was reconciled with the prior measured unreadable CE response after a successful upload. Work is isolated from PR #518 in a separate worktree. Production deployment and SonarQube administration are outside this plan.
- 2026-10-09: Four recovery/timeout cases failed before the change. After the bounded retry and status-decoding split, all 111 scanner tests pass. A deliberate removal of the HTTP 5xx retry failed the new recovery test and was restored. The full repository gate is running.
- 2026-10-09: `make verify` passed, including Python, JavaScript, desktop and phone-width browser, accessibility, security and Docker checks. PR #518 merged as `880b5398`; its exact-master SonarQube scan is running.
- 2026-10-09: The branch was rebased onto `880b5398` with an identical tree to the one that passed `make verify`. Both independent local reviews were requested before pushing.
- 2026-10-09: Independent review reproduced an unknown CE status leaking response content into stderr. A new test failed with a private-path marker, the error was made generic, all 112 scanner tests passed, and a deliberate reintroduction of the leak failed the new test. Repeat local review is required before pushing.
- 2026-10-09: PR #519 cloud review found `http.client.IncompleteRead` escaping when a CE response ends before its declared length. A response-read test failed with the raw exception, then passed after classifying it as transient. All 113 scanner tests pass; removing the new catch makes that test fail. Repeat local review is required before the fix push.
- 2026-10-09: Two local reviewers found the next HTTP parser subclass, `BadStatusLine`, still escaped and could expose server-supplied text. The exception policy now catches the `HTTPException` family instead of individual subclasses. Recovery tests for `IncompleteRead`, `BadStatusLine` and `LineTooLong`, plus a bounded private-marker timeout test, failed before the class-level fix and pass after it. All 116 scanner tests pass; removing the family catch makes four cases fail. Repeat local review is required before pushing.
- 2026-10-09: PR #519 merged as `6fb95aac`. Its exact clean-master scan
  showed that the critical `poll_ce_task` complexity warning remains at 16,
  one above the permitted 15. It also showed one new minor `python:S5713`
  warning because `URLError` derives from `OSError`, leaving the new-code
  quality gate in error. The follow-up removes the redundant class and moves
  the two identical deadline checks into a small helper. This preserves the
  same monotonic-clock calls, timeout text and poll boundary. Focused tests,
  full gate, review and post-merge confirmation are required again.
