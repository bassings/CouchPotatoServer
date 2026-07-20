# BUG-015: Manual refresh/search serves stale results from the 30-minute provider cache

## Problem
When a user clicks **Refresh** on a movie (or otherwise triggers a manual
search), CouchPotato re-runs a full provider search — but the newznab/torznab
(Jackett) and torrentpotato providers cache their indexer responses for 30
minutes (`cache_timeout = 1800`), keyed on `md5(search_url)`. Because the search
URL for a given movie+quality is deterministic, a manual refresh within 30
minutes of the previous search replays the *cached* indexer response and shows
no newly-posted releases. The refresh appears to do nothing.

The 30-minute cache is intentional politeness for the *automatic* background
sweep (it must stay). The bug is that a **user-initiated** search does not
bypass it.

## Root Cause
The `manual` flag already exists at the top of the search chain but is never
threaded down to the provider HTTP fetch:

- `couchpotato/core/media/movie/searcher.py` → `single(..., manual=...)` already
  knows whether this is a manual search, and calls
  `fireEvent('searcher.search', search_protocols, movie, quality, single=True)`
  **without** passing `manual`.
- `couchpotato/core/media/_base/searcher/main.py` → `search(self, protocols,
  media, quality)` dispatches to providers via
  `fireEvent('provider.search.<proto>.<type>', media, quality, merge=True)` —
  no `manual`.
- Providers `search(self, media, quality)` (base `YarrProvider.search`,
  `newznab.search`, `torrentpotato.search`) don't accept `manual`.
- `newznab._searchOnHost` and `torrentpotato.search` hardcode
  `cache_timeout = 1800`.

## Fix Required
Thread an optional `manual=False` flag from the searcher down to the two
providers that hardcode the 30-minute cache, and bypass the cache when it is a
manual search. Use `cache_timeout = -1` on manual to force a live fetch
(`getCache`/`_fetch_and_cache` treats `cache_timeout <= 0` as "fetch, don't
store" — verify this in `couchpotato/core/plugins/base.py` before relying on it;
`-1` must NOT write the fresh result into the cache, so the next automatic
search still fetches its own copy rather than reusing a possibly-different manual
result set).

### Threading (keep defaults so nothing else breaks)
1. `couchpotato/core/media/movie/searcher.py`: pass `manual = manual` into the
   `fireEvent('searcher.search', ...)` call.
2. `couchpotato/core/media/_base/searcher/main.py`:
   `def search(self, protocols, media, quality, manual = False)` and pass
   `manual = manual` into the `provider.search.*` fireEvent.
3. `couchpotato/core/media/_base/providers/base.py`:
   `YarrProvider.search(self, media, quality, manual = False)` — accept and
   ignore it (all inheriting providers that don't override `search` are covered
   by this default).
4. `couchpotato/core/media/_base/providers/nzb/newznab.py`:
   `search(self, media, quality, manual = False)`, thread `manual` into
   `_searchOnHost(...)`, and use
   `cache_timeout = -1 if manual else 1800` at BOTH `getRSSData` sites
   (lines ~50 and ~100).
5. `couchpotato/core/media/_base/providers/torrent/torrentpotato.py`:
   `search(self, media, quality, manual = False)` and use
   `cache_timeout = -1 if manual else 1800` at the `getJsonData` site (~line 67).

Do NOT change the other ~20 providers — they inherit `YarrProvider.search` and
do not hardcode the 1800s cache; their own default (300s or provider-specific)
is out of scope for this fix.

## Acceptance Criteria (TDD — failing tests FIRST)
1. **Manual search bypasses cache:** with `manual=True`, `newznab.search`
   requests its RSS data with `cache_timeout = -1` (assert the value passed to
   `getRSSData`, e.g. by patching `getRSSData` and inspecting kwargs).
2. **Automatic search still caches:** with `manual=False` (default),
   `newznab.search` requests with `cache_timeout = 1800`.
3. Same two assertions for `torrentpotato.search` (`getJsonData`).
4. **Signature back-compat:** calling `provider.search(media, quality)` with no
   `manual` arg still works (defaults to the cached path) — a regression guard so
   existing callers and inheriting providers don't break.
5. `searcher.single(..., manual=True)` results in the provider being called with
   `manual=True` (integration-style assertion through `searcher.search`), and
   `manual=False`/absent results in `manual=False`.
