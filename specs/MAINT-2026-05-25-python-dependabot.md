# MAINT-2026-05-25: Python Dependabot Batch

## Problem

Dependabot opened five new Python dependency PRs after the 2026-05-24 maintenance pass:

- #97 `pytest-cov >=7.1.0`
- #98 `fastapi 0.136.3`
- #99 `certifi 2026.5.20`
- #100 `pydantic 2.13.4`
- #101 `pydantic-core 2.47.0`

PRs #100 and #101 are failing CI because Dependabot split a coupled dependency pair into incompatible pins:

- `pydantic 2.13.4` requires `pydantic-core == 2.46.4`
- `pydantic-core 2.47.0` is the newest standalone release, but it is not compatible with the current newest `pydantic` release

## Scope

Update the Python dependency pins in one coherent batch:

- `requirements-dev.txt`: change `pytest-cov>=4.0` to `pytest-cov>=7.1.0`
- `requirements.txt`: change `fastapi==0.135.3` to `fastapi==0.136.3`
- `requirements.txt`: change `certifi==2026.2.25` to `certifi==2026.5.20`
- `requirements.txt`: change `pydantic==2.12.5` to `pydantic==2.13.4`
- `requirements.txt`: change `pydantic_core==2.41.5` to `pydantic_core==2.46.4`

Do not apply `pydantic-core 2.47.0` unless PyPI metadata shows a matching `pydantic` release requires it.

## Acceptance Criteria

- Dependency installation succeeds without resolver conflicts.
- Full Python unit tests pass.
- Ruff passes.
- UI unit tests still pass.
- `npm audit --audit-level=moderate` still passes.
- `git diff --check` passes.

## Verification Commands

Run these before handing back:

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m ruff check .
python3 -m pytest tests/unit -q
npm run test:unit
npm audit --audit-level=moderate
git diff --check
```

If Docker is available and not already validated in this session, also run:

```bash
./scripts/test-local.sh 3.14
```
