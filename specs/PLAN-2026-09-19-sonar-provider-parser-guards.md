# Sonar provider parser guards

## Goal

Resolve or evidence the three open `python:S8904` reliability findings in the
torrent-provider parsers without changing successful parsing or exposing
provider credentials.

## Acceptance criteria

- [x] AC-REL-1: Pirate Bay binds the optional pagination element and checks it
  before dereferencing it. Missing pagination retains the initialized
  one-page fallback and valid first-page results.
- [x] AC-REL-2: Focused malformed-markup tests characterize Pirate Bay's
  missing-pagination fallback, Awesome-HD's guarded error response, and
  BiT-HDTV's empty-description fallback when its detail table is absent.
- [x] AC-REL-3: Removing Pirate Bay's explicit guard makes the focused
  missing-pagination test fail; restoring it returns the test to green.
- [ ] AC-REL-4: Exact-master Sonar closes Pirate Bay issue
  `9a4242f8-9116-4918-b6f5-62a9605c5eb4` as fixed.
- [ ] AC-REL-5: Awesome-HD issue
  `1c41c0a5-e98b-4b0f-b096-6ad69a791362` is accepted only as a false
  positive: the same parsed tree is queried in the preceding condition before
  `get_text()` and an error response returns without appending results.
- [ ] AC-REL-6: BiT-HDTV issue
  `098a9262-bae6-4635-a752-2558c71d2f2b` is accepted only as a false
  positive: the conditional expression dereferences `nfo_pre` only on its
  truthy branch and otherwise assigns an empty description.
- [x] AC-SEC-1: No response bodies, request URLs, passkeys, cookies, media
  titles, or local paths are newly logged.
- [x] AC-SIMP-1: Production changes are confined to Pirate Bay's pagination
  block; no helper, dependency, AST rule, or adjacent parser cleanup is added.

## Evidence and decisions

- The pre-change focused characterization suite passed (5 tests). The behavior
  was already safe because a broad inner exception handler retained
  `total_pages = 1`; the defect is exception-driven control flow, so claiming a
  naturally failing behavioral test would be inaccurate.
- Prior T39 analysis in `specs/REMEDIATION-2026-08.md` independently classified
  Awesome-HD and BiT-HDTV as guarded false positives and Pirate Bay as a
  tolerated dereference.
- The security, QA, and simplicity planning lenses agreed that Pirate Bay is
  the only production edit needed. False-positive transitions remain deferred
  until the fixed exact-master analysis is available.
