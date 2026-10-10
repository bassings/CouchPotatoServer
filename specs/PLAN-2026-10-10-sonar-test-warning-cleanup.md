# SonarQube test-warning cleanup, 2026-10-10

## Finding

The exact clean-master scan of `655b5488b` closed the intended `S8999` and
critical release `S3776` records, but added five `python:S9073` composite
assertion warnings and two `python:S5778` exception-test warnings in the new
tests. They are all test-only and made the reporting quality gate red.

## Acceptance criteria

1. Split the five composite assertions so each condition reports its own
   failure. Keep candidate identity, wait state and response-closure coverage.
2. Construct each `Request` before its `pytest.raises` block so only the
   `read_ce_status` invocation can satisfy the expected exception.
3. Focused tests pass, and deliberate mutations of the protected size and
   response-close conditions still make their tests fail. Ruff, the full
   local gate and two independent code-reviewer agents pass before push.
4. PR CI and cloud review pass. An exact clean-master scan closes all seven
   new issue UUIDs, introduces no new issue and restores the reporting gate.
   No production deployment.

## Tasks

- [x] W1 Refactor the assertions and prove tests remain load-bearing
- [ ] W2 Review, deliver and analyse exact master; state: building

## Conductor log

- 2026-10-10: Split all five composite assertions and moved both `Request`
  constructions outside `pytest.raises`. All 124 focused scanner and release
  tests passed with Ruff. Raising the production release-size rejection
  threshold made the intended filter test fail. Removing the production
  HTTP error close made all three stream-close cases fail. Each source was
  restored and the 124 focused tests passed again.
- 2026-10-10: The full local gate passed: 4,905 Python unit, 42 integration,
  311 JavaScript unit, 227 desktop browser, 2 browser isolation, 24 phone and
  126 accessibility tests. Ruff, test-trap and UI conformance checks passed.
  Two independent code-reviewer agents found the test and plan diff clean.
