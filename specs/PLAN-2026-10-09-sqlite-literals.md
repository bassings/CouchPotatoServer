# SonarQube SQLite adapter repeated literals, 2026-10-09

## Finding

The clean-master SonarQube analysis at `880b5398` reports five critical
`python:S1192` findings in `couchpotato/core/db/sqlite_adapter.py`: the
database filename, the base media and release queries, the media-title order
clause and the release-identifier predicate. The repeated SQL lives in the
active `_query_index` path, so changing its text or parameter order could
return the wrong media or release record.

## Acceptance criteria

1. Share all five literal values without changing their exact text, query
   assembly, bound parameters, row order or persistence behaviour.
2. Focused SQLite query and database tests pass. Attempt the configured
   Python mutation runner for this in-scope file and inspect any survivors.
   If its sandbox cannot collect the configured tests, record the cause and
   prove each shared literal with a deliberate mutation. The full repository
   gate and two independent local reviews pass before push.
3. PR, CI and cloud reviews pass, the change merges, and a post-merge
   clean-master SonarQube analysis confirms the exact closed issue keys and
   checks for new findings. No production deployment.

## Tasks

- [x] D1 Share the five exact literal values; state: verified
- [x] D2 Verify query behaviour, mutation results and full gate; state: verified
- [x] D3 Complete independent review, PR, CI, merge and post-merge scan; state: completed

## Conductor log

- 2026-10-09: Grouped five critical repeated-literal records from the
  `880b5398` clean-master issue snapshot. The active adapter is a data-loss
  priority area, so query behaviour and mutation survivors require review.
- 2026-10-09: Shared the five exact values as module constants; 115 focused
  SQLite and release-backend tests pass, as does targeted ruff. Mutation and
  the full gate remain pending.
- 2026-10-09: The configured `make mutation-changed` selected the adapter but
  could not collect its all-unit stats run inside mutmut's copied sandbox.
  Copying the tracked repository roots and providing local JavaScript modules
  resolved import and checker errors, but a unit test that requires a Git
  worktree root still failed under `mutants/`. The temporary config change was
  removed; no mutation-survivor report was produced. Manual mutations of the
  filename, media query, release query and release identifier predicate each
  failed existing database tests. The media-title order mutation survived, so
  three parameterised real-database index tests were added; the mutation then
  failed all three and the source was restored.
- 2026-10-09: Focused database and release tests passed (118). The full
  `make verify` gate passed: 4,836 Python unit tests, 42 integration tests,
  311 UI unit tests, 227 desktop browser tests, 2 isolation tests, 24 phone
  tests and 126 accessibility tests. The non-blocking security-lint inventory
  reported 137 existing findings.
- 2026-10-09: Two independent local reviews, PR #521 checks and cloud review
  passed. The change merged as `9c28e5ee`. The exact clean-master scan closed
  all five targeted critical issue keys, found no new issues and passed the
  quality gate. No production deployment occurred.