6. `ruff check .` clean; full `pytest tests/unit/` green; UI E2E unaffected.

## Files to Change
- `couchpotato/core/media/movie/searcher.py`
- `couchpotato/core/media/_base/searcher/main.py`
- `couchpotato/core/media/_base/providers/base.py`
- `couchpotato/core/media/_base/providers/nzb/newznab.py`
- `couchpotato/core/media/_base/providers/torrent/torrentpotato.py`
- `tests/unit/` (new tests for the cache-timeout threading)

## Notes
- Verify `_fetch_and_cache` in `couchpotato/core/plugins/base.py`: a negative
  `cache_timeout` currently means "fetch but don't store" (`data and
  cache_timeout > 0 and use_cache` gates the `setCache`). Confirm this holds so
  `-1` gives a live, un-stored fetch. If instead a different sentinel is needed,
  adjust the spec — but do not weaken the 1800s automatic-search caching.
- This is a behaviour change to a hot path; keep the diff tight and rely on the
  default `manual=False` everywhere so the automatic sweep is byte-for-byte
  unchanged.

## Follow-up: cache bypass must NOT apply to the full-library "Search All" sweep

Review found a design gap in the original threading above: `searchAllView()`
fires `movie.searcher.all` with `manual=True`, and `searchAll()` called
`self.single(media, search_protocols, manual = manual)` for **every** active
movie in the library. Once `manual=True` bypassed the provider cache
end-to-end, clicking "Search All" would force a live, uncached HTTP fetch
against every configured indexer for the *entire* library in one pass — the
opposite of what the 30-minute cache exists to prevent (indexer rate-limiting
and IP bans from CouchPotato hammering it). Only genuinely single-movie manual
searches (per-movie Refresh button, `tryNextRelease`, `markFailedView`) are
supposed to get the live fetch.

### Fix: `bypass_cache` — decoupled from `manual`

`manual` inside `single()` has two independent jobs: (a) status-gating
override + `ignore_eta` (must still apply for `searchAll`, so a full sweep
still searches movies it would otherwise skip/throttle), and (b) whether the
provider HTTP cache is bypassed (must NOT apply for `searchAll`). A new
`bypass_cache` keyword decouples (b) from (a):

- `MovieSearcher.single(self, movie, search_protocols = None, manual = False, force_download = False, bypass_cache = None)`.
  Inside: `if bypass_cache is None: bypass_cache = manual`. So every existing
  single-movie manual caller (the `movie.searcher.single` event, `tryNextRelease`,
  `markFailedView`) is unchanged — no caller edits needed, cache bypass still
  follows `manual`.
- `searchAll()` calls `self.single(media, search_protocols, manual = manual, bypass_cache = False)` —
  the sweep still searches with manual's status-gating/`ignore_eta` semantics,
  but the resolved `bypass_cache` is pinned to `False`, so the provider cache
  is never bypassed for the full-library sweep.
- The provider search call becomes
  `fireEvent('searcher.search', search_protocols, movie, quality, manual = bypass_cache, single = True)` —
  i.e. `Searcher.search`/providers keep seeing a single `manual` flag (no
  signature changes downstream); `single()` just resolves which value that
  flag carries before firing it.

### Tests

`tests/unit/test_provider_manual_cache.py`:
- `TestMovieSearcherSingleThreadsManual.test_manual_true_bypass_cache_false_threads_manual_false` —
  `single(movie, manual=True, bypass_cache=False)` → `searcher.search` receives `manual=False`.
- `TestMovieSearcherSingleThreadsManual.test_bypass_cache_none_defaults_to_manual_value` —
  `single(movie, manual=True)` (bypass_cache omitted) → `searcher.search` still receives `manual=True`.
- `TestMovieSearcherSearchAllCacheScoping.test_search_all_manual_calls_single_with_manual_true_bypass_cache_false` —
  `searchAll(manual=True)` calls `single()` with `manual=True, bypass_cache=False`.
- `TestMovieSearcherSearchAllCacheScoping.test_search_all_manual_does_not_bypass_provider_cache` —
  end-to-end through the real `single()`: `searchAll(manual=True)` results in `searcher.search` receiving `manual=False`.
