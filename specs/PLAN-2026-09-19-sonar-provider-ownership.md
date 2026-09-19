# Sonar provider ownership findings

## Goal

Resolve the final two open Sonar `BUG` findings without changing provider
ownership behavior or the shared event interface.

## Acceptance criteria

- [x] AC-QA-1: Newznab and TorrentPotato retain the public
  `belongsTo(self, url, provider=None, host=None)` signature and rename only
  the loop-local configured-host binding.
- [x] AC-QA-2: Each override examines configured hosts in order, passes the
  exact configured hostname plus the unchanged URL and provider value to its
  parent matcher, and returns the first truthy result by identity.
- [x] AC-QA-3: A first-host match short-circuits; an all-miss result examines
  every configured host exactly once and returns `None`.
- [x] AC-QA-4: Ownership enumeration remains independent of enabled state so
  saved release URLs can still be associated after a provider is disabled.
- [x] AC-QA-5: Manual mutations that forward the incoming `host` argument,
  return after the first miss, continue after a match, or filter disabled
  hosts fail the focused tests; the restored implementation is green.
- [x] AC-QA-6: Focused provider tests, the repository fast gate, and two
  independent clean-agent reviews are clean.
- [ ] AC-REL-1: Exact-master Sonar closes issue
  `fd85abaa-2550-44f9-bd16-6755fee26c00` (`python:S1226`) as fixed.
- [ ] AC-REL-2: Exact-master Sonar closes issue
  `0078c882-2d6c-40b8-8c1e-da92bb3a4cb5` (`python:S1226`) as fixed.
- [ ] AC-REL-3: The exact-master Sonar bug inventory is empty after the scan.
- [x] AC-SEC-1: The incoming `host` argument is neither trusted nor used as a
  match authority; no logging, network I/O, credential handling, or error
  payload behavior changes.
- [x] AC-SEC-2: Tests use only reserved `.example` hosts and fake provider
  tokens; no private endpoints, credentials, media paths, or release data are
  introduced.
- [x] AC-SIMP-1: Production scope is exactly two local-variable renames, with
  no matching, normalization, event, or dependency changes.

## TDD note

Current runtime behavior is correct, so the two exact open Sonar findings are
the honest static red. Focused characterization tests pin the behavior before
the rename; deliberate mutations provide load-bearing red evidence rather
than inventing a runtime defect.
