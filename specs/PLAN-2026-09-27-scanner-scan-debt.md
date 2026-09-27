# Scanner pipeline complexity paydown

## Goal

Reduce the cognitive complexity of `FolderScannerMixin.scan` without changing its grouping, callback, or completeness decisions. The exact-master Sonar analysis at `ea92794b` reports `python:S3776` on `scan` with cognitive complexity 154 against the allowed 15. This function sits upstream of library cleanup, so a refactor must preserve absence-evidence safety. `specs/PLAN-2026-09-27-scanner-identity-debt.md` is the format exemplar.

## Acceptance criteria

- [ ] AC-DATA-1: A complete library scan still reports identified groups and permits cleanup only under the existing `Manage.updateLibrary` policy. An unresolved group, failed walk, vanished movie, or failed movie-size check still withholds a complete result and cannot authorise deletion.
- [ ] AC-QA-1: Ordinary scanner callers retain best-effort scanning: an unreadable subtree does not hide accessible later siblings; explicit `files` input and an empty `files` value retain their current semantics.
- [ ] AC-QA-2: Movie, DVD, sample, sidecar, ignored-extension and leftover grouping retain their existing buckets and duplicate handling. Group and callback order, callback counts, and the processed result shape remain unchanged.
- [ ] AC-QA-3: File-date and `newer_than` filters, shutdown checks, release-download ID handling, and thread-throttle behaviour remain unchanged.
- [ ] AC-QA-4: New characterisation tests cover callback order, sidecar/leftover association, partial-completeness signals, and the filter boundary. Deliberate mutations prove the new assertions fail on a meaningful change.
- [ ] AC-SEC-1: Error logging stays best effort and does not newly expose private file paths or credentials.
- [ ] AC-SIMP-1: Extraction uses private, purpose-specific helpers; the public `scan` signature, event contract, dependencies and database schema are unchanged.
- [ ] AC-REL-1: The `python:S3776` finding on `scan` closes on a fresh-clone exact-master Sonar scan, with no new S3776 finding in an extracted helper.
- [ ] AC-REL-2: Focused tests, the full local gate, two fresh independent clean reviews, hosted checks and post-merge exact-master Sonar verification pass.

## TDD note

The existing scan behaviour is the contract, so the Sonar complexity finding is the structural red. Characterisation tests should pass before refactoring; deliberate mutations, not an invented runtime defect, provide red evidence that they protect behaviour.
