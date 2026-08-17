# AGENTS.md

## Project Context

CouchPotatoServer is a media-management web application with a Python backend, a browser-based UI, SQLite-backed state, Docker deployment, and GitHub Actions release automation.

Treat this as a home-server application that may run on private networks and manage personal media libraries, automation credentials, user settings, and downloaded metadata. Changes should preserve reliability, privacy, and production deployability.

## Review Guidelines

When reviewing pull requests, prioritise issues that can cause real defects, security exposure, accessibility regressions, privacy leaks, data loss, broken mobile workflows, or operational failures. Keep minor style preferences out of review comments unless they contribute to one of those risks.

Review at minimum for:

- Code quality: correctness, maintainability, clear boundaries, unnecessary complexity, brittle assumptions, legacy compatibility hazards, and behaviour that is hard to test.
- Security: authentication and authorisation flaws, CSRF exposure, injection risks, unsafe redirects, path traversal, secret exposure, dependency risk, unsafe file handling, overly permissive server behaviour, and private-network attack surface.
- Accessibility: semantic structure, keyboard access, visible focus states, useful labels, screen-reader clarity, colour contrast, reduced-motion handling, and avoiding ARIA misuse.
- Mobile and responsive UX: small-screen layout, tap targets, text overflow, viewport issues, form ergonomics, and regressions that make core library or wanted-list flows difficult on phones.
- Privacy and PII: accidental logging or exposure of media library paths, API keys, automation credentials, user settings, watch history, request metadata, or environment secrets.
- Reliability: database write safety, migrations, error handling, idempotency, startup and shutdown behaviour, backup-friendly state handling, and failure states that could lose or corrupt configuration or media metadata.
- Test coverage: focused unit, integration, or e2e coverage for changed behaviour, especially auth, settings, database writes, migration logic, API routes, UI workflows, Docker startup, and release automation.
- Performance: avoid unnecessary client JavaScript, slow or unbounded queries, blocking startup work, excessive polling, expensive rendering, and changes that make the UI feel heavy on lower-powered home servers.
- Deployment and operations: Docker, compose files, environment variables, health checks, persistent volumes, restart behaviour, release workflows, dependency submission, and production build compatibility.

Treat these as high-priority review findings:

- Any privacy leak, secret leak, or exposure of personal media paths, credentials, API keys, or local-network details.
- Any unauthorised access path to settings, automation endpoints, credentials, library data, or administrative actions.
- Any accessibility regression that blocks keyboard users, screen-reader users, or basic form completion.
- Any mobile layout regression that blocks searching, adding, editing, wanted-list management, settings, or library workflows.
- Any data-loss, data-corruption, migration, or backup-hostile change.
- Any production deployment breakage in Docker, compose, health checks, release workflows, or application startup.

## Development Expectations

- Preserve existing app patterns unless there is a clear reason to change them.
- Prefer simple, typed validation and explicit parsing for untrusted input.
- Keep sensitive operations server-side and avoid logging secrets or private paths.
- Keep database and migration changes conservative and recoverable.
- Do not add broad new dependencies without a clear benefit.
- Add or update tests when changing user-facing flows, access control, persistence, migrations, deployment, or release automation.
- Do not weaken linting, type checking, tests, security checks, dependency checks, or accessibility checks to make a change pass.

## Local Verification

Before considering a change complete, run the narrowest relevant checks for the touched area. For broad changes, prefer:

```sh
ruff check .
python -m pytest
npm run test:unit
npx playwright test --project=chromium
npx playwright test --project=accessibility
docker build -t couchpotato:test .
```

### Running the tests from inside a git worktree

Agents in this repo usually work in a linked worktree, and **a worktree has no
`.venv` of its own**. Resolve the main checkout first and use its interpreter:

```sh
MAIN_REPO="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
PYTHONPATH=.:libs "$MAIN_REPO/.venv/bin/python" -m pytest ...   # run from THIS worktree's root
```

`--git-common-dir` resolves the main checkout even from a linked worktree;
`--show-toplevel` would return the worktree, where there is no interpreter.
Never modify anything under `$MAIN_REPO` or its `.venv`: it is the shared
checkout and other work is usually live in it.

For release or dependency changes, also run the repository's release-quality checks and audit commands where available. For browser-facing workflow changes, add or update Playwright coverage where practical and verify the affected flow on a mobile-sized viewport.

## Local Review Gate (before pushing)

