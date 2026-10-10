# SonarQube continuation, 2026-10-10

## Objective

Continue Scott's finding-delivery request from clean `master` at `0a908e769`.
The exact scan has 608 open findings, including 133 critical, with a green
reporting gate, 66.5% coverage and zero bugs, vulnerabilities or hotspots.
Resolve a bounded critical batch, or record an evidence-backed disposition
where a scanner-only refactor would increase operational or data-loss risk.
Production deployment is outside this plan.

Scott also reported a reliability issue after the #530 to #533 batch.
Investigate and repair that first if it affects users, guards or delivery.

## Acceptance criteria

1. Identify the reported reliability defect from a reproducible symptom,
   failing test, or concrete workflow gap. For a behavioural fix, capture the
   failure before changing production code, then prove the test or guard is
   load-bearing by mutation and restoration. Close the reported `python:S8999`
   finding on the fixture-isolation test without losing `pytester` coverage.
2. Reconcile completed #530 to #533 plans with their exact post-merge scans.
   Preserve the fact that #532 made no SonarQube change and #533 closed the
   remaining default-shell warning.
3. Triage the eight critical `python:S3776` records in
   `couchpotato/core/plugins/release/main.py` by method and consequence.
   Characterise database writes, deletion, download and status transitions
   before extracting control flow. Deliver only a safe, bounded subset with
   measured behaviour and changed-line coverage; record holds explicitly.
4. For delivered code, pass focused checks, the full local gate, two clean
   independent reviews, PR CI and cloud review, then merge and analyse exact
   clean `master`. Confirm intended issue closure, new issues and the
   reporting gate. No production deployment.

## Tasks

- [x] R1 Investigate and fix the reported reliability issue
- [x] R2 Reconcile #530 to #533 completion evidence in their plans
- [x] R3 Triage release-plugin critical findings and characterise safe behaviour
- [x] R4 Implement and deliver the selected bounded critical slice
- [x] R5 Confirm exact-master results and select the next critical group
- [ ] R6 Close new test-only SonarQube warnings and restore the reporting gate; state: building
- [ ] R7 Triage the three critical E2E guard complexity findings; state: queued

## Conductor log

- 2026-10-10: Remote `master` remains `0a908e769`. PRs #530 to #533 are
  merged. The exact final scan closed 11 critical records across the four
  PRs, leaving 608 open and 133 critical. The shared checkout contains
  unrelated changes and an untracked handoff plan, so this continuation uses
  an isolated worktree. A clarification of the reported reliability symptom
  has been requested while independent investigation continues.
- 2026-10-10: The session stop guard resolves the shared checkout, whose
  ignored marker still named the completed handoff. Its marker now names a
  local copy of this continuation plan with five open tasks. The shared
  checkout's existing tracked and untracked work was preserved.
- 2026-10-10: Eight release-plugin S3776 findings were inspected. `cleanDone`
  can delete records and has a documented dormant SQLite path; `add`,
  `createFromSearch`, and `updateStatus` write status or media state;
  `download` triggers external clients and writes download state; `clean`
  deletes or updates rows; `forMedia` guards against incomplete reads used by
  file replacement. Those seven need dedicated behavioural work, not a bulk
  complexity extraction. `tryDownloadResult` only filters candidates and
  dispatches downloads, so its filtering loop is the bounded first slice.
- 2026-10-10: Four #530 to #533 plans now record their merged PRs and exact
  scan outcomes, including #532's misattribution and #533's correction. The
  release-result filter extraction has four contract tests and matched the
  original on 3,000 generated batches. A size-threshold mutation made the
  contract tests fail, then restoration passed. Focused tests and Ruff pass;
  full gate and independent review are pending.
- 2026-10-10: Re-read PR #519's local scanner retry change and its review
  observation: an HTTPError retains its response stream while a failed CE
  poll is retried. A retained-error test failed for 401, 404 and 503 on the
  current code. The reader now closes each error response, preserving the
  original poll outcome even if close raises OSError. A close-failure test
  failed before that guard and passed after. Removing the close call again
  made all three retained-stream cases fail; restoration passed. This is a
  concrete reliability fix alongside the session stop-guard correction.
- 2026-10-10: Scott identified the reported issue as `python:S8999` on
  `tests/unit/test_sonar_env_fixture_isolation.py`, severity major in the
  exact scan. Removing the module-level plugin declaration first produced
  three fixture-not-found errors. Registering `pytester` in the unit
  `conftest.py` passed all three cases and 127 focused tests. Deliberately
  removing that registration again produced the three expected errors;
  restoration passed. This changes shared unit-test plugin availability, so
  the full suite is required before delivery.
- 2026-10-10: Two independent code-reviewer agents found the staged branch
  clean. The first full gate reached browser tests after Python, integration,
  JavaScript unit and static checks passed, but browser setup found an
  `.e2e-w0-data` directory left by an earlier interrupted run. The run was
  stopped, `scripts/e2e_worker_data.py cleanup 0` removed that worker state,
  and the complete gate was restarted on the same staged code.
- 2026-10-10: The clean rerun of `make verify` passed: 4,905 Python unit
  tests, 42 integration tests, 311 JavaScript unit tests, 227 desktop browser
  tests, 2 browser isolation tests, 24 phone tests and 126 accessibility
  tests. Ruff, the test-trap check and UI conformance passed. The reported
  `pytest_plugins` placement is fixed locally; delivery and exact-master
  confirmation remain open.
- 2026-10-10: The pre-push hook repeated and passed the full gate, then
  pushed `5a0fe11c1`. PR #534 is open for CI and cloud review. No production
  deployment was started.
- 2026-10-10: Claude's cloud review passed. Codex raised a P1 claim that
  pytest forbids `pytest_plugins` in `tests/unit/conftest.py`; this is
  contradicted by two complete root-run local gates with the repository's
  pinned pytest 9.1.1. Replied with that evidence and resolved the thread.
  CI Python, accessibility, lint, secrets, dependency review and CodeQL pass;
  Docker and browser CI jobs remain pending.
- 2026-10-10: All PR #534 checks passed, the cloud review thread was resolved,
  and the PR merged as `655b5488bf482c80c51f487d69b33e3a3db2922e`.
  Remote `master` matches that commit. Exact-master SonarQube confirmation is
  next; automatic beta and post-merge checks are separate from production.
- 2026-10-10: Exact clean-master analysis of `655b5488b` closed the reported
  `python:S8999` and the release filter's critical `python:S3776`. Open
  findings moved 608 to 613 and critical findings 133 to 132. Seven new
  test-only findings, five `python:S9073` and two `python:S5778`, made the
  reporting gate red; coverage stayed 66.5% with zero bugs, vulnerabilities
  or security hotspots. They are the immediate cleanup slice. The next
  critical cluster to triage is three `javascript:S3776` findings in
  `scripts/check_e2e_test_traps.mjs`, a potential bounded bulk fix.
- 2026-10-10: The seven test-only warnings were fixed with individual
  assertions and narrow `pytest.raises` blocks. All 124 focused tests passed;
  size-filter and stream-close mutations made the intended tests fail and
  restoration passed. The complete local gate passed, including 4,905 Python
  unit, 42 integration, 311 JavaScript unit, 227 desktop, 2 isolation, 24
  phone and 126 accessibility tests. Two independent local reviews were clean.
  PR delivery and exact-master SonarQube confirmation remain open.
