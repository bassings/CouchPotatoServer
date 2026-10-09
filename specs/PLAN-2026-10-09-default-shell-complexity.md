# Workflow default-shell complexity correction, 2026-10-09

## Finding

The exact clean-master scan of `faa51b713` still reports `python:S3776` on
`scripts/check_test_traps.py:639`, complexity 17 against the allowed 15.
That line defines `_default_run_shell`. PR #532 extracted the neighbouring
`_iter_run_steps` mapping traversal after incorrectly attributing the warning
to that function. It caused no new SonarQube finding but did not close this
one. The remaining issue UUID is
`c96c1624-43b1-4e7a-a180-4a0f3b347b25`.

## Acceptance criteria

1. Reduce `_default_run_shell` complexity below the SonarQube limit while
   preserving the last scalar `shell` value from nested `defaults.run`
   mappings, including duplicate keys, non-mapping values and absent keys.
2. Characterise boundary cases before the refactor. Compare old and new
   output on generated and repository workflows, including yielded YAML node
   identity and all checker findings. Any behavioural difference needs a
   focused test and disposition.
3. `make check-traps`, focused tests, the full local gate and two independent
   local reviews pass before push. PR, CI and cloud review pass before merge.
4. An exact clean-master scan closes this UUID, introduces no distinct new
   finding and passes the reporting quality gate. No production deployment.

## Tasks

- [x] D1 Characterise default-shell edge cases and make the focused change
- [x] D2 Complete gate, review, PR, merge and exact-master scan; state: merged

## Conductor log

- 2026-10-09: Six new parameter cases passed on the old implementation,
  covering absent and non-mapping defaults, duplicate `run` and `shell`
  entries, and a non-scalar shell. They passed after the refactor too.
  Replacing the scalar-shell guard with an always-false condition made three
  cases fail; restoring it passed all six. The full 324-test checker suite
  passed, with all nine changed executable lines covered. Old and new
  checkers matched on 3,007 generated and repository workflow inputs.
  `make check-traps` passed across 390 files; Ruff and the secret scan passed.
- 2026-10-09: PR #533 passed the full gate, two independent local reviews,
  CI and cloud review, then merged as `0a908e769`. The exact clean-master
  scan closed the targeted `S3776` UUID with no new records, 609 to 608 open
  findings, 134 to 133 critical, 66.5% coverage and a green gate.
  Post-merge CI, CodeQL and the automatic beta build passed. No production
  deployment occurred.
