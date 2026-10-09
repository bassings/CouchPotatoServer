# SonarQube covered critical Python repeated literals, 2026-10-09

## Finding

The exact clean-master scan at `0b888c8d` reports 14 critical
`python:S1192` repeated-literal findings across 12 files. Seven of them are
in six modules where the affected executable lines already have full-suite
coverage: the rTorrent URL scheme, Trakt content type, movie-search API
description, Plex setting description, file-plugin self-check paths and
soft-chroot error text. These values can be shared in one bounded batch.

## Acceptance criteria

1. Share these seven repeated values without changing runtime strings,
   formatting, parameter order, request headers, paths, API descriptions or
   self-check expectations.
2. For each edited module, compare its syntax tree before and after the change
   after inlining the new constant references. Relevant focused checks, fresh
   changed-line coverage at or above 80%, and the full repository gate pass.
   Any deliberate test or guard added for a gap is proved load-bearing by
   mutation.
3. Two independent local reviews find no actionable issue before push. PR, CI
   and cloud review pass, then an exact clean-master SonarQube scan confirms
   the targeted issue keys closed, no new issues, and a passing reporting
   quality gate. No production deployment.

## Tasks

- [x] R1 Inventory the seven covered literal call sites and preserve their exact values; state: completed
- [x] R2 Substitute module constants and verify AST equivalence and focused behaviour; state: completed
- [ ] R3 Complete full gate, local reviews, PR, CI, merge and exact-master scan; state: queued

## Conductor log

- 2026-10-09: Selected the remaining critical Python repeated literals as a
  bulk candidate while the shell-gate complexity branch was in its pre-push
  gate. The exact issue inventory and module contexts need confirmation after
  that branch's post-merge scan before any delivery.
- 2026-10-09: An initial 14-value substitution matched all 12 original module
  syntax trees after inlining constants, and 299 focused tests passed. A fresh
  full-suite coverage run exposed one structural rTorrent test that expected a
  literal AST node, plus only 22/48 covered changed executable lines (45.8%).
  The six low-coverage modules were removed from this delivery branch and
  preserved on `refactor/sonar-remaining-literals-all` for a separate batch
  with meaningful tests. This branch retains seven findings in six modules.
- 2026-10-09: The rTorrent guard now resolves the shared scheme constant and
  still checks the tuple-prefix call. Changing the constant to a wrong scheme
  made the guard fail; restoring it passed. Fresh `make coverage` passed with
  4,907 Python tests; all 15 changed executable production lines are covered
  in `coverage.xml`. Full verification and independent review remain pending.
