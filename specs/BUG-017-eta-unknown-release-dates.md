# BUG-017: Unknown release dates are treated as "already released"

## Problem

A user bulk-added a batch of new movies and some began downloading before
their release date.

This is **not** the BUG-014 pre-release hole — that fix (#190) is present in
the running v3.10.0 and guards the `is_pre_release` branch. This is a
different path through the same method.

`MovieSearcher.couldBeReleased()` (`couchpotato/core/media/movie/searcher.py:391`):

```python
# For movies before 1972
if not dates or dates.get('theater', 0) < 0 or dates.get('dvd', 0) < 0:
    return True
```

The comment states the intent: a **negative** epoch timestamp is the
pre-1970/pre-1972 sentinel, so such movies are assumed long released. But
`not dates` was folded into the same condition, which means an **empty or
missing** `dates` dict also returns "could be released".

Empty is exactly what the caller supplies when the lookup fails.
`MovieBase.updateReleaseDate()` (`couchpotato/core/media/movie/_base/main.py:434`)
returns `{}` from its exception handler, and also yields `{}` whenever the
info provider simply has no `release_date` for the title yet.

So: **"we don't know when this comes out" is read as "it's out"**, and the
searcher proceeds to download.

Note the asymmetry that makes this a latent trap rather than an obvious one —
a dict with explicit zeros behaves correctly:

| `dates` | current result | correct |
|---|---|---|
| `{'theater': 0, 'dvd': 0}` | False (too early) ✓ | False |
| `{}` | **True (downloads)** ✗ | False |
| `None` | **True (downloads)** ✗ | False |

`{'theater': 0, 'dvd': 0}` is covered by an existing test
(`test_non_pre_release_with_unknown_dates_returns_false`); `{}` and `None`
are not, which is why BUG-014's work didn't surface this.

### Why bulk-adding triggers it

`search_on_add` defaults to on (`searcher.py` config block), so a search fires
immediately per movie as it is added. Adding many movies at once is precisely
when info-provider calls are most likely to be slow, rate-limited, or
incomplete — producing the empty `dates` dict for some fraction of the batch.
That matches the reported "added a bunch, some downloaded early".

## Secondary finding: `always_search` under-describes itself

`always_search` is documented as:

> Search for movies even before there is a ETA. Enabling this will probably
> get you a lot of fakes.

But at `searcher.py:268` it is also one of the three conditions that authorise
the **download**:

```python
if (force_download or not could_not_be_released or always_search) and \
        fireEvent('release.try_download_result', ...):
```

So the setting does not merely widen searching, it disables the ETA download
gate entirely. Anyone who enabled it expecting "search early, show me
results, let me pick" gets automatic pre-ETA grabs.

**Scope decision: do not change the behaviour.** Users have configured around
the current semantics, and silently narrowing an opt-in setting is its own
regression. Fix the description so it states the download consequence.

## Fix Required

1. Normalise `dates` once at the top of `couldBeReleased()`
   (`dates = dates or {}`), so the remaining `.get()` calls are safe now that
   the `not dates` short-circuit is being removed from the pre-1972 branch.

2. Remove `not dates` from the pre-1972 condition, leaving only the negative
   sentinel:

   ```python
   if dates.get('theater', 0) < 0 or dates.get('dvd', 0) < 0:
       return True
   ```

   An empty dict then falls through every branch to the method's closing
   `return False` — "unknown ⇒ not yet released". No new branch is needed.

3. **Leave the top-of-method heuristic at line 381 alone.** It also tests
   `not dates`, but there the combination is "old movie *and* no dates", which
   is a deliberate and correct assumption (an unreleased film cannot have a
   year two or more in the past). AC5 of BUG-014 pins that behaviour.

4. Reword the `always_search` description to state that it also bypasses the
   ETA gate for downloads, not just searching.

## Acceptance Criteria

- [ ] AC1 (bug repro): `couldBeReleased(False, {}, year=<current year>)`
      returns False. Fails against the unfixed code.
- [ ] AC2: same for `dates=None` — must return False, not raise.
- [ ] AC3: same for `is_pre_release=True` with `{}` / `None`.
- [ ] AC4 (regression): the negative-epoch sentinel still returns True —
      `{'theater': -1}` and `{'dvd': -1}`.
- [ ] AC5 (regression): an old movie with no dates still returns True via the
      line-381 heuristic, for `{}`, `None` and `{'theater': 0, 'dvd': 0}`.
- [ ] AC6 (regression): every existing case in
      `tests/unit/test_movie_searcher_eta.py` still passes unchanged.
- [ ] AC7: `always_search`'s description states that it also enables
      downloading before the ETA.

## Affected Files

- `couchpotato/core/media/movie/searcher.py` — `couldBeReleased()`, and the
  `always_search` config description
- `tests/unit/test_movie_searcher_eta.py` — new cases (AC1–AC5)

## Out of scope

- Changing `always_search` behaviour (see scope decision above).
- Making `search_on_add` wait for release-date resolution. Worth considering
  separately, but the fix above already prevents the bad download; ordering
  work here risks delaying legitimate adds.
