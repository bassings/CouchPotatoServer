# QUAL-001 — widen Python mutation testing scope

## Problem
The Python suite has **662 unit tests across 42 files**, but `mutmut` is scoped
to a **single module** (`couchpotato/core/db/sqlite_adapter.py`). So the mutation
signal — which catches assertion-free / coverage-only tests — covers ~1 module
while the other 661-tests'-worth of surface is mutation-blind. High test *count*,
narrow test *strength* verification.

## Fix
Widen `[tool.mutmut] paths_to_mutate` in `pyproject.toml` incrementally, in
test-density order, keeping each run fast by pointing the runner at the tests
that actually cover the mutated paths. Add modules one PR (or one batch) at a
time so a flood of survivors is triaged, not ignored:

| Order | Module | Unit-test files referencing it | Rationale |
|---|---|---|---|
| (done) | `core/db/sqlite_adapter.py` | 15 | post-migration `_query_index` bugs |
| 1 | `core/media/quality` logic | 28 | well-tested; backs the profiles UI |
| 2 | `core/media/profile` logic | 22 | backs the profiles UI port |
| 3 | `core/media/category` logic | 16 | backs the categories UI port (#138) |
| 4 | `core/media/release` logic | 36 | high coverage; dedup/identifier logic |
| 5 | `core/media` (broad) | 61 | highest coverage AND highest mutant count — scope the runner carefully, may need per-file batching |

For each addition: run `make mutation-py`, triage survivors (each survivor is
either a missing assertion → add it, or an equivalent mutant → note it), and
record the per-module score. Keep mutation **informational / nightly + on-demand**
(non-blocking) as today.

## Acceptance criteria
- [ ] `paths_to_mutate` includes at least orders 1–3 (quality/profile/category logic).
- [ ] `make mutation-py` completes in a bounded time (runner stays scoped to covering tests).
- [ ] Survivors from each newly-added module are triaged: real gaps get assertions,
      equivalents are documented.
- [ ] Per-module mutation scores recorded (PR description or a NOTES section).
- [ ] Mutation stays non-blocking (nightly + `make mutation-py`).

## Files
- `pyproject.toml` — `[tool.mutmut] paths_to_mutate`.
- `tests/unit/**` — assertions added where survivors reveal weak tests.
- `specs/QUAL-001-mutmut-scope-expansion.md` — this file.

## Notes
The exact module paths under `core/media/quality|profile|category` need a quick
`Glob`/read to pin the precise `.py` files (plugins live under
`couchpotato/core/media/...`). mutmut runtime ≈ mutants × covering-test runtime,
so favour adding the smaller, denser-tested logic files before the broad `media`
package.
