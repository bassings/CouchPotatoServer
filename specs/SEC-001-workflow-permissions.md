# SEC-001: GitHub Workflow Permissions Hardening

## Problem
CodeQL alerts #47, #49, #51, #52, #53 — multiple GitHub Actions workflow jobs
are missing explicit `permissions` declarations, violating least-privilege principle.
Jobs run with default (overly broad) token permissions.

## Files to Change
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `.github/workflows/docker.yml`

## Fix

Add explicit `permissions` blocks to each job that doesn't already have one.
Use minimum required permissions:

| Job type | Permissions needed |
|----------|-------------------|
| lint/test (read-only) | `contents: read` |
| docker build/push | `contents: read`, `packages: write` |
| release (create release) | `contents: write`, `packages: write` |
| CodeQL analysis | `security-events: write`, `contents: read` |

Review each workflow file and add the appropriate `permissions` to any job lacking it.
Do NOT add permissions broader than what the job actually uses.

## Acceptance Criteria
- [ ] Every job in all 3 workflow files has an explicit `permissions` block
- [ ] No job has broader permissions than required for its tasks
- [ ] Workflow YAML is valid (check with `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`)
- [ ] Run `ruff check .` to confirm no Python was accidentally changed
- [ ] Commit message: `fix: add explicit permissions to GitHub Actions workflows (SEC-001)`

## Notes
- YAML only — no Python code changes
- No unit tests needed for this task
- Check each job's `steps` to determine what permissions it actually needs
