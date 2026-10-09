# SonarQube media-module repeated literals, 2026-10-09

## Finding

The current clean-master analysis reports six critical `python:S1192`
findings in `couchpotato/core/media/_base/media/main.py`. Three are public API
documentation values and three are error response strings used by Mark Done,
Mark Watched and Mark Unwatched. Their repeated values can be shared without
changing the documented API or response text.

## Acceptance criteria

1. Share the six reported literal values through clear module constants, with
   no change to API documentation or error response values.
2. Relevant media tests and the repository verification gate pass. Independent
   local review confirms the diff before push.
3. PR, CI and cloud review pass, the change merges, and an exact clean-master
   SonarQube analysis confirms which issue records closed.

## Tasks

- [x] M1 Replace all six repeated values. — state: building
- [x] M2 Verify and independently review the branch. — state: building
- [ ] M3 Deliver PR and confirm post-merge analysis. — state: building

## Conductor log

- 2026-10-09: Grouped six critical `python:S1192` records in the media module
  from the post-`#517` clean-master issue snapshot. Production deployment is
  outside this plan.
- 2026-10-09: Replaced the six repeated values with module constants. All 18
  focused media tests and ruff pass. The post-`#518` scan closed the NZBGet
  complexity issue with no new findings; this branch remains based on that
  exact merged revision.
- 2026-10-09: Two independent reviewers confirmed the constants preserve the
  source module's syntax tree after inlining and found no material issue. The
  first full gate collided with another worktree's browser server on port
  5150 and correctly refused to test against it. The isolated rerun passed:
  4,833 Python unit tests, 42 integration tests, 311 UI unit tests, 227 desktop,
  2 isolation, 24 phone-width and 126 accessibility browser tests. Repeat
  local review of this status update is required before push.
