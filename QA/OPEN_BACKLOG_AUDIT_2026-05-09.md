# Open Backlog Audit - 2026-05-09

Branch: `qa/open-backlog-audit-agent`  
Base HEAD audited: `899976b9fe086d4ef0f5fb750cbd03bfcff8d226`

## Summary

Release readiness is **not fully clear**. GitHub issues and PRs are empty and Dependabot has no open alerts, but CodeQL still reports open high-severity alerts and the latest `master` CI run is still in progress on the UI E2E job.

The local QA branch also contains uncommitted feature implementation work for movie collections and watch history. That work should not be treated as part of this audit commit or a release candidate until it is reviewed, tested, and committed on its own feature branch.

## Blockers / release gates

1. **Open CodeQL alerts remain**
   - `#83` `py/weak-sensitive-data-hashing` in `couchpotato/core/helpers/variable.py:107`
   - `#82` `py/path-injection` in `couchpotato/__init__.py:247`
   - `#81` `py/path-injection` in `couchpotato/__init__.py:246`
   - `#80` `py/clear-text-storage-sensitive-data` in `couchpotato/__init__.py:352`
   - `#79` `py/incomplete-url-substring-sanitization` in `tests/unit/test_providers.py:554`
   - `#78` `py/incomplete-url-substring-sanitization` in `tests/unit/test_provider_tests.py:164`
   - `#14` `py/clear-text-storage-sensitive-data` in `couchpotato/core/downloaders/pneumatic.py:60`
   - `#11` `js/redos` in `couchpotato/static/scripts/vendor/mootools.js:1450`
   - `#9` `js/incomplete-multi-character-sanitization` in `couchpotato/static/scripts/vendor/mootools.js:1149`
   - `#7` `js/bad-tag-filter` in `couchpotato/static/scripts/vendor/mootools.js:1149`

2. **Latest master CI run is not complete**
   - Run: <https://github.com/bassings/CouchPotatoServer/actions/runs/25587528414>
   - Completed successfully: lint, UI unit tests, Python tests on 3.10 to 3.13, test summary, Docker.
   - Still in progress when checked: `ui-e2e-tests`.

3. **Local verification environment is incomplete**
   - `pytest tests/unit -q` failed during collection because local Python is missing development/runtime packages including `httpx` and `bcrypt`.
   - `ruff check .` could not run because `ruff` is not installed in the active shell.
   - `npm test -- --run` started Playwright E2E and failed because local Playwright browser binaries are missing for Firefox/WebKit. `npm run test:unit` passed.

4. **Dirty local worktree on the QA branch**
   - Uncommitted code exists in DB, media, UI, and collection/watch-history files.
   - Treat this as separate feature work, not as part of release readiness.

## Deferred enhancements / non-blocking backlog

These items are not represented by open GitHub issues or PRs, but still appear in repository QA/spec documentation or local uncommitted work:

- Movie collections, tracked in `QA/QA_FINDINGS.md` as `FEAT-001`. Local uncommitted implementation and tests are present, but not release-ready as-is.
- Watch history integration, tracked in `QA/QA_FINDINGS.md` as `FEAT-002`. Local uncommitted implementation and tests are present, but not release-ready as-is.
- Remaining spec files in `specs/` include older unchecked acceptance criteria for `BUG-012`, `BUG-013`, `FEAT-001`, `FEAT-002`, `FEAT-003`, and `SEC-001` to `SEC-003`. Several appear implemented on `master`, but the spec files themselves have not been reconciled.
- `QA/QA_TEST_PLAN.md` remains a broad manual regression checklist, not a closed release gate.

## Checks performed

- Inspected local branch and git state.
- Searched repo QA/docs/spec files for TODOs, open checklist items, defect IDs, feature IDs, and stale status.
- Queried GitHub issues and PRs with `gh`: no open issues or PRs.
- Queried Dependabot alerts with `gh api`: no open Dependabot alerts returned.
- Queried CodeQL alerts with `gh api`: 10 open alerts returned.
- Queried recent GitHub Actions runs with `gh run list` and `gh run view`.
- Ran `npm run test:unit`: 19 Vitest tests passed.
- Attempted Python unit tests: blocked by missing local dependencies.
- Attempted `ruff check .`: blocked by missing local `ruff` executable.
- Attempted full npm test command: blocked at Playwright E2E browser binary setup.

## Recommended release / deploy steps

1. Do not deploy from `qa/open-backlog-audit-agent` while the worktree is dirty.
2. Wait for latest master CI run `25587528414` to finish, especially `ui-e2e-tests`.
3. Resolve or formally dismiss the 10 open CodeQL alerts before declaring the release clean.
4. Re-run release gates in a clean environment with dev dependencies installed:
   - `pip install -r requirements.txt -r requirements-dev.txt`
   - `ruff check .`
   - `pytest tests/unit -q`
   - `npm run test:unit`
   - `npx playwright install` then `npm run test:e2e` if local browser E2E is required.
5. Split movie collections and watch history into dedicated feature branches or discard local changes before final release tagging.
