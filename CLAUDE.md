# CouchPotatoServer — Claude Context

> Imported from Openclaw memory (`couchpotato-project.md`, `topics/couchpotato.md`). Last updated: 2026-04-11.

## Project Overview

- **What:** Python 3 media management server (movie library + download automation)
- **Repo:** https://github.com/bassings/CouchPotatoServer
- **Stack:** Python 3.10+, FastAPI, htmx + Tailwind + Alpine.js UI, SQLite, Docker
- **Production:** http://homemedia.maeewing.com:5050
- **Docker Image:** ghcr.io/bassings/couchpotatoserver:latest (Alpine Linux base, `python:3.14-alpine`)
- **Dev container port:** 5051 (`docker-compose.dev.yml`)

---

## Development Rules (MANDATORY — read these first every session)

### 0. Delegate Implementation to Codex

- **Scott (Eggbert) plans and reviews** — architecture, specs, QA
- **Codex does the coding** — spawn sub-agents for implementation tasks

**Workflow:**
1. Write a clear spec in `specs/` (problem, fix, acceptance criteria, files)
2. Spawn Codex: `codex exec --full-auto "Read spec at specs/FEAT-XXX.md and implement. TDD: write failing test first, fix, then run ruff + pytest. When done: openclaw system event --text 'FEAT-XXX done' --mode now"`
3. Report start to user, then stop monitoring
4. Wait for completion, check result with one poll, review and commit

**DO NOT** poll logs repeatedly, read output incrementally, or narrate each Codex step.

### 1. Test Locally Before Every Push

**The gate is `make verify`** — it mirrors CI exactly (ruff → Python unit →
UI unit → E2E with auto-started server) and is the single source of truth for
"is this safe to PR". `make setup` (run once) installs a **pre-push hook** that
runs it automatically and blocks the push on failure.

```bash
make setup          # once: installs git hooks + JS deps
make verify         # full local gate (mirrors CI) — runs on every push
make verify-fast    # quick: lint + unit only, skips E2E
./scripts/test-local.sh   # optional: Python unit in clean Alpine Docker
```

**Never push untested code to remote. Never deploy untested code to production.**
Emergency hook bypass: `git push --no-verify` (use sparingly).

### Path to Production (full flow)

```
make setup → code → make verify → open PR → Claude review + remediate → approve → merge → release → deploy
```

- **PR gate:** every PR is auto-reviewed by Claude
  (`.github/workflows/claude-review.yml`, authenticated via the
  `CLAUDE_CODE_OAUTH_TOKEN` subscription secret — no API billing). Resolve every
  thread it opens; branch protection on `master` requires the `claude-review`
  check to pass + conversation resolution. No separate human approval is
  required (solo-maintainer setup), so the agent review *is* the review gate.
- **Required CI checks:** `lint`, `test-summary`, `ui-unit-tests`,
  `ui-e2e-tests`, `claude-review`, `Analyze (python)`, `Analyze (javascript)`,
  `dependency-review`, `docker`.
- **SAST / security gates:**
  - **CodeQL** (`codeql.yml`) — Python + JS static analysis, per-PR + weekly.
  - **dependency-review** (`dependency-review.yml`) — blocks PRs that add deps
    with known high/critical vulns.
  - **Trivy** image scan in the `docker` job — fails on fixable HIGH/CRITICAL
    CVEs (`ignore-unfixed`, `.trivyignore` for the DS-0002 false positive).
  - **security-lint** (ruff `S`/bandit) — INFORMATIONAL, non-blocking (~169
    legacy findings); ratchet S codes into the blocking `lint` as cleared.
  - Plus the `claude-review` prompt covers security qualitatively.
- **Note:** GitHub only runs `claude-review` with its token once the workflow
  exists on `master`; the PR that introduces/edits it is a no-op (expected).
- **Mutation testing** runs nightly + on-demand (*Mutation Testing* workflow),
  informational only: `make mutation-py` (mutmut) / `make mutation-js` (Stryker
  over the extracted UI logic in `couchpotato/static/scripts/ui/`, ~96% score).
  See `[tool.mutmut]` in `pyproject.toml` and `stryker.conf.json`.

### 1a. E2E Tests — Check for UI Changes

- E2E tests live in `tests/e2e/*.spec.ts` (Playwright)
- **No local E2E runner** — CI catches failures
- For any UI change, check these files and update them:
  - `tests/e2e/filters.spec.ts`
  - `tests/e2e/navigation.spec.ts`
  - `tests/e2e/interactions.e2e.spec.ts`

### 2. Lint Before Pushing

```bash
ruff check .   # Must be clean before every push
```

### 3. Test-Driven Development

Write failing tests first, then code to make them pass. Tests should meet a **principal developer's standard**: clear names, edge cases, failure modes, no unnecessary mocking.

### 4. Version Tagging

- Use `-beta` suffix during development: `v3.2.0-beta.1`, `v3.2.0-beta.2`, etc.
- Only drop `-beta` when ready for production
- Never deploy to production until explicitly agreed

