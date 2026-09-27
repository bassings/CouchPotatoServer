# Fail-closed library cleanup after incomplete scans

## Goal

An unattended full-library scan must not treat a partially scanned or unidentified movie as proof that the movie was deleted. The current `Manage.updateLibrary` cleanup can delete a `done` media record when one movie is identified and another group in the same directory is not. The scanner can also return a partial file list after a walk error. Preserve normal add/update work, but withhold destructive cleanup whenever the scan's absence evidence is incomplete. The scanner identity spec `specs/PLAN-2026-09-27-scanner-identity-debt.md` is the format exemplar.

## Acceptance criteria

- [ ] AC-DATA-1: If a full scan finds one valid movie and one unresolved movie group in the same directory, neither the unresolved movie's media record nor its history is deleted. Successfully identified groups may still be added or updated.
- [ ] AC-DATA-2: If file gathering or a movie file-size check fails after yielding at least one movie, cleanup is skipped even though the partial scan is non-empty. An empty-but-successful directory remains covered by the existing per-directory empty guard.
- [ ] AC-DATA-3: A scanner handler error or missing scan result cannot be accepted as a complete scan, even if `on_found` fired earlier. The real event dispatcher's failure return shape is reflected by test doubles.
- [ ] AC-DATA-4: A complete scan still removes a genuinely missing, terminal movie under the existing cleanup policy. Active and review-stage movies remain exempt.
- [ ] AC-OPS-1: Skipped cleanup emits an actionable warning at the production log level without adding private filesystem paths or credentials to the message.
- [ ] AC-OPS-2: An incomplete full or incremental scan cannot leave the progress wait stuck above zero or advance the last-successful-scan timestamp, including when a directory vanishes between the manager and scanner checks; a later scan must be able to retry.
- [ ] AC-QA-1: Cross-boundary tests exercise `scanner.scan` through the `Manage.updateLibrary` cleanup decision, with red/green proof of the dangerous partial-success case and focused failure cases for unresolved groups and file-walk errors.
- [ ] AC-SIMP-1: The completeness signal uses one optional scanner flag and one private file-gather status; ordinary scanner callers keep their previous return and best-effort behaviour. No database schema or dependency changes.
- [ ] AC-REL-1: Focused checks, deliberate mutation proof, the full local gate, two fresh independent clean reviews, and hosted checks pass before merge. A fresh-clone exact-master Sonar scan completes after merge.

## Implementation sequence

1. Characterise the real `scanner.scan` result and event-dispatch failure shape in focused tests.
2. Add a failing two-movie cleanup test and failing partial-gather/failed-dispatch tests.
3. Make `Manage` require a complete scan result before cleanup, and let library scans request fail-closed file gathering while preserving other scanner callers' best-effort behaviour.
4. Run focused and full gates, independent review, PR checks, merge and the required exact-master Sonar scan.
