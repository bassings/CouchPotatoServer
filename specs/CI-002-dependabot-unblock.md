# CI-002 — Unblock Dependabot PRs on claude-review + fix js-yaml alert

## Problem A — claude-review fails on every Dependabot PR

All five open Dependabot PRs (#142–#146) pass 16/17 checks; the required
`claude-review` check fails with:

> Action failed with error: Workflow initiated by non-human actor: dependabot
> (type: Bot). Add bot to allowed_bots list or use '*' to allow all bots.

(`anthropics/claude-code-action@v1` rejects bot actors by default. Letting the
review actually *run* for Dependabot would also require registering
`CLAUDE_CODE_OAUTH_TOKEN` as a separate Dependabot secret — not wanted.)

### Fix A

In `.github/workflows/claude-review.yml`, skip the job for Dependabot at the
job level, e.g. extend the existing job `if:`:

```yaml
if: ${{ github.event.pull_request.head.repo.full_name == github.repository && github.actor != 'dependabot[bot]' }}
```

A job skipped via `if:` reports conclusion `skipped`, which **satisfies** the
required-status-check branch protection (unlike a workflow that never runs).
Add a brief comment in the YAML explaining why (bot actor rejected by the
action; skipped == satisfied for branch protection).

## Problem B — open Dependabot alert #90: js-yaml < 3.15.0 (medium, dev-only)

Quadratic-complexity DoS in merge-key handling. Chain:
`@lhci/cli@0.15.1 → @lhci/utils@0.15.1 → js-yaml@3.14.2` (package-lock.json,
development scope).

### Fix B

Add an npm override in `package.json` (there is precedent — the `tmp` override):

```json
"overrides": { "js-yaml": "^3.15.0" }
```

Stay on the 3.x line (3.15.0 is the first patched version) so `@lhci/utils`'s
js-yaml 3.x API usage keeps working. If an `overrides` block already exists,
extend it. Then `npm install` to refresh `package-lock.json`, and verify
`npm ls js-yaml` shows ≥ 3.15.0 everywhere.

## Acceptance criteria

- `.github/workflows/claude-review.yml` parses as valid YAML
  (`.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/claude-review.yml'))"`).
- `npm ls js-yaml` → 3.15.x (no `< 3.15.0` anywhere in the tree).
- UI unit tests still pass: `npm run test:unit` (and `npx lhci --help` exits 0
  as a smoke test that the override didn't break @lhci/cli).
- `ruff check .` clean (should be untouched).
- Conventional commit locally. **STOP after committing — do NOT push.**

## Notes

- CLAUDE.md: GitHub only honours edits to `claude-review.yml` once the workflow
  exists on `master`; the PR editing it is a no-op for its own run — expected.
- After this lands on master, the five Dependabot PRs need `@dependabot rebase`
  (or close/reopen) so their merge commits pick up the new workflow.

## Files

- `.github/workflows/claude-review.yml`
- `package.json`, `package-lock.json`
