# Release-result filter complexity, 2026-10-10

## Finding and scope

The exact clean-master scan of `0a908e769` reports `python:S3776` on
`Release.tryDownloadResult` in `couchpotato/core/plugins/release/main.py`.
The method filters search candidates before it dispatches a download. Extract
the acceptance check so the filtering decisions remain in one place and the
method falls below SonarQube's complexity threshold.

This slice does not change downloader failure fallback, database writes,
scheduled cleanup or candidate order.

## Acceptance criteria

1. Status, score, size and seeder rejection produce the same log messages and
   skip the same candidates. Accepted input dictionaries retain their identity
   and receive the same `wait_for` mutation.
2. Waiting logic, `release.download` call order, `True` and `try_next` results,
   and return values match the pre-change method, including all-filtered and
   all-waiting lists.
3. Focused tests and a differential run cover these cases, plus a deliberate
   mutation of a filter threshold. Ruff, the full local gate and two
   independent reviews pass before push.
4. PR CI and cloud review pass, then an exact clean-master scan confirms the
   issue's disposition, new issues and reporting gate. No production action.

## Tasks

- [x] F1 Characterise filter and dispatch behaviour
- [x] F2 Extract acceptance check and verify
- [ ] F3 Review, PR, merge and scan; state: building

## Conductor log

- 2026-10-10: Four contract tests passed on original code. Raising the size
  rejection threshold from 50 to 51 made three fail, and restoration passed
  after refreshing the source timestamp so Python would not reuse a stale
  bytecode cache. The extraction passed 75 focused tests and Ruff. A
  deterministic comparison of 3,000 generated batches found identical return
  values, dispatch order and input mutations in old and new implementations.
