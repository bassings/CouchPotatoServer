# MAINT-2026-05-24: Python Dependabot Maintenance

## Context

Dependabot has five open Python dependency PRs that should be consolidated and validated after the npm security/a11y maintenance patch merged to `master`.

Open PRs covered by this spec:

- #86 `packaging` from `26.0` to `26.2`
- #87 `uvicorn` from `0.44.0` to `0.46.0`
- #88 `httpx` dev requirement from `>=0.27.0` to `>=0.28.1`
- #89 `python-multipart` from `0.0.27` to `0.0.28`
- #90 `cryptography` from `46.0.7` to `48.0.0`

## Scope

Update the project dependency files only as required for those versions:

- `requirements.txt`
- `requirements-dev.txt`

Do not change application code unless a test proves it is required by the dependency upgrade.

## TDD / Validation Expectations

For dependency-only maintenance, the red/green loop is compatibility verification rather than new behavioural tests.

1. Inspect existing tests that exercise server startup, multipart/form handling, packaging/version handling, HTTP clients, and cryptography-sensitive paths.
2. Apply dependency updates.
3. Run the full local validation suite:
   - `python3 -m ruff check .`
   - `.venv/bin/python -m pytest tests/unit -q`
   - `./scripts/test-local.sh 3.14`
4. If a compatibility failure appears, add or adjust the smallest focused test first, then fix the code.

## Acceptance Criteria

- The dependency versions above are reflected in the appropriate requirements files.
- No unrelated files are changed.
- Full local validation passes, or any environment-only failure is documented with exact output.
- The branch is committed with a conventional commit message.
