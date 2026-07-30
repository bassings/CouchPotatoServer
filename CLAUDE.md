# CouchPotatoServer — Claude Context

> Restructured 2026-07-13: process detail moved to `docs/development-process.md`,
> tech debt + lessons to `docs/technical-debt.md`. This file is the short core —
> read it at the start of every session.

Python 3 media management server (movie library + download automation). Fork of
the archived CouchPotato, fully modernised.

- **Repo:** https://github.com/bassings/CouchPotatoServer — default branch `master`
- **Stack:** Python 3.10+, FastAPI/Uvicorn, htmx + Tailwind + Alpine.js UI, SQLite, Docker
- **Entry point:** `CouchPotato.py`
- **Production:** http://homemedia.maeewing.com:5050 · image `ghcr.io/bassings/couchpotatoserver:latest` (Alpine, `python:3.14-alpine`)
- **Dev container port:** 5051 (`docker-compose.dev.yml`)

## Commands

| Command | Purpose |
|---|---|
| `make setup` | Once per clone: installs deps + git pre-push hook |
| `make verify` | Full local gate, mirrors CI (ruff → py unit → UI unit → E2E). Runs automatically on push via hook |
| `make verify-fast` | Quick gate: lint + unit only, skips E2E |
| `ruff check .` | Lint (must be clean before every push) |
| `pytest tests/unit/ -q` | Python unit tests |
| `./scripts/test-local.sh` | Python unit in clean Alpine Docker (optional) |
| `make mutation-py` / `make mutation-js` | Mutation testing, everything in scope (informational, slow) |
| `make mutation-changed` | Mutation testing on changed files only — use this per-change |
| `make check-traps` | False-green guard (jsdom layout reads, exit-code-eating pipes, weak shell gates) |
| `make check-secrets` | Secret scan of the working tree (same command CI runs) |
| `./scripts/backup.sh` | Snapshot prod SQLite DB + settings — run before every deploy |

## Hard rules — never break these

1. **TDD.** Write the failing test first, then code to make it pass. Tests to a
   principal developer's standard: clear names, edge cases, failure modes, no
   unnecessary mocking.
2. **Never push untested code.** `make verify` must pass locally before every
   push — don't rely on CI. Emergency hook bypass `git push --no-verify` only
   sparingly.
3. **Local agent review gate before pushing code changes.** Any code change
   (plus edits to `CLAUDE.md`/`AGENTS.md`/`specs/**`) must pass a clean-agent
   local review before push. Pure docs-only prose may skip. Full rules,
   reviewer setup, and verified-facts list: `docs/development-process.md`.
4. **Delegate implementation to Sonnet sub-agents** (`Agent` tool,
   `model: "sonnet"`). Agents edit, test, and commit locally, then **STOP — they
   never push**. The orchestrator reviews, runs the local review gate, and
   pushes. Details: `docs/development-process.md`.
5. **UI changes require E2E updates.** Check `tests/e2e/filters.spec.ts`,
   `navigation.spec.ts`, `interactions.e2e.spec.ts` — CI fails otherwise.
6. **Versioning:** betas auto-publish per commit on `master` (minor bump,
   `:beta` channel); production is a manual promotion that re-tags a tested
   beta byte-for-byte to `:latest` (stable-only). **Never deploy to
   production until explicitly agreed.**
7. **Git hygiene:** conventional commits; never commit secrets or test data
   (`test_data/` is gitignored — keep local backups). Secret scanning is
   enforced: the `secrets` CI job and `make check-secrets` run gitleaks over the
   working tree. Adding a fingerprint to `.gitleaksignore` requires a comment
   justifying it — and rotation, not redaction, is the remedy for a real key.
8. **Dockerfile is Alpine:** use `apk`/`su-exec`/`adduser`, entrypoint is
   `#!/bin/sh` — never `apt`/`gosu`/`useradd`/bash.
9. **A sub-agent's report is not evidence.** Validate against the repo, not the
   summary: read the diff, run the command yourself. When a report and the repo
   disagree, the repo wins. A report that omits something you asked for (a paste,
   a test count, a mutation result) is unverified, not done.
10. **When a test is the deliverable, run the mutation — and prove the mutation
    landed.** Break the thing the test claims to guard, watch it fail, restore.
    Then confirm the break actually applied (`git diff` / hash the file) before
    trusting either outcome — a `sed` that silently matched nothing produces a
    passing test against code you believe you reverted, which is a false green
    that looks exactly like success.
11. **After three failed fixes, question the frame, not the fix.** Each attempt
    surfacing a new defect elsewhere means the shape is wrong. Stop, say so, and
    re-open the approach instead of trying a fourth. On any branch where a fix
    has itself introduced a defect twice, treat the next fix as suspect and
    review it as new work, not as a correction.

## Key technical decisions

| Decision | What | Why |
|---|---|---|
| Database | SQLite via `SQLiteAdapter` | Replaced CodernityDB (unmaintained, Py3 issues). Vendored `libs/CodernityDB/` stays for one-time migration — don't remove |
| Web framework | FastAPI/Uvicorn | Replaced Tornado — modern async, better typing |
| UI | htmx + Tailwind + Alpine.js at `/` | Legacy `/old/` UI being retired — see `specs/UI-MIGRATION.md` |
| UI design system | `docs/design-system/README.md` | **Visual source of truth.** Conform new UI against `docs/design-system/CONFORMANCE.md` (CI-gated) |
| Container base | `python:3.14-alpine` + `su-exec` | Debian base carried ~119 OS CVEs; Alpine ships 0. Healthcheck uses Python `urllib` (no curl in image) |

### Database patterns

```python
db.get('media', 'imdb-{id}', with_doc=True)                          # media lookup
db.get('release_identifier', '{imdb}.{audio}.{quality}', with_doc=True)  # release dedup
# with_doc=True returns {'doc': ...}
```

## Where to find more

| Topic | Location |
|---|---|
| Full push/review/release process, CI checks, agent delegation | `docs/development-process.md` |
| Current technical debt + lessons learned | `docs/technical-debt.md` |
| Review rubric + agent instructions | `AGENTS.md` |
| Feature specs | `specs/` |
| QA test plan / findings / session logs | `QA/` |
| Design system | `docs/design-system/` |

## Production infrastructure

- **Server:** homemedia.maeewing.com (SSH credentials in Openclaw memory:
  `~/.openclaw/workspace/memory/topics/couchpotato.md`)
- **Compose + config:** `/var/lib/plexmediaserver/CouchPotato/` — the
  `config.bak/` directory there must **NEVER be deleted**
- **SQLite DB:** `.../config/data/database_v2/couchpotato.db`
- **Jackett:** http://homemedia:9117