### 5. Production Deployment Process

1. All local tests pass + lint clean
2. Push to master, wait for CI to pass
3. Tag with release version, create GitHub Release with changelog
4. SSH to server, pull new image, restart:
   ```bash
   # SSH credentials in Openclaw memory (topics/couchpotato.md)
   cd /var/lib/plexmediaserver/CouchPotato
   docker compose pull
   docker compose up -d
   docker logs couchpotato --tail=50
   ```

### 6. Git Hygiene

- Conventional commits style
- Never commit test data or secrets
- `test_data/` is gitignored — maintain local backups

---

## Key Technical Decisions

| Decision | What | Why |
|---|---|---|
| Database | SQLite via `SQLiteAdapter` | Replaced CodernityDB (unmaintained, Python 3 issues) |
| Web framework | FastAPI/Uvicorn | Replaced Tornado — modern async, better typing |
| UI | htmx + Tailwind + Alpine.js | `/` = new UI, `/old/` = classic UI |
| Container base | `python:3.14-alpine` + `su-exec` | Debian base carried ~119 OS-package CVEs (many HIGH/CRITICAL, no upstream fix); Alpine ships **0**. Healthcheck uses Python `urllib` so no `curl`/`libcurl` in the image. |

### Database Patterns

```python
# Media lookup
db.get('media', 'imdb-{id}', with_doc=True)

# Release dedup
db.get('release_identifier', '{imdb}.{audio}.{quality}', with_doc=True)

# with_doc=True returns {'doc': ...}
```

### Known Technical Debt

- 367 bare `except:` clauses
- Race conditions in read-modify-write DB patterns (see `couchpotato/core/media/main.py`)
- No CORS/CSRF protection
- Passwords now bcrypt-hashed (was plaintext before PR #44)
- API auth via URL key only, no rate limiting
- `_locks` dict on `Plugin` is a class variable shared across all instances (thread safety bug)

---

## Test Infrastructure

| Script | Purpose |
|---|---|
| `pytest tests/unit/ -q` | All unit tests |
| `ruff check .` | Linting |
| `./scripts/test-local.sh` | Full Docker container test |

- Unit tests: `pytest` + `tmp_path` fixture, no Docker needed locally
- SQLiteAdapter tests: `adapter.create(str(tmp_path / 'name'))`
- Skip `test_api_auth.py`, `test_fastapi_web.py`, `test_security.py` locally (`httpx` not installed)
- CI matrix: Python 3.10, 3.11, 3.12, 3.13

---

## QA Process

- Test plan: `QA/QA_TEST_PLAN.md`
- Findings: `QA/QA_FINDINGS.md`
- Session logs: `QA/QA_SESSION_YYYY-MM-DD.md`

Run through core flows before any release: add movie, view detail, filter/search wanted list, settings tabs, searcher/downloader connections, suggestions.

---

## Infrastructure

- **Server:** homemedia.maeewing.com (credentials in Openclaw: `~/.openclaw/workspace/memory/topics/couchpotato.md`)
- **Docker compose:** `/var/lib/plexmediaserver/CouchPotato/docker-compose.yml`
- **Config:** `/var/lib/plexmediaserver/CouchPotato/config/`
- **Config backup:** `/var/lib/plexmediaserver/CouchPotato/config.bak/` — **NEVER DELETE**
- **SQLite DB:** `/var/lib/plexmediaserver/CouchPotato/config/data/database_v2/couchpotato.db`
- **Jackett:** http://homemedia:9117

---

## Codex Delegation

```bash
codex exec -s danger-full-access -a never -C ~/repos/CouchPotatoServer
```

- Codex handles: file edits, test validation, commit, push, Docker rebuild
- **Hallucination risk:** Codex may invent package versions — always verify with `pip index versions <pkg>`
- **Docker timing:** Docker Desktop takes 1-2 min to fully start — start it early

---

## Lessons Learned

1. Read this file at the START of every session before touching code
2. Always run `pytest tests/unit/ -q` + `ruff check .` before pushing — don't rely on CI
3. For UI changes, update `tests/e2e/` or CI will fail
4. Spawn Codex for implementation; don't do it yourself (rate limits)
5. `diskcache` was replaced with `SQLiteCache` (CVE-2025-69872 — pickle RCE, lib abandoned)
6. Branch protection check names must match exactly — matrix jobs report as `test (3.10)`, not `test`
7. Dependabot PRs may need `--admin` merge if they predate CI changes
8. Docker image is **Alpine**-based: use `apk`/`su-exec`/`adduser` in the Dockerfile, not `apt`/`gosu`/`useradd`. The entrypoint is `#!/bin/sh` (no bash). Heavy deps (cryptography, lxml, bcrypt, pydantic-core) all ship `musllinux` wheels, so multi-arch builds don't compile from source.
9. Scan the image before release: `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --scanners vuln <image>`. Target 0 CVEs. `.trivyignore` suppresses only the DS-0002 misconfig false positive (gosu/su-exec privilege-drop pattern).