Passing the checks above is necessary but **not sufficient**. A change is not pushed until a **clean-agent local review is clean**: spawn ≥2 independent `code-reviewer` agents (defined in `.claude/agents/`, which apply the Review Guidelines below) against the branch diff (vs `master`), and **iterate locally — fix every real finding, re-verify, re-review — until the review comes back clean. Only then push.** Running the review agents *is* the gate; self-verifying the diff yourself is not a substitute. This holds for every push: the initial PR, **each fix commit** made in response to a cloud `claude-review` finding (fix → local review again until clean → push), and policy-doc (`CLAUDE.md`/`AGENTS.md`) or `specs/**` changes. See `docs/development-process.md` → *Path to Production (full flow)* for the full flow and rationale (the cloud reviewer is stateless per push, so pushing before the local review is clean just dribbles the findings out one round at a time).

## Multi-lens harness: path triggers and precedence (this repo)

The lens roster, output contract and evidence discipline are global:
`~/.claude/AGENT-HARNESS.md` (summarised in `~/.claude/CLAUDE.md` §13). This
section supplies only what is repo-specific.

**Always on:** `lens-security`, `lens-qa` (both cycles); `lens-simplicity`
(**planning only**: its `AC-SIMP-<n>` constraints are verified at review by the
orchestrator reading the diff, not by an agent).

**Triggered by changed paths:**

| Lens | Trigger |
|---|---|
| `lens-design` + `lens-accessibility` | `couchpotato/ui/**`, `couchpotato/templates/**`, `**/*.html`, `couchpotato/static/**`, `tests/e2e/**`, `.github/workflows/ci.yml` |
| `lens-data` | `couchpotato/core/db/**`, `couchpotato/core/database.py`, `**/schema.sql`, `couchpotato/core/plugins/renamer/**`, `couchpotato/core/plugins/scanner/**`, `couchpotato/core/plugins/release/**`, `couchpotato/core/migration/**` |
| `lens-architecture` | `couchpotato/core/event.py`, `couchpotato/core/loader.py`, `couchpotato/api.py`, `couchpotato/__init__.py` |
| `lens-operability` | `Dockerfile`, `docker-*.yml`, `.github/workflows/**`, `couchpotato/core/logger.py`, `scripts/**`, `couchpotato/core/_base/scheduler.py`, `couchpotato/core/plugins/manage.py`, `couchpotato/core/plugins/renamer/main.py`, `couchpotato/core/plugins/automation.py`, `couchpotato/core/plugins/file.py`, `couchpotato/core/_base/updater/main.py`, `couchpotato/core/notifications/core/main.py` |
| `lens-product` | a `specs/**` file exists for the change, or the change is user-facing |

`lens-architecture` also triggers, independent of the path globs above, when
the diff adds a new module or package, or a new entry to a dependency
manifest (`requirements*.txt`, `pyproject.toml`). That is handled by a
separate boolean in the workflow's scope step, not by a path glob, so it does
not appear in the table or in `harness-triggers.json`.

Those globs are configuration, not prose: they live in
`.claude/harness-triggers.json`, which the installed harness workflow reads.
Change them there and this table together — a unit test
(`tests/unit/test_no_forked_workflow_copies.py`) asserts the two stay in sync.

`couchpotato/core/migration/**` is a deliberate addition to `lens-data`, not
part of the CodernityDB-to-SQLite migration this PR ports. It was missing
from the forked workflow this PR replaces too, so it is a pre-existing gap,
not a regression introduced here. `clean_orphans.py`
(`couchpotato/core/migration/clean_orphans.py`) deletes movie and child
records from the database, invoked unconditionally on every server start by
`couchpotato/runner.py` (around line 477); a change there is exactly the
irrecoverable-data-loss surface `lens-data` exists to catch, so it is added
now rather than left open.

Two rows exist in the shape they do because a cycle got them wrong once, and
the reasons are cheaper to keep than to rediscover:

- **`couchpotato/api.py`, not `couchpotato/core/api.py`.** The latter does not
  exist, so while the glob named it, the API boundary never triggered
  `lens-architecture` at all.
- **Scheduled behaviour is an operability concern wherever it lives.** Path
  globs alone missed it: a change to the scheduled full-library cleanup in
  `couchpotato/core/plugins/manage.py` matched no operability glob, so the
  cycle skipped `lens-operability` for its own diff. The scheduler module and
  the plugins that register interval jobs are now listed explicitly.

**Do not fork the workflow to tune it.** Until 2026-08-17 this repo carried
copies of `plan-cycle.js` and `review-cycle.js` under `.claude/workflows/`.
Repo-local copies win over the installed ones, so those forks silently
shadowed every later harness update: both were pinned at 2026-08-07/08,
predated the run ledger entirely, and contained no ledger write at all. The
measurable consequence was that no cycle run in this repo ever produced
telemetry, and nothing warned. Tune through `harness-triggers.json`.

