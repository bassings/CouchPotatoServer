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

### 0. Delegate Implementation to Sonnet 5 Agents

- **Scott (Eggbert) plans and reviews** — architecture, specs, QA
- **Claude Sonnet 5 sub-agents do the coding** — spawn agents (via the `Agent`
  tool with `model: "sonnet"`, which resolves to `claude-sonnet-5`) for
  implementation tasks

**Workflow:**
1. Write a clear spec in `specs/` (problem, fix, acceptance criteria, files)
2. Spawn one or more Sonnet 5 sub-agents to implement the spec. TDD: write the
   failing test first, make it pass, then run `ruff` + `pytest`. The agent must
   **STOP after committing locally — it does not push** (the local-review gate
   still applies; see Path to Production).
3. Report start to user, then stop monitoring
4. Wait for completion, review the diff and commit; for code changes, run the
   local-agent review and push only once it passes (see Path to Production)

**DO NOT** poll the agent transcript repeatedly, read output incrementally, or
narrate each step.

### 1. Test Locally Before Every Push

**`make verify`** mirrors CI exactly (ruff → Python unit → UI unit → E2E with
auto-started server) and is the single source of truth for *"do the tests/lint
pass"*. It is **not** the only pre-push gate: for code changes a clean-agent
local review must also pass first (see Path to Production). `make setup` (run
once) installs a **pre-push hook** that runs `make verify` automatically and
blocks the push on failure.

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
make setup → code → make verify → LOCAL agent review (must pass) → push/open PR →
  cloud claude-review → (findings? fix → LOCAL review again → push) → merge → release → deploy
