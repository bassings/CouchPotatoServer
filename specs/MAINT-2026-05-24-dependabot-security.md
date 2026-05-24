# MAINT-2026-05-24 - Dependabot Security and E2E Stabilisation

## Context

CouchPotatoServer is currently clean on `master` at `db8424df` and production is healthy on `v3.3.0`.

Open maintenance work:

- Dependabot security alert #80: `qs` vulnerable range `>= 6.11.1, <= 6.15.1`, fixed by `6.15.2`.
- Dependabot security alert #79: `uuid` vulnerable range `< 11.1.1`, fixed by `11.1.1`.
- Local `npm audit --audit-level=moderate` also reports `ws` moderate vulnerabilities.
- Dependabot PRs #91, #92, and #93 are blocked by `ui-e2e-tests`.
- Latest E2E failure from PR #93:
  - `tests/e2e/accessibility.a11y.spec.ts:67`
  - Test: `Accessibility › Suggestions page should be accessible`
  - First attempt timed out at `page.waitForLoadState('networkidle')`.
  - Retries found one serious `color-contrast` violation on Suggestions.

## Goal

Get the repository ready for Dependabot/security updates by fixing the blocking E2E accessibility issue and patching npm vulnerable transitive packages without using unsafe blind downgrades.

## Required Workflow

Use TDD:

1. Write or adjust a focused test first.
2. Run it and observe the expected failure.
3. Implement the smallest production/test change to make it pass.
4. Re-run the focused test.
5. Run the broader verification listed below.

If a test cannot be made to fail locally because the local environment differs from GitHub Actions, document that clearly in the final report and still validate with the closest local command.

## Scope

Allowed files:

- `tests/e2e/accessibility.a11y.spec.ts`
- `couchpotato/ui/templates/suggestions.html`
- `couchpotato/ui/templates/partials/suggestions.html`
- `couchpotato/ui/templates/base.html` only if the contrast issue is from shared theme tokens
- `package.json`
- `package-lock.json`
- Minimal docs/comments only if needed

Do not touch unrelated Python application code or production deployment files.

## Tasks

### 1. Stabilise Suggestions accessibility E2E

- Replace the brittle Suggestions test `waitForLoadState('networkidle')` with a readiness assertion tied to the rendered Suggestions page or its known partial container.
- Keep the assertion meaningful, not just a sleep.
- Identify the color-contrast violation on the Suggestions page and fix the actual UI contrast.
- Prefer theme-consistent colour classes over test exclusions.
- Do not suppress the color-contrast rule unless there is a clearly documented false positive. Expected path is a real contrast fix.

### 2. Patch npm vulnerable packages

- Update package metadata/lockfile so `npm audit --audit-level=moderate` no longer reports `qs`, `uuid`, or `ws`.
- Do not run `npm audit fix --force` if it downgrades `@lhci/cli` or other tooling.
- Prefer safe overrides where upstream packages have not yet updated their transitive dependency ranges, but verify that tests still pass.
- Current transitive sources observed:
  - `@lhci/cli@0.15.1 -> express/body-parser -> qs@6.14.2`
  - `@lhci/cli@0.15.1 -> lighthouse -> puppeteer-core -> ws@8.19.0`
  - `@lhci/cli@0.15.1 -> lighthouse -> ws@7.5.10`
  - `@lhci/cli@0.15.1 -> uuid@8.3.2`

### 3. Verification

Run and report exact results:

- `npm audit --audit-level=moderate`
- `npm run test:unit`
- Focused E2E accessibility command for Suggestions, if possible
- Full UI E2E if practical
- `python3 -m ruff check .`
- `pytest tests/unit -q` if local Python deps are available; otherwise report the environment blocker exactly

## Acceptance Criteria

- Suggestions accessibility E2E no longer uses `networkidle` as the primary readiness mechanism.
- Suggestions page has no serious/critical axe color-contrast violation.
- `npm audit --audit-level=moderate` exits cleanly, or any remaining advisory is explicitly justified with a package-manager limitation and proposed next step.
- UI unit tests pass.
- Python lint passes.
- No unrelated files changed.
- Final report includes:
  - TDD red/green evidence
  - Files changed
  - Verification commands and outcomes
  - Any blockers or residual risks
