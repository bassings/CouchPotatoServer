# SonarQube release, collection and charts literals, 2026-10-09

## Finding

The clean-master SonarQube analysis at `6fb95aac` reports nine critical
`python:S1192` findings across release handling, collection operations and
TMDB chart descriptions. These include user-facing API text, a collection
lock key and a release notification event name. A bulk literal extraction can
close this class of findings while retaining exact runtime values.

## Acceptance criteria

1. Share the nine repeated values without changing API descriptions, error
   responses, log formatting, lock keys, event names or chart metadata.
2. After inlining the new constants, each module's syntax tree matches its
   pre-change version. Relevant release, collection and chart tests pass, as
   do the full repository gate and two independent local reviews before push.
3. PR, CI and cloud reviews pass; a clean-master post-merge analysis confirms
   the exact closed issue keys and checks for new findings. No production
   deployment.

## Tasks

- [x] L1 Share the nine exact literal values; state: verified
- [x] L2 Verify behaviour and complete the full local gate; state: verified
- [ ] L3 Complete independent review, PR, CI, merge and post-merge scan; state: queued

## Conductor log

- 2026-10-09: Selected nine critical repeated-literal findings from the
  `6fb95aac` clean-master issue snapshot. Kept the three related modules in
  one batch because each change is a constant substitution with a shared AST
  equivalence check.
- 2026-10-09: All three modules match their `origin/master` syntax trees after
  inlining the nine new constants. Targeted Ruff and 51 focused release,
  collection, chart and event-name tests pass.
- 2026-10-09: The full `make verify` gate passed: 4,844 Python unit tests,
  42 integration tests, 311 UI unit tests, 227 desktop browser tests,
  2 isolation tests, 24 phone tests and 126 accessibility tests. The
  non-blocking security-lint inventory reported 137 existing findings.
  Two independent local reviews found the code diff clean and confirmed
  syntax-tree equivalence after inlining each constant.
