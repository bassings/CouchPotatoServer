# SonarQube priority fixes, 2026-10-07

The analysis of released commit `2b7ed668` reports no bugs, vulnerabilities or
security hotspots. Its critical findings are code smells. Earlier Sonar plans
already assessed the broad naming and complexity groups; this slice addresses
one critical finding with a concrete failure mode and groups test isolation
findings that can cause order-dependent results.

## Acceptance criteria

- The updater's scheduled-job removal and registration use one identifier, so
  they cannot target different jobs during the same rescheduling call.
- Tests that temporarily change process globals restore them through pytest's
  `monkeypatch` fixture, including when an assertion or request fails.
- Trivial constant-return method stubs use the mock library's `return_value`
  so their intent is visible and the mocks can be inspected by tests.
- The focused tests and repository lint pass. Existing shared-checkout changes
  remain untouched.

Delivery continues through a reviewed pull request, CI, merge and a
post-merge SonarQube analysis. A stable release needs Scott's approval.
