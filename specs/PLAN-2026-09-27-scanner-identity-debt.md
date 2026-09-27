# Scanner identity complexity paydown

## Goal

Reduce the cognitive complexity of `FolderScannerMixin.determineMedia` while preserving its ordered identity evidence and failure containment. This is the first bounded PR in the maintainability wave. The existing spec `specs/PLAN-2026-09-19-sonar-provider-ownership.md` is the format exemplar.

## Acceptance criteria

- [x] AC-DATA-1: Identity sources retain this precedence: download ID, CP tag, NFO, filename IMDb ID, then searched title and year. The first valid source wins, and `identity_source` names it.
- [x] AC-DATA-2: A filename IMDb ID cannot be overwritten by later files or file types. A fuzzy search remains marked `search`, never an asserted identity for destructive replacement.
- [x] AC-QA-1: A malformed NFO, filename or search provider response cannot abort identification of later candidates or leave a partial library scan that enables cleanup.
- [x] AC-QA-2: The first movie filename, DVD suppression, primary/alternate query order, search limit/type, and first in-tolerance year choice remain unchanged.
- [x] AC-QA-3: New or existing focused tests cover source precedence, failure fallthrough and the search boundary; deliberate mutations demonstrate new tests are load-bearing.
- [x] AC-QA-4: Scanner diagnostic logging failures cannot truncate an otherwise continuing multi-movie scan or discard an identified fallback. Real two-movie, symlink-gather, search-warning and parser-error tests must fail when their guards are removed.
- [x] AC-QA-5: A static scanner guard rejects any new direct logger call that bypasses the non-fatal diagnostic helper.
- [x] AC-SIMP-1: Helpers stay private, small and purpose-specific. No public scanner signature, event contract, dependency, or database schema changes.
- [ ] AC-REL-1: The original `python:S3776` finding on `determineMedia` closes on a fresh-clone exact-master Sonar scan without creating a replacement S3776 finding in an extracted helper.
- [ ] AC-REL-2: The full local gate, two independent clean-agent reviews and hosted checks pass before merge.

## TDD note

The current fallback behaviour is intentional, so the measured Sonar complexity finding is the honest static red. Characterisation tests must pass before refactoring; deliberate mutations, not a fabricated runtime defect, provide red evidence for their behavioural protection.
