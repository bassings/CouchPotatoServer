# Restore test environment state after each fixture

The 2026-10-08 SonarQube scan of `26eb0b5` reports three major
`python:S9100` findings in autouse fixtures that call `Env.set(...)` and
then yield without restoring the values. `Env.set` writes class attributes,
so later tests can inherit web, API, development-mode or application-name
settings from an unrelated module.

## Acceptance criteria

- The autouse fixtures in `test_releases_partial_route.py`,
  `test_review_actions_ui_template.py` and `test_notifications.py` restore
  every `Env` attribute they set after each test, including attributes that
  were absent before setup.
- A failing test body still triggers restoration through pytest teardown.
- A regression test drives each fixture through a real pytest test lifecycle
  and fails when its former process-global leak is restored deliberately.
- Focused tests, lint and the repository gate pass. A clean-master scan
  confirms the three issue records close without new high-impact findings.

Delivery follows the repository's local review, PR, CI and merge gates.
