# T17: keep the settings save transaction auditable

`Settings._saveView` now holds authentication, credential and on-disk outcome
handling in one high-complexity method. SonarQube reports S3776 cognitive
complexity 54 on exact master `7114bd7d`. This follows the new password
revocation-intent protection in
`specs/PLAN-2026-09-28-session-rotation-intent.md`; the protection takes
priority over a lower smell count.

Acceptance criteria:

- A password value-hook failure leaves the in-memory auth gate and pending
  revocation marker as they were before the attempt. A later unrelated save
  cannot persist a half-prepared password change. Test with real `Settings`,
  config file and SQLite state, and deliberately demonstrate the pre-fix
  failure.
- Extract the password/auth transaction preparation and failed-save
  reconciliation into cohesive helpers. The exact-master Sonar scan after
  merge closes S3776 on `_saveView` without creating another S3776 finding
  in those helpers.
- Existing success, refusal, uncertain-commit, secret-rotation, cookie and
  settings-save tests remain green. The focused tests and full repository gate
  pass; a load-bearing mutation fails and is restored. Two independent local
  reviews are clean before any push.
- Do not change schema, credentials, auth defaults, emitted secrets, or the
  operator's recovery path. No new dependency.
