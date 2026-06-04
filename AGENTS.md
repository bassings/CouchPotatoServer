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
