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

### The actual scale: the ETA gate has never worked at all

An initial reading of this bug assumed empty `dates` was an occasional
failure under load. It is not. **`movie.info.release_date` has no registered
handler anywhere in the codebase.**

```
$ grep -rn "addEvent(" couchpotato --include "*.py" | grep -i release_date
couchpotato/core/media/movie/_base/main.py:55:  addEvent('movie.update_release_dates', self.updateReleaseDate)
```

Only the *outer* event is registered. The inner one is fired but never
handled, and `fireEvent` returns `[]` when a name has no handlers
(`couchpotato/core/event.py:95`). Verified directly:

```
>>> fireEvent('movie.info.release_date', identifier='tt1', merge=True)
[]
```

So `updateReleaseDate()` returns empty for **every movie on every search**,
`not dates` is always true, and `couldBeReleased()` therefore always returns
True. The ETA gate is a no-op: CouchPotato downloads whatever it finds,
whenever it finds it. That — not an occasional provider hiccup — is why a
batch of newly-added films downloaded before their release dates.

It also means the naive fix is dangerous. Removing `not dates` while nothing
populates `dates` flips the gate from always-open to always-**closed** for
any movie whose year is the current year (older years exit early via the
line-381 heuristic). Those films would never auto-download until the calendar
rolled them into the "old movie" branch — roughly 16 months. That trades an
early-download bug for a no-download bug.

### The data already exists

The TMDB provider stores the release date on the movie document
(`providers/info/themoviedb.py:256`):

```python
'released': str(movie.get('release_date')),   # 'YYYY-MM-DD', or 'None'
```

Nothing ever converts it into the `{theater, dvd}` epoch mapping the gate
reads. Deriving it there requires no extra API call and works for any info
provider that populates `released`.

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

Closing the gate is only safe once something opens it, so the population fix
and the guard fix must land together.

1. **Populate the dates.** In `MovieBase.updateReleaseDate()`, when
   `movie.info.release_date` yields nothing usable (i.e. always, today),
   derive the mapping from the `released` string the info provider already
   stored. A module-level `releaseDatesFromInfo(info)` keeps this testable
   without a database:
   - parse `'YYYY-MM-DD'` to a UTC-midnight epoch → `{'theater': <epoch>, 'dvd': 0}`
   - return `{}` for anything unparseable, including the literal `'None'`
     that `str(movie.get('release_date'))` produces when TMDB has no date
   - do **not** write derived dates back to the document. Deriving is free,
     and the current code's unconditional `db.update(media)` on every search
     is a write per movie per cycle for no benefit.

2. **Make the wait configurable.** The existing rule unlocks a download 12
   weeks after the theatrical date (`theater + 7257600 < now`), which was
   written when physical media was the target. Replace the hardcoded constant
   with a new `wait_for_release` setting, **default 0 days** — a film unlocks
   once its release date has passed. Users who want the old conservative
   behaviour can set 84.

   `couldBeReleased()` takes `wait_days` as a parameter (defaulting to 0)
   rather than reading `self.conf` internally, so it stays a pure function
   and the existing tests can keep instantiating it via `object.__new__`.
   `MovieSearcher.single()` reads the setting and passes it.

   The dvd-date rules are left untouched: they are a separate unlock path and
   nothing populates `dvd` today, so changing them would be unverifiable
   churn.

3. Normalise `dates` once at the top of `couldBeReleased()`
   (`dates = dates or {}`). Note the caller can supply a **list** — an
   unhandled `fireEvent` returns `[]`, and existing databases have `[]`
   stored in `info['release_date']` from previous runs — so `.get()` is not
   safe without this.

4. Remove `not dates` from the pre-1972 condition, leaving only the negative
   sentinel:

   ```python
   if dates.get('theater', 0) < 0 or dates.get('dvd', 0) < 0:
       return True
   ```

   An empty mapping then falls through to the closing `return False` —
   "unknown ⇒ not yet released". Safe only because of step 1.

5. **Leave the top-of-method heuristic at line 381 alone.** It also tests
   `not dates`, but there the combination is "old movie *and* no dates", which
   is a deliberate and correct assumption (an unreleased film cannot have a
   year two or more in the past). AC5 of BUG-014 pins that behaviour. It also
   remains the safety net for a movie whose `released` field is missing.

6. Reword the `always_search` description to state that it also bypasses the
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
- [ ] AC8: `releaseDatesFromInfo({'released': '2026-08-14'})` returns a
      `theater` epoch matching 2026-08-14 UTC midnight.
- [ ] AC9: it returns `{}` for a missing key, `''`, the literal `'None'`,
      a malformed string, and a non-string type — never raising.
- [ ] AC10: `updateReleaseDate()` falls back to the derived dates when
      `movie.info.release_date` returns `[]` (its real behaviour today), and
      does not write the derived value back to the document.
- [ ] AC11: a real provider result still wins over the derived fallback.
- [ ] AC12: `couldBeReleased` honours `wait_days` — a movie released
      yesterday is releasable at `wait_days=0` but not at `wait_days=7`; one
      released 100 days ago is releasable at both.
- [ ] AC13: a `wait_for_release` setting exists, defaults to `0`, and
      `MovieSearcher.single()` passes it through.
- [ ] AC14: the end-to-end case that started this — an unreleased film
      (theatre date in the future) with a fully populated info document is
      NOT releasable at the default setting.

## Affected Files

- `couchpotato/core/media/movie/searcher.py` — `couldBeReleased()`, and the
  `always_search` config description
- `tests/unit/test_movie_searcher_eta.py` — new cases (AC1–AC5)

## Residual risk

Closing the gate means a movie with no derivable date and a current-year
`year` will not auto-download until the calendar rolls it into the line-381
"old movie" heuristic. Two things keep that narrow:

- The TMDB provider derives `year` **from** `release_date`
  (`themoviedb.py:229`), so a movie with no release date generally has no
  year either — and `year is None` routes to the line-381 heuristic, which
  fails **open**. The dangerous combination (year known, release date
  unknown) requires the year to have come from somewhere other than TMDB's
  release date.
- A manual search is unaffected: `manual=True` sets `ignore_eta`, and
  `release.manual_download` bypasses `couldBeReleased()` entirely. The
  searcher also surfaces out-of-ETA results in the dashboard for manual
  selection.

If this proves to bite, the fix is a real `movie.info.release_date` provider
handler (TMDB exposes a per-country `release_dates` endpoint with both
theatrical and digital dates), not re-opening the gate.

## Out of scope

- Changing `always_search` behaviour (see scope decision above).
- Making `search_on_add` wait for release-date resolution. Worth considering
  separately, but the fix above already prevents the bad download; ordering
  work here risks delaying legitimate adds.
