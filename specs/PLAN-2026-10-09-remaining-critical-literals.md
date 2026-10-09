# SonarQube remaining critical Python repeated literals, 2026-10-09

## Finding

The exact clean-master scan at `0b888c8d` reports 14 critical
`python:S1192` repeated-literal findings across 12 files. They include
renamer ignore markers, downloader URL schemes, API descriptions, notification
messages, and values in a file-plugin self-check. These values cross different
behavioural boundaries, but every intended edit is an exact constant
substitution within its original module.

## Acceptance criteria

1. Share each of the 14 repeated values without changing runtime strings,
   formatting, parameter order, request headers, paths, API descriptions or
   self-check expectations.
2. For each edited module, compare its syntax tree before and after the change
   after inlining the new constant references. Relevant focused checks and the
   full repository gate pass. Any deliberate test or guard added for a gap is
   proved load-bearing by mutation.
3. Two independent local reviews find no actionable issue before push. PR, CI
   and cloud review pass, then an exact clean-master SonarQube scan confirms
   the targeted issue keys closed, no new issues, and a passing reporting
   quality gate. No production deployment.

## Tasks

- [x] R1 Inventory the 14 literal call sites and preserve their exact values; state: completed
- [x] R2 Substitute module constants and verify AST equivalence and focused behaviour; state: completed
- [ ] R3 Complete full gate, local reviews, PR, CI, merge and exact-master scan; state: queued

## Conductor log

- 2026-10-09: Selected the remaining critical Python repeated literals as a
  bulk candidate while the shell-gate complexity branch was in its pre-push
  gate. The exact issue inventory and module contexts need confirmation after
  that branch's post-merge scan before any delivery.
- 2026-10-09: Replaced the 14 exact values with module constants in 12 files.
  After inlining those constants, each module's syntax tree matches
  `origin/master`. Targeted Ruff, `git diff --check` and 299 focused unit
  tests passed. Full verification and independent review are pending.