```

> **The rule, stated plainly — never skip it: any push that needs the gate does
> not happen until its clean-agent local review is clean.** ("Needs the gate" =
> any code change, or a change touching `CLAUDE.md`/`AGENTS.md` or a `specs/**`
> file; **pure docs-only prose may skip** — see the carve-out in the bullet just
> below.) For a gated push the loop is: run the local review → fix every real
> finding → re-verify → **re-run the local review** → repeat **until it comes
> back clean**, and only *then* `git push`. Running the review agents *is* the
> gate — self-verifying the diff yourself does **not** substitute for it. This
> governs **every** gated push, not just the first:
> - the **initial** PR push;
> - **every fix commit** pushed in response to a cloud `claude-review` finding —
>   fix → local review again until clean → push; never fix-and-push without
>   re-reviewing. (But apply the **Exit condition** below for a genuine false
>   alarm / marginal nit: reject it with evidence and stop — don't chase forever.)
> - any push touching `CLAUDE.md`/`AGENTS.md` or a `specs/**` file.
>
> Pushing before the local review is clean defeats the point: the cloud reviewer
> is stateless per push, so it dribbles out — one push at a time — the findings a
> single local pass would have surfaced together (Rationale in the gate bullet
> below).

- **Local agent review gate (MANDATORY for code changes, before every push to the
  cloud review; docs-only changes may skip it and push directly):**
  *"Docs-only"* means the diff touches **only** documentation prose — `*.md`
  **outside** `specs/**`, or files under `docs/**` — and nothing else, **except
  the policy docs `CLAUDE.md` and `AGENTS.md`**, which define how we work and so
  are treated as code-changes (run the gate) even though they are markdown. A
  change touching any code, template, test, config, or workflow file, **or any
  `specs/**` file (including a `specs/*.md` spec, which accompanies code)** —
  even alongside docs — is a **code change** and the gate applies. When in
  doubt, run the gate.
  Run a clean-agent review on the full branch diff (vs `master`) and make it pass
  *before* pushing to the `claude-review` gate. Spawn ≥2 independent review
  subagents (`general-purpose`, which can both read and reason about the diff —
  not `Explore`, which is search-only) in parallel (e.g. one frontend/a11y, one
  backend/tests) against the diff with the AGENTS.md rubric. Give them the **currently-verified facts** so they don't
  re-litigate things already confirmed *for the code as it stands* — but
  **re-verify each fact against the tree before relying on it**; these are
  point-in-time, not eternal, and a dependency bump or refactor can invalidate
  any of them. As of 2026-06 (verify before reuse): htmx 2.0.4 dual-dispatches
  camelCase+kebab so `@htmx:*` kebab handlers fire (check the bundled
  `htmx-*.min.js` if the version changes); `callApiHandler` returns
  `{'success': False}` instead of raising (check `couchpotato/api.py`); `CPLog`
  has no `.exception()` (check `couchpotato/core/logger.py`); CP.ui loads before
  Alpine in `base.html`. A fact that no longer holds is a real finding, not a
  false alarm — never suppress on the say-so of this list alone. Fix everything
  real they surface, re-verify locally, and re-review until clean. **If the cloud
  review later raises anything, fix it and run the local review again until it
  passes — then push.** **Exit condition (avoid an infinite loop):** if the cloud
  review keeps flagging a point the local review clears, investigate it once
  more; if it's a verified false alarm (or a marginal/subjective nit on a
  low-risk change), reject it with evidence in the PR thread, resolve the thread,
  and **stop** — do not keep pushing. A stateless reviewer will always find "one
  more" angle; converge on substance, not on silencing every comment. Rationale: cloud `claude-review` is stateless per push,
  so each push re-discovers the same already-cleared points and dribbles out
  genuine findings one at a time; the local loop front-loads that discovery and
  collapses many serial ~15-min cloud rounds into one. This gate is
  **policy/agent-enforced, not hook-enforced**: the `make setup` pre-push hook
  only runs `make verify` and cannot tell whether the local agent review ran —
  honour the gate as a rule, don't rely on the hook to block a gate-less push.
- **PR gate:** every PR is auto-reviewed by Claude
  (`.github/workflows/claude-review.yml`, authenticated via the
  `CLAUDE_CODE_OAUTH_TOKEN` subscription secret — no API billing). Resolve every
  thread it opens; branch protection on `master` requires the `claude-review`
  check to pass + conversation resolution. No separate human approval is
  required (solo-maintainer setup), so the agent review *is* the review gate.
- **Required CI checks:** `lint`, `test-summary`, `ui-unit-tests`,
  `ui-e2e-tests`, `claude-review`, `Analyze (python)`, `Analyze (javascript)`,
  `dependency-review`, `docker`, `accessibility` (axe), `conformance`
  (`scripts/check_conformance.py` — design-system drift gate, added in #147).
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
- **E2E run locally** — `make verify` runs them with an auto-started server, or
  run directly against a booted app:
  `.venv/bin/python CouchPotato.py --data_dir=.e2e-data --console_log` then
  `CP_TEST_URL=http://localhost:5050 npx playwright test tests/e2e/<spec> --project=chromium --workers=1`.
  CI also runs the full suite. (See also AGENTS.md's local-verification step,
  which runs the whole suite via `npm run test:e2e`.)
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
| UI | htmx + Tailwind + Alpine.js | `/` = new UI (the only UI; legacy `/old/` is being retired — see `specs/UI-MIGRATION.md`) |
| UI design system | `docs/design-system/README.md` is the **visual source of truth** | Tokens, typography, iconography (Heroicons), components, motion, a11y — extracted from `base.html`. Conform new UI against `docs/design-system/CONFORMANCE.md`. |
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
- `test_api_auth.py`, `test_fastapi_web.py`, `test_security.py` run locally too —
  `httpx` is installed in `.venv` (run via `.venv/bin/python -m pytest`)
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

## Sonnet 5 Agent Delegation

Spawn implementation sub-agents via the `Agent` tool with `model: "sonnet"` (this
resolves to `claude-sonnet-5`). Use `general-purpose` agents that can both edit
and reason about the code.

- Agents handle: file edits, test validation, and local commit.
- **Local-review gate still applies (see Path to Production):** an implementation
  agent must NOT push for code changes. It stops after committing locally; the
  orchestrator runs the clean-agent local review and only pushes once it passes.
  (Docs-only changes may skip the local review and push directly.)
- **Hallucination risk:** agents may invent package versions — always verify with `pip index versions <pkg>`
- **Docker timing:** Docker Desktop takes 1-2 min to fully start — start it early

---

## Lessons Learned

1. Read this file at the START of every session before touching code
2. Always run `pytest tests/unit/ -q` + `ruff check .` before pushing — don't rely on CI
3. For UI changes, update `tests/e2e/` or CI will fail
4. Spawn Sonnet 5 sub-agents (`Agent` tool, `model: "sonnet"`) for implementation; don't do it all inline
5. `diskcache` was replaced with `SQLiteCache` (CVE-2025-69872 — pickle RCE, lib abandoned)
6. Branch protection check names must match exactly — matrix jobs report as `test (3.10)`, not `test`
7. Dependabot PRs may need `--admin` merge if they predate CI changes
8. Docker image is **Alpine**-based: use `apk`/`su-exec`/`adduser` in the Dockerfile, not `apt`/`gosu`/`useradd`. The entrypoint is `#!/bin/sh` (no bash). Heavy deps (cryptography, lxml, bcrypt, pydantic-core) all ship `musllinux` wheels, so multi-arch builds don't compile from source.
9. Scan the image before release: `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --scanners vuln <image>`. Target 0 CVEs. `.trivyignore` suppresses only the DS-0002 misconfig false positive (gosu/su-exec privilege-drop pattern).
