# BUG-014: Pre-release qualities download before release date when theater date is unknown

## Problem
`MovieSearcher.couldBeReleased()` lets pre-release qualities (`cam`, `ts`, `tc`,
`r5`, `scr`) pass the ETA gate for a movie whose theater date is unknown
(`theater == 0`). The result is that CouchPotato treats such a pre-release as
"could be released now" and the searcher auto-downloads it — a low-quality
pre-release grabbed before the movie has any known release date.

This is common for Wanted movies: TheMovieDB frequently has no theater date for
upcoming films, so `theater` stays `0`.

## Root Cause
`couchpotato/core/media/movie/searcher.py`, `couldBeReleased()` (around line 376):

```python
if is_pre_release:
    # Prerelease 1 week before theaters
    if dates.get('theater') - 604800 < now:      # BUG: no "> 0" guard
        return True
else:
    # 12 weeks after theater release
    if dates.get('theater') > 0 and dates.get('theater') + 7257600 < now:  # correct guard
        return True
```

When `theater == 0`, the pre-release branch computes `0 - 604800 = -604800`,
which is `< now`, so it returns `True`. The non-pre-release branch directly
below it correctly guards with `dates.get('theater') > 0` and does not fire in
the same situation. Only the pre-release branch fails open.

## Fix Required
Add the same `dates.get('theater') > 0` guard to the pre-release branch so a
pre-release is only eligible when the theater date is actually known AND we are
within one week of it:

```python
if is_pre_release:
    # Prerelease 1 week before theaters
    if dates.get('theater') > 0 and dates.get('theater') - 604800 < now:
        return True
```

Do not change any other branch. In particular:
- The "no dates known, old movie" heuristic at the top of the method
  (`theater == 0 and dvd == 0` for movies a year or more old) must keep
  returning `True` — that path is intentional and unrelated.
- The negative-date "before 1972" branch (`theater < 0`) must be unchanged.

## Acceptance Criteria (write these as failing unit tests FIRST — TDD)
Test `couldBeReleased()` directly. A recent movie is one whose `year` is the
current year (so the top-of-method "old movie, no dates" heuristic does NOT
apply).

1. **RED → GREEN (the bug):** pre-release quality (`is_pre_release=True`),
   recent `year`, `dates={'theater': 0, 'dvd': 0}` → returns **False**
   (currently returns True).
2. Pre-release quality, recent `year`, theater date known and within 1 week
   (`theater = now + 3 days`) → returns **True** (unchanged behaviour).
3. Pre-release quality, recent `year`, theater date known but > 1 week away
   (`theater = now + 30 days`) → returns **False** (unchanged behaviour).
4. Non-pre-release quality, recent `year`, `dates={'theater': 0, 'dvd': 0}` →
   returns **False** (regression guard — was already correct, must stay).
5. Old movie (`year = current_year - 2`), `dates={'theater': 0, 'dvd': 0}` →
   returns **True** for both pre-release and non-pre-release (the "assume
   released" heuristic must be preserved).
6. `ruff check .` clean; full `pytest tests/unit/` green.

## Files to Change
- `couchpotato/core/media/movie/searcher.py` (`couldBeReleased` — add the guard)
- `tests/unit/` (new test module, e.g. `test_movie_searcher_eta.py`, covering
  the criteria above)

## Notes
- No mocking of time is strictly required: pass explicit `dates` computed from
  `int(time.time())` in the test and let the method read the real clock, or
  freeze `time.time()`/`date.today()` if the test module already has a helper.
  Prefer computing dates relative to `int(time.time())` at test time.
- Keep the diff minimal and match surrounding style (this file uses
  `dates.get('theater')`, spaces around operators as shown).
- Addendum (review follow-up): all `dates.get('theater')`/`dates.get('dvd')`
  calls in the is_pre_release branch and its sibling now carry explicit `0`
  defaults, so a partial `dates` dict missing a key returns False instead of
  raising `TypeError` (latent-fragility hardening flagged in PR review).
