# Scanner release-name/year complexity paydown

## Goal

Close the remaining open `python:S3776` finding in `folder_scanner.py`: `getReleaseNameYear` has cognitive complexity 24 against the configured limit of 15 on exact `master` `39f2be60`. Keep the movie-identification result and fallback order unchanged. `specs/PLAN-2026-09-27-scanner-scan-debt.md` is the format exemplar.

## Acceptance criteria

- [ ] AC-DATA-1: A usable filename `guessit` title and year remain an alternate candidate; the existing cleaner parse wins only when years match and its name is longer. Preserve each candidate's nested `other` result.
- [ ] AC-DATA-2: Year lookup still prefers the filename, then release basename, then cleaned release name. Malformed guessit input must not abort the existing fallback.
- [ ] AC-QA-1: Characterisation tests cover the precedence, no-year and failure paths, and deliberate mutations prove the new assertions reject a wrong result.
- [ ] AC-SEC-1: No new private filename, path, credential or metadata exposure in diagnostics.
- [ ] AC-SIMP-1: Keep the public method and call sites stable; use a small purpose-specific extraction rather than broad scanner restructuring or new dependencies.
- [ ] AC-REL-1: Focused scanner/caller tests, the full local gate, two independent clean reviews and hosted checks pass. A fresh-clone exact-master Sonar scan closes this S3776 finding without a new S3776 in extracted helpers.
