# SonarQube test-trap lexer complexity, 2026-10-09

## Finding

The clean-master SonarQube analysis at `e1f9fe94` reports nine critical
`python:S3776` findings in `scripts/check_test_traps.py`. Two are the shell
and JavaScript comment strippers, at cognitive complexity 26 and 47. These
lexers protect test and shell gates from false-green results: mishandling a
quote or comment can hide an actual runner or browser assertion.

## Acceptance criteria

1. Refactor `strip_shell_comments` and `strip_js_comments` so each function
   falls at or below SonarQube's complexity limit of 15, without changing
   their outputs for existing or new boundary cases.
2. Add focused characterisation tests for shell quoting, escapes and comment
   boundaries, and JavaScript strings, templates, line and block comments.
   Deliberately mutate a protected branch, confirm the test fails, restore
   the source and confirm it passes.
3. The test-trap checker catches its own known false-green fixtures and
   `make check-traps`, focused unit tests, the full local gate and two
   independent local reviews pass before push.
4. PR, CI and cloud review pass. A post-merge clean-master scan confirms
   exact issue-key closure and checks for new findings. No production
   deployment.

## Tasks

- [x] T1 Characterise both lexers and prove tests catch a mutation; state: verified
- [x] T2 Refactor both lexers and pass focused checks; state: completed
- [ ] T3 Complete full gate, review, PR, CI, merge and exact-master scan; state: building

## Conductor log

- 2026-10-09: Selected two of nine critical complexity findings in the
  test-trap checker. They share the comment-stripping boundary but have
  different language rules; the batch preserves each lexer contract and
  leaves the other seven functions for later scoped work.
- 2026-10-09: Seven direct lexer cases passed before refactoring. Disabling
  shell escaped-character handling made one new shell case fail. Disabling
  JavaScript line-comment reset made two new cases fail. Each mutation was
  confirmed applied, restored in a `finally` block and followed by passing
  tests on the restored source.
- 2026-10-09: The refactored lexers matched their previous outputs on 10,000
  generated inputs, all 312 focused trap-checker tests and `make check-traps`
  passed, and the full `make verify` gate passed before rebase onto the next
  clean master. Independent review and post-rebase verification remain.
