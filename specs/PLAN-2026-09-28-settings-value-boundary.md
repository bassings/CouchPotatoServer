# T18: make settings value disclosure decisions auditable

Exact-master SonarQube at `e34179bf` reports S3776 cognitive complexity 36
in `Settings.getValues`. The method decides whether config values may reach
the settings UI. Refactor it without changing what the operator sees or
letting orphaned credentials pass through a stale shared type registry.

Acceptance criteria:

- Orphaned options are masked from their raw config value before any typed
  conversion, including when another `Settings` instance registered the same
  name as a directory. A deliberate reordering mutation makes this test fail.
- Registered password, plain string, directory and directories options
  retain their existing masking and soft-chroot behaviour, including
  conversion failures. The existing credential and orphan suites stay green.
- `getValues` becomes a small coordinator with separate orphan and registered
  value handling. The post-merge exact-master Sonar scan closes its S3776
  finding without creating one in a new helper.
- Ruff, focused tests, the full repository gate and two independent clean
  local reviews pass before push. No new dependency or settings schema change.
