# SonarQube shell-gate checker complexity, 2026-10-09

## Finding

The clean-master scan at `a9fdbc0e` retains two critical `python:S3776`
findings in `scripts/check_test_traps.py`: `_has_pipefail` (33/15) and
`check_shell_script` (51/15). Both decide whether a verification shell script
can hide a failing command. They share shell token and option parsing and can
be simplified together without relaxing the false-green guard.

## Acceptance criteria

1. Reduce each targeted function to cognitive complexity at or below 15, with
   no change in checker findings for existing repository files or characterised
   boundary inputs.
2. Test `set` option groups, disabled options, comments, quoted hints,
   continuations, POSIX `sh`, pipelines and command boundaries. Prove a new
   test catches a deliberate protected-condition mutation and passes after
   restoration.
3. Pass the complete trap-checker unit suite, `make check-traps`, the full repository
   gate and two independent local reviews before push.
4. Deliver a PR through CI and cloud review, then confirm both issue keys
   close in an exact clean-master SonarQube scan with no new findings. No
   production deployment.

## Tasks

- [x] S1 Characterise shell-gate behaviour and mutation-prove tests; state: completed
- [x] S2 Refactor both functions with unchanged outputs; state: completed
- [x] S3 Complete gates, reviews, PR, merge and exact-master scan; state: completed

## Conductor log

- 2026-10-09: Selected the two related shell-gate complexity findings from
  the seven remaining in the trap checker after the lexer batch. The guard is
  a required local and CI check, so preservation of true and false findings
  has priority over reducing lines of code.
- 2026-10-09: Six new shell-boundary cases passed against the original
  implementation. Mutating pipefail option polarity and POSIX-shell detection
  made their respective test groups fail; restoring the source and removing
  timestamp-colliding Python bytecode made both pass again.
- 2026-10-09: The refactored functions matched the previous implementation
  on 10,000 generated scripts, including exact findings. All 311 trap-checker
  unit tests, `make check-traps` over 387 files and targeted Ruff passed.
  Both mutation checks still failed as intended after the refactor.
- 2026-10-09: The full `make verify` gate passed before rebase, including
  desktop, phone and accessibility browser suites. The branch rebased cleanly
  onto the merged lexer batch. Focused post-rebase verification and final
  branch reviews are pending.
- 2026-10-09: The post-rebase trap-checker suite passed all 318 tests and
  `make check-traps` scanned 387 files. Two independent final reviews were
  clean, and the pre-push full gate passed. PR #526 passed CI and cloud review
  and merged as `d76f31e1`. The exact clean-master scan closed both targeted
  critical `python:S3776` issue keys, found no new issue keys and passed the
  quality gate. Open critical findings fell from 160 to 158. No production
  deployment was made.
- 2026-10-09: Post-merge CI, CodeQL and the authorised automatic beta build
  all passed for `d76f31e1`.
