# SonarQube new-code coverage after literal consolidation, 2026-10-09

## Finding

The exact clean-master analysis at `639db05d` closed all nine targeted
critical `python:S1192` issues with no new issue records, but its new-code
coverage was 48.3% against an 80% quality-gate threshold. The changed
release module has 8 uncovered of 13 new executable lines; the collection
module has 7 uncovered of 13. The three new TMDB chart lines are covered.

## Acceptance criteria

1. Add behaviour tests for missing and unknown collection IDs across the
   affected API actions, and for the release API registration and manual
   download notification event. Assert the exact public responses and event
   data, including failure and success boundaries.
2. Prove each new test group is load-bearing through a deliberate mutation:
   confirm the mutation applies, observe test failure, restore the source
   and observe tests pass. Do not alter the runtime behaviour or weaken any
   gate.
3. Focused tests, the full repository gate and two independent local reviews
   pass before push. PR, CI and cloud review pass, then an exact clean-master
   SonarQube scan shows new-code coverage at or above 80%, no new issues and
   a passing quality gate. No production deployment.

## Tasks

- [x] C1 Add and mutation-prove the collection and release tests; state: completed
- [x] C2 Pass focused and full gates and independent review; state: completed
- [ ] C3 Deliver PR, merge and confirm clean-master coverage; state: building

## Conductor log

- 2026-10-09: Queried SonarQube's file measures after PR #523. The 29 new
  executable lines have 14 covered: 5 of 13 in release, 6 of 13 in
  collection and 3 of 3 in TMDB charts. At least 10 more need coverage to
  reach the 80% floor.
- 2026-10-09: Eleven focused tests passed. Four deliberate mutations of
  collection response text, release route documentation and manual-download
  event name each caused the intended test group to fail; restoration passed.
- 2026-10-09: Both independent local reviews are clean after correcting a
  false-green failure test. The full `make verify` gate passed, including
  browser, phone-width and accessibility checks.
- 2026-10-09: Cloud review on PR #524 found that plugin construction leaked
  base event handlers into the process-wide registry. A new shared fixture
  clones handler lists for the release and collection tests. The unisolated
  release test failed before the fix; disabling the fixture made both test
  groups fail, and restoring it passed all 18 focused tests. The second full
  `make verify` gate and two independent local re-reviews passed before the
  fix push.
