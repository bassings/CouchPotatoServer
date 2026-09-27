# Fail closed after an uncertain default move

The default renamer move currently treats a raised `shutil.move` as success if
the source and destination compare equal, then unlinks the source. A pathname
can be replaced after that comparison, so the unlink can delete an unrelated
file. This task does not solve the documented composite-call retry gap in
`docs/technical-debt.md`; it removes the unsafe success claim while a more
complete, provenance-aware retry design is investigated.

## Acceptance criteria

- When `shutil.move` raises after writing a complete destination, `moveFile`
  propagates failure, keeps both paths and never removes the source, even if
  its pathname changes after comparison.
- The real caller suppresses source-folder cleanup on that failure.
- The extractor's leftover-file caller also retains the source, omits a
  failed destination from its extracted-file result, and does not run
  empty-folder cleanup after the same failure.
- A shorter failed destination is still quarantined where safe; existing
  collision and successful-move behaviour remains unchanged.
- Newly reached error logs do not disclose full source or destination paths,
  movie names, or exception messages containing those values.
- An opaque `.cps-partial-*` identifier remains visible at ERROR level when
  its recovery copy blocks a retry, so an operator can find the artefact.
- Earlier acceptance criteria that permitted source deletion after a failed
  complete copy explicitly defer to this fail-closed contract, with a test
  preventing the unsafe wording from silently returning.
- A regression test first fails against the pre-fix behaviour, then passes;
  a deliberate production-code mutation proves the guard remains load-bearing.