**The accepted cost of not forking.** `harness-triggers.json` is read by an
LLM scope step, not by deterministic code, and `custom_rules` is optional in
that step's schema: if the model omits it or the read fails, the run falls
back silently to the installed workflow's defaults, which know nothing about
`couchpotato/` paths. Measured blast radius, re-derived 2026-08-18 against the
final `harness-triggers.json`: **25** of this repo's `lens-data` paths and
**7** of its `lens-operability` paths stop triggering, including
`couchpotato/core/plugins/renamer/mover.py`, this repo's highest-risk file —
and the run prints a normal-looking lens roster with nothing indicating the
override was dropped. Those counts are re-derivable, and should be re-derived after any glob change
rather than trusted: for each git-tracked path, a path "stops triggering" lens
X on fallback if it matches this repo's X globs but NOT the installed harness
`DEFAULT_RULES` X globs in `~/.claude/workflows/review-cycle.js`. Over 731
tracked paths that gives ui 1, data 25, architecture 4, operability 7.

These numbers have already drifted once, which is why the method is written
down: an earlier commit on this branch said "21 data paths", correct before
`couchpotato/core/migration/**` was added, and "4 operability paths", correct
before the three scheduled-job registrants were added. A count with no stated
derivation is a claim nobody can check, which is the failure this file's own
fork-removal rationale exists to argue against.

This is not free, and it is not fixed here: the real
fix is upstream in `claude-ai-harness`, making `custom_rules` load
deterministically rather than through a model step. Until then, a reviewer
running `/review-cycle` on a diff touching `renamer/`, `database.py`,
`release/`, `scanner/`, or `migration/` must confirm `lens-data` is actually
in the triggered roster printed at the start of the run — its absence on one
of those paths means the override did not load, not that the change is safe.

`.github/workflows/ci.yml` appears in BOTH the UI row and the operability row,
deliberately. It is where the accessibility gate itself is configured, and
`specs/CI-003-fast-gate.md:462-466` records the cycle already missing this
once: "no `lens-accessibility` ran on a change that edits the accessibility
gate", so no AC-A11Y criterion had a verdict from anyone. A change that can
weaken the gate needs the lens the gate exists to serve, not just the lens
that owns CI.

The operability list enumerates scheduled-job registrants because a path glob
cannot express "registers a scheduled job". That list was derived by searching
for `fireEvent('schedule.interval'` and is therefore a snapshot: re-derive it
when adding a plugin that registers interval work, or the next one will be
missed the way `plugins/manage.py` already was.

**Precedence for conflicts on this repo** (the global order, made concrete):

1. **Irrecoverable data loss**: the user's media files, settings, the SQLite
   database. Ranked per CLAUDE.md: irreplaceable → expensive (a completed
   download, watch history) → cheap (caches, the container). A change that moves
   a possible loss *up* that list loses to one that does not, however correct it
   looks
2. **Security**: this ships to self-hosted installs that are sometimes
   port-forwarded; assume the operator will not read a release note
3. **Accessibility floor**: WCAG 2.2 AA, in **both** themes and at phone width
4. **Operability**: a self-hosted user has no dashboards; if it fails silently
   nobody finds out
5. Product and design intent
6. Performance

**Repo-specific notes for lenses:**

- `lens-data` owns the highest-risk surface here. `moveFile`
  (`core/plugins/renamer/mover.py`) and the `_query_index` branches
  (`core/db/sqlite_adapter.py`) have both produced live defects; treat changes
  near them as new work, not corrections
- `lens-qa` must check `tests/e2e/` for conditional test bodies
  (`if (await x.isVisible()) { ... }`), which pass while asserting nothing. 
  the pattern was removed once in `movie-detail.spec.ts` and still exists
  elsewhere
- `lens-operability` should assume the reader is the operator at 3am with only
  `docker logs`. There are no metrics
- `lens-simplicity` should know that shipped public app keys, the vendored
  `libs/CodernityDB/`, and the accepted E2E coverage gap are **deliberate** and
  documented in `docs/technical-debt.md`: do not propose removing them
- `lens-security` owns **privacy** here as well as security. The personal data
  on this project is not a user table: it is the **library itself**: film
  titles and watch history are a detailed personal profile, and filesystem paths
  disclose the user's real name and directory layout. Honour `PrivacyFilter`
  (`couchpotato/core/logger.py`), and treat a private path in a log, an error
  payload or a third-party request as a privacy finding, not a cosmetic one.
  There is no user-facing deletion or export flow today; if a change adds one,
  `lens-data` verifies the mechanism reaches the poster cache and the
  `media_identifiers` table, not just the `media` row

The `code-reviewer` agent in `.claude/agents/` remains valid for small changes
that do not justify the full set: it is the degenerate case of the harness,
not a competing process.
