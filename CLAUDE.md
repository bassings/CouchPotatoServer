# CouchPotatoServer — Claude Context

> Imported from Openclaw memory (`couchpotato-project.md`, `topics/couchpotato.md`). Last updated: 2026-04-11.

## Project Overview

- **What:** Python 3 media management server (movie library + download automation)
- **Repo:** https://github.com/bassings/CouchPotatoServer
- **Stack:** Python 3.10+, FastAPI, htmx + Tailwind + Alpine.js UI, SQLite, Docker
- **Production:** http://homemedia.maeewing.com:5050
- **Docker Image:** ghcr.io/bassings/couchpotatoserver:latest
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

```bash
python3 -m pytest tests/unit/ -q   # ALL unit tests
python3 -m ruff check .            # Lint
# Or full Docker test:
./scripts/test-local.sh
```

**Never push untested code to remote. Never deploy untested code to production.**

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
