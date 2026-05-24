# MAINT-2026-05-24: UI Tooling Dependabot Maintenance

## Context

Dependabot has two open UI tooling PRs:

- #91 `@playwright/test` from `1.59.1` to `1.60.0`
- #92 `vitest` from `4.1.5` to `4.1.6`

Their earlier CI failures were in `ui-e2e-tests` before the Suggestions accessibility/wait fix merged to `master`. Re-validate these upgrades against current `master`.

## Scope

Update only Node dependency files unless a test proves code changes are required:

- `package.json`
- `package-lock.json`

Do not alter application UI or test semantics unless required for compatibility with the new tooling versions.

## TDD / Validation Expectations

For tooling-only maintenance, the red/green loop is runner compatibility verification.

1. Apply both dependency updates.
2. Run:
   - `npm install`
   - `npm run test:unit`
   - `npm audit --audit-level=moderate`
   - focused Playwright/a11y checks if practical
3. If a compatibility failure appears, add or adjust the smallest focused test first, then fix the affected config/test code.

## Acceptance Criteria

- `@playwright/test` resolves to `1.60.0`.
- `vitest` resolves to `4.1.6`.
- Existing npm overrides for `qs`, `uuid`, and `ws` remain intact.
- UI unit tests and npm audit pass locally.
- The branch is committed with a conventional commit message.
