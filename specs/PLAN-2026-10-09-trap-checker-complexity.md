# Trap-checker complexity batch, 2026-10-09

## Finding

The exact clean-master scan at `c00e7b8d` reports five critical
`python:S3776` findings in `scripts/check_test_traps.py`: `_iter_run_steps`
(33), `check_workflow` (25), `check_e2e_ast_traps` (28),
`check_live_region_visibility` (37) and `_iter_script_blocks` (16).
These checks are merge safeguards. A refactor must not make a bad workflow,
Playwright test or inline script pass silently.

Targeted issue keys: `4eb95e12-433d-4b11-bd45-dfa4f201cac8`,
`f709fda9-a373-4bfa-94b9-2d1d60487076`,
`fce372de-4179-4bbc-8dc8-98e738c84769`,
`ec1ffa14-d665-4f4a-b934-a6b1f958cca9` and
`cd8b782a-4ed9-4c49-98a8-45e7d5367609`.

## Acceptance criteria

1. Split the five functions by parsing/checking responsibility so a new
   clean-master SonarQube scan closes their five targeted `S3776` keys.
   Preserve every finding tuple, line number, error message and failure mode.
2. Characterise existing false-green and valid boundary cases before the
   refactor. Differentially compare the original and changed checkers on
   deterministic generated and repository inputs; differences require a
   focused behaviour test and explicit disposition. Prove any new tests are
   load-bearing with deliberate mutations and restoration.
3. `make check-traps`, focused tests, the full repository gate and two
   independent clean-agent reviews pass before push.
4. PR, CI and cloud review pass. An exact clean-master scan closes the five
   targets, introduces no distinct findings and passes the reporting quality
   gate. No production deployment.

## Tasks

- [x] C1 Capture baseline and characterise guard boundaries; state: completed
- [x] C2 Extract small helpers and prove differential equivalence; state: completed
- [ ] C3 Complete gates, reviews, PR, merge and exact-master scan; state: building

## Conductor log

- 2026-10-09: Chose this five-finding cluster after the remaining literal
  and empty-hook batches. The checker already has a broad test suite, but
  false-green risk warrants differential input comparison and explicit
  review of any mismatches.
- 2026-10-09: Baseline passed 318 checker tests and `make check-traps` before
  the refactor. Extracted helpers from all five functions; the same 318 tests,
  targeted Ruff and `make check-traps` pass afterward. Old and new functions
  returned identical findings on 3,007 workflow, 10,035 HTML, 128 E2E AST
  and 128 live-region inputs, including repository files. No new test or
  guard was added, so the test-mutation criterion was not triggered.
- 2026-10-09: A final frozen-source `make coverage` run passed 4,915 Python
  tests and 311 JavaScript tests. It covered 90 of 109 changed executable
  checker lines (82.6%). The earlier run overlapped a source edit and made an
  `inspect.getsource` test read mixed line numbers; the frozen-source rerun
  passed that test and the full suite.
