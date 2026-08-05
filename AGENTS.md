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
npm run test:e2e -- --project=chromium
npm run test:a11y
docker build -t couchpotato:test .
```

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
| `lens-design` + `lens-accessibility` | `couchpotato/ui/**`, `couchpotato/templates/**`, `**/*.html`, `couchpotato/static/**`, `tests/e2e/**` |
| `lens-data` | `couchpotato/core/db/**`, `couchpotato/core/database.py`, `**/schema.sql`, `couchpotato/core/plugins/renamer/**`, `couchpotato/core/plugins/scanner/**`, `couchpotato/core/plugins/release/**` |
| `lens-architecture` | a new module or package, a new entry in `requirements*.txt`, or any change to `couchpotato/core/event.py`, `loader.py`, `api.py`, `couchpotato/__init__.py` |
| `lens-operability` | `Dockerfile`, `docker-*.yml`, `.github/workflows/**`, `couchpotato/core/logger.py`, `scripts/**`, or any change to scheduled/cron behaviour |
| `lens-product` | a `specs/**` file exists for the change, or the change is user-facing |

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
  (`if (await x.isVisible()) { ... }`), which pass while asserting nothing , 
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
