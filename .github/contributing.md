# Contributing to CouchPotato

Contributions are welcome! Please ensure compatibility with Python 3.10+ and include tests where practical.

## Getting Started

1. Fork the repo and clone locally
2. Create a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt -r requirements-dev.txt`
4. One-time local setup (installs git hooks + JS deps): `make setup`

## Path to Production

```
make setup → code → make verify → open PR → Claude review + remediate → approve → merge → release/deploy
```

- **`make verify`** is the local gate and mirrors CI exactly: ruff lint →
  Python unit tests → UI unit tests (vitest) → E2E (Playwright, auto-starts the
  app). Green locally means green in CI.
- A **pre-push hook** (installed by `make setup`) runs `make verify` on every
  push and blocks it on failure, so local testing passes *before* a PR exists.
  Emergency bypass: `git push --no-verify` (use sparingly).
- Quick inner loop: `make verify-fast` skips the slow E2E stage.

## Pull Requests

- Keep PRs focused on a single change
- Include tests for new functionality (principal-developer standard)
- Ensure `make verify` passes locally before opening the PR
- Every PR is auto-reviewed by **Claude** (`.github/workflows/claude-review.yml`).
  Resolve every review thread it opens — branch protection requires the
  `claude-review` check to pass + conversation resolution before merge (no
  separate human approval needed).
- Required CI checks: `lint`, `test-summary`, `ui-unit-tests`, `ui-e2e-tests`,
  `claude-review`

## Mutation Testing

Mutation testing finds behaviour your tests don't actually pin down. It runs
**nightly** (and on-demand via the *Mutation Testing* workflow) — it is
informational, never a merge gate.

- Python (mutmut): `make mutation-py`
- JS (Stryker): `make mutation-js` *(inert until Alpine/htmx components are
  extracted into importable modules under `couchpotato/static/scripts/ui/`)*

## Reporting Issues

Open a [GitHub issue](https://github.com/bassings/CouchPotatoServer/issues) with:
- Steps to reproduce
- Expected vs actual behaviour
- Python version and OS
- Relevant log output
