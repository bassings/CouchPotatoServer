# Development Process — Path to Production

> Moved out of `CLAUDE.md` on 2026-07-13 during a restructure. This is the full,
> authoritative description of the push/review/deploy process. `CLAUDE.md` holds
> the short version; when in doubt, this file governs.

## The full flow

```
make setup → code → make verify → LOCAL agent review (must pass) → push/open PR →
  cloud claude-review → (findings? fix → LOCAL review again → push) → merge → release → deploy
```

> **The rule, stated plainly — never skip it: any push that needs the gate does
> not happen until its clean-agent local review is clean.** ("Needs the gate" =
> any code change, or a change touching `CLAUDE.md`/`AGENTS.md` or a `specs/**`
> file; **pure docs-only prose may skip** — see the carve-out below.) For a
> gated push the loop is: run the local review → fix every real finding →
> re-verify → **re-run the local review** → repeat **until it comes back
> clean**, and only *then* `git push`. Running the review agents *is* the gate —
> self-verifying the diff yourself does **not** substitute for it. This governs
> **every** gated push, not just the first:
> - the **initial** PR push;
> - **every fix commit** pushed in response to a cloud `claude-review` finding —
>   fix → local review again until clean → push; never fix-and-push without
>   re-reviewing. (But apply the **Exit condition** below for a genuine false
>   alarm / marginal nit: reject it with evidence and stop — don't chase forever.)
> - any push touching `CLAUDE.md`/`AGENTS.md` or a `specs/**` file.
>
> Pushing before the local review is clean defeats the point: the cloud reviewer
> is stateless per push, so it dribbles out — one push at a time — the findings a
> single local pass would have surfaced together.

## Local agent review gate

**MANDATORY for code changes, before every push to the cloud review; docs-only
changes may skip it and push directly.**

*"Docs-only"* means the diff touches **only** documentation prose — `*.md`
**outside** `specs/**`, or files under `docs/**` — and nothing else, **except
the policy docs `CLAUDE.md` and `AGENTS.md`**, which define how we work and so
are treated as code-changes (run the gate) even though they are markdown. A
change touching any code, template, test, config, or workflow file, **or any
`specs/**` file (including a `specs/*.md` spec, which accompanies code)** —
even alongside docs — is a **code change** and the gate applies. When in doubt,
run the gate.

Run a clean-agent review on the full branch diff (vs `master`) and make it pass
*before* pushing to the `claude-review` gate. Spawn ≥2 independent review
subagents (`general-purpose`, which can both read and reason about the diff —
not `Explore`, which is search-only) in parallel (e.g. one frontend/a11y, one
backend/tests) against the diff with the AGENTS.md rubric.

Give the reviewers the **currently-verified facts** below so they don't
re-litigate things already confirmed *for the code as it stands* — but
**re-verify each fact against the tree before relying on it**; these are
point-in-time, not eternal, and a dependency bump or refactor can invalidate
any of them. A fact that no longer holds is a real finding, not a false alarm —
never suppress on the say-so of this list alone.

As of 2026-06 (verify before reuse):
- htmx 2.0.4 dual-dispatches camelCase+kebab so `@htmx:*` kebab handlers fire
  (check the bundled `htmx-*.min.js` if the version changes);
- `callApiHandler` returns `{'success': False}` instead of raising
  (check `couchpotato/api.py`);
- `CPLog` has no `.exception()` (check `couchpotato/core/logger.py`);
- CP.ui loads before Alpine in `base.html`.

Fix everything real the reviewers surface, re-verify locally, and re-review
until clean. **If the cloud review later raises anything, fix it and run the
local review again until it passes — then push.**

**Exit condition (avoid an infinite loop):** if the cloud review keeps flagging
a point the local review clears, investigate it once more; if it's a verified
false alarm (or a marginal/subjective nit on a low-risk change), reject it with
evidence in the PR thread, resolve the thread, and **stop** — do not keep
pushing. A stateless reviewer will always find "one more" angle; converge on
substance, not on silencing every comment.

Rationale: cloud `claude-review` is stateless per push, so each push
re-discovers the same already-cleared points and dribbles out genuine findings
one at a time; the local loop front-loads that discovery and collapses many
serial ~15-min cloud rounds into one.

This gate is **policy/agent-enforced, not hook-enforced**: the `make setup`
pre-push hook only runs `make verify` and cannot tell whether the local agent
review ran — honour the gate as a rule, don't rely on the hook to block a
gate-less push.

## PR gate (cloud review)

Every PR is auto-reviewed by Claude (`.github/workflows/claude-review.yml`,
authenticated via the `CLAUDE_CODE_OAUTH_TOKEN` subscription secret — no API
billing). Resolve every thread it opens; branch protection on `master` requires
the `claude-review` check to pass + conversation resolution. No separate human
approval is required (solo-maintainer setup), so the agent review *is* the
review gate.

**Note:** GitHub only runs `claude-review` with its token once the workflow
exists on `master`; the PR that introduces/edits it is a no-op (expected).

## Required CI checks

`lint`, `test-summary`, `ui-unit-tests`, `ui-e2e-tests`, `claude-review`,
`Analyze (python)`, `Analyze (javascript)`, `dependency-review`, `docker`,
`accessibility` (axe), `conformance` (`scripts/check_conformance.py` —
design-system drift gate, added in #147).

## SAST / security gates

- **CodeQL** (`codeql.yml`) — Python + JS static analysis, per-PR + weekly.
- **dependency-review** (`dependency-review.yml`) — blocks PRs that add deps
  with known high/critical vulns.
- **Trivy** image scan in the `docker` job — fails on fixable HIGH/CRITICAL
  CVEs (`ignore-unfixed`, `.trivyignore` for the DS-0002 false positive).
- **security-lint** (ruff `S`/bandit) — INFORMATIONAL, non-blocking (~169
  legacy findings); ratchet S codes into the blocking `lint` as cleared.
- Plus the `claude-review` prompt covers security qualitatively.

## Mutation testing

Runs nightly + on-demand (*Mutation Testing* workflow), informational only:
`make mutation-py` (mutmut) / `make mutation-js` (Stryker over the extracted UI
logic in `couchpotato/static/scripts/ui/`, ~96% score). See `[tool.mutmut]` in
`pyproject.toml` and `stryker.conf.json`.

## E2E tests

- E2E tests live in `tests/e2e/*.spec.ts` (Playwright).
- `make verify` runs them with an auto-started server, or run directly against
  a booted app:
  `.venv/bin/python CouchPotato.py --data_dir=.e2e-data --console_log` then
  `CP_TEST_URL=http://localhost:5050 npx playwright test tests/e2e/<spec> --project=chromium --workers=1`.
- CI also runs the full suite. (See also AGENTS.md's local-verification step,
  which runs the whole suite via `npm run test:e2e`.)
- For any UI change, check and update:
  - `tests/e2e/filters.spec.ts`
  - `tests/e2e/navigation.spec.ts`
  - `tests/e2e/interactions.e2e.spec.ts`

## Sonnet agent delegation

Scott (Eggbert) plans and reviews — architecture, specs, QA. Claude Sonnet
sub-agents do the coding: spawn agents (via the `Agent` tool with
`model: "sonnet"`) for implementation tasks. Use `general-purpose` agents that
can both edit and reason about the code.

Workflow:
1. Write a clear spec in `specs/` (problem, fix, acceptance criteria, files).
2. Spawn one or more Sonnet sub-agents to implement the spec. TDD: write the
   failing test first, make it pass, then run `ruff` + `pytest`. The agent must
   **STOP after committing locally — it does not push** (the local-review gate
   still applies).
3. Report start to user, then stop monitoring — do NOT poll the agent
   transcript repeatedly, read output incrementally, or narrate each step.
4. Wait for completion, review the diff; run the local-agent review and push
   only once it passes.

Notes:
- **Hallucination risk:** agents may invent package versions — always verify
  with `pip index versions <pkg>`.
- **Docker timing:** Docker Desktop takes 1–2 min to fully start — start it early.

## Release & production deployment

1. All local tests pass + lint clean.
2. Push to master, wait for CI to pass.
3. Tag with release version (`-beta` suffix during development:
   `v3.2.0-beta.1`, `v3.2.0-beta.2`, …; drop `-beta` only when ready for
   production), create GitHub Release with changelog.
4. Never deploy to production until explicitly agreed.
5. SSH to server, pull new image, restart:
   ```bash
   # SSH credentials in Openclaw memory (topics/couchpotato.md)
   cd /var/lib/plexmediaserver/CouchPotato
   docker compose pull
   docker compose up -d
   docker logs couchpotato --tail=50
   ```
6. Scan the image before release:
   `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --scanners vuln <image>`.
   Target 0 CVEs. `.trivyignore` suppresses only the DS-0002 misconfig false
   positive (gosu/su-exec privilege-drop pattern).

## Test infrastructure

| Script | Purpose |
|---|---|
| `pytest tests/unit/ -q` | All unit tests (see PYTHONPATH note below) |
| `ruff check .` | Linting |
| `./scripts/test-local.sh` | Full Docker container test |

- Unit tests use `pytest` + the `tmp_path` fixture — no Docker needed locally.
- SQLiteAdapter tests instantiate against a temp path:
  `adapter.create(str(tmp_path / 'name'))`.
- `test_api_auth.py`, `test_fastapi_web.py`, `test_security.py` run locally too —
  `httpx` is installed in `.venv`, so run them via `.venv/bin/python -m pytest`.
- CI matrix: Python 3.10, 3.11, 3.12, 3.13.
- Note: a bare `pytest tests/unit/ -q` may hit import errors for tests touching
  vendored `libs/` — `make test-py` sets `PYTHONPATH=libs`. Prefer `make verify`
  / `make test-py`, or add the prefix if invoking pytest directly.

## QA process

- Test plan: `QA/QA_TEST_PLAN.md`
- Findings: `QA/QA_FINDINGS.md`
- Session logs: `QA/QA_SESSION_YYYY-MM-DD.md`

Run through core flows before any release: add movie, view detail,
filter/search wanted list, settings tabs, searcher/downloader connections,
suggestions.
