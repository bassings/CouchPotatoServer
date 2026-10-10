# TMDB provider critical complexity, 2026-10-10

## Objective

Close the three critical `python:S3776` findings in the TMDB provider's
`search`, `getTrailer` and `parseMovie` methods while preserving metadata,
API request order, fallbacks and failure behaviour. This follows the
browser-test guard batch and must stay separate from any TMDB API behaviour
change.

## Acceptance criteria

1. Search preserves disabled behaviour, derived and explicit `search_type`,
   scanner name/year parsing, candidate order, result limit and parse errors.
2. Trailer lookup preserves IMDB-to-TMDB resolution, YouTube-only selection,
   Trailer before Teaser before other videos, return payload and empty cases.
3. Movie parsing preserves English/default/other-language request order,
   default fallback, image and cast handling, title order and de-duplication,
   missing-date sentinel handling and failure propagation.
4. Add focused tests for currently uncovered branches before changing code.
   Confirm they fail under deliberate mutations, pass after restoration and
   compare representative old/new method outputs and request traces.
5. Pass focused checks, full `make verify`, two independent local reviews,
   PR CI and cloud review; merge and analyse exact clean `master`. Confirm
   target closure, new findings and reporting gate. No production deployment.

## Tasks

- [x] T1 Characterise existing behaviour and add missing contracts
- [x] T2 Extract focused helpers with equivalent results and traces
- [x] T3 Complete full local gate and independent reviews
- [ ] T4 Deliver PR through CI, cloud review and merge
- [ ] T5 Confirm exact-master SonarQube result

## Conductor log

- 2026-10-10: Added six focused contracts for trailer resolution and
  selection, empty cases, search parse errors and the 1900 date/cast boundary.
  All six passed on the original code. Three deliberate mutations changed
  trailer priority, the 1900 sentinel and the search parse-error result in
  turn. Each mutation applied, made its targeted test fail, and passed after
  restoration. The first restoration exposed a same-size, same-second Python
  bytecode cache reuse in the test harness; clearing the provider's bytecode
  between variants produced reliable red/green proof.
- 2026-10-10: Extracted small helpers for search type, trailer lookup and
  selection, language requests, images, year, cast and alternate titles.
  Focused provider, scanner and date tests passed: 168 passed, one existing
  expected failure. Ruff passed. A separate old/new module comparison matched
  exact return values and API request traces on 180 varied search, trailer
  and movie-parse scenarios. TMDB is outside the configured mutmut source
  scope, so the three targeted mutation probes are the load-bearing proof.
- 2026-10-10: Full `make verify` passed: 4,911 Python unit tests, 42
  integration, 311 JavaScript unit, 227 desktop, two browser-isolation, 24
  phone and 126 accessibility tests, plus the repository's other checks.
  Post-refactor mutations to search-type selection, trailer priority and the
  1900 date sentinel each applied, failed the intended contract and passed
  after restoration. The original provider SHA-256 was restored. Two
  independent local reviews found no material issue; final review refresh
  remains before the first push.
