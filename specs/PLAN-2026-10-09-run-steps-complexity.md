# Workflow step walker complexity follow-up, 2026-10-09

## Finding

The exact clean-master SonarQube scan of `5b493ace4` closed the five
original `python:S3776` records targeted by PR #531, but reported a new
record on `_iter_run_steps` at `scripts/check_test_traps.py:639`. Its measured
complexity fell from 33 to 17, still above the allowed 15. The new SonarQube
issue UUID is `c96c1624-43b1-4e7a-a180-4a0f3b347b25`.

## Acceptance criteria

1. Split workflow mapping traversal from sequence traversal so a clean-master
   scan closes the remaining `S3776` record. Preserve yielded step order,
   scalar-node identity, effective shell inheritance and malformed-node
   behaviour.
2. Run the existing checker tests and compare the old and new walkers on
   generated workflow inputs and repository workflows. Any difference needs
   a focused behaviour test and explicit disposition.
3. `make check-traps`, the full local gate and two independent local reviews
   pass before push. PR, CI and cloud review pass before merge.
4. An exact clean-master scan confirms the target closes, introduces no
   distinct new finding and passes the reporting quality gate. No production
   deployment is included.

## Tasks

- [x] R1 Extract the mapping traversal and verify equivalent output
- [x] R2 Complete gate, review, PR, merge and exact-master scan; state: merged

## Conductor log

- 2026-10-09: The unmodified #531 merge passed all 318 focused checker tests.
  The extracted mapping walker passed the same 318 tests and `make
  check-traps` across 390 files. A differential run on 3,007 generated and
  repository workflows found identical returned scalar-node identities,
  shell values and checker findings. No new test or guard was added.
- 2026-10-09: PR #532 passed the full gate, two local reviews, CI and cloud
  review, then merged as `faa51b713`. Its exact scan stayed at 609 open and
  134 critical findings, with no closed or new UUIDs and a green gate. The
  target was incorrectly attributed to `_iter_run_steps`; line 639 defined
  `_default_run_shell`. The extraction was behaviour-preserving but did not
  meet the intended Sonar closure. PR #533 corrected the actual function.
