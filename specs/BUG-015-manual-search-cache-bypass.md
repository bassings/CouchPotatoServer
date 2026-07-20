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
- `couchpotato/core/plugins/base.py` (`getCache`/`_fetch_and_cache` —
  `cache_timeout <= 0` gating; no signature change, verified/documented, see Notes)
- `tests/unit/` (new tests for the cache-timeout threading)

## Notes
- `couchpotato/core/plugins/base.py` `getCache` (not just the store path) is
  what actually implements the `cache_timeout <= 0` contract this fix relies
  on. `getCache` computes `skip_cache_read = cache_timeout is not None and
  cache_timeout <= 0` and uses that single flag twice: it gates the pre-lock
  cache read (`if use_cache and not skip_cache_read: ...Env.get('cache').get(...)`),
  and it gates the post-lock double-check inside the stampede-prevention
  section (`if not skip_cache_read: # Double-check...`). The
  stampede-protection lock itself (`self._get_cache_lock(cache_key_md5)`) is
  still always acquired whenever `use_cache` is true and a `url` was given —
  it is gated on `use_cache`, not on `cache_timeout` — so concurrent fetches
  for the same key are still serialized even for a manual/`cache_timeout=-1`
  request. Once the lock is held (or skipped because `use_cache` is false),
  the call always reaches `_fetch_and_cache`, which performs the real
  `urlopen` and only then applies the *separate* store-path gate: `if data and
  cache_timeout > 0 and use_cache: self.setCache(...)`. Net effect for
  `cache_timeout = -1`: no stale cache entry (even one written moments ago by
  an automatic search) can satisfy the read at any point — before or after
  the lock — while the lock still cooperates with other in-flight fetches for
  the same key, and the fresh result is never written back, so the next
  automatic search still fetches and caches its own copy.
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

## Decision record: bulk Refresh (wanted.html `bulkRefresh`) is accepted as-is, unscoped

The new UI's bulk Refresh action (`bulkRefresh` in `couchpotato/ui/templates/wanted.html`)
fires one `movie.refresh` request per selected movie (`Promise.all(ids.map(id =>
fetch(...)))`). Each of those independently flows through
`MediaPlugin.refresh` → metadata update → `fireEventAsync('movie.searcher.single',
media, manual=True)`, so every selected movie's search resolves
`bypass_cache = manual = True` — i.e. bulk Refresh bypasses the provider cache
for every movie the user selected, same as a single-movie Refresh.

This is a **conscious decision, not an oversight**: unlike `searchAll()`
(which sweeps the entire library unconditionally), bulk Refresh's blast
radius is bounded by the user's explicit selection — a deliberate, visible
action, not a background sweep. Verified during review:
- **Bounded scope:** load scales with how many movies the user selected, not
  library size.
- **No cross-request queue serialization:** `bulkRefresh`'s `Promise.all`
  sends the selected movies' refresh requests concurrently, and each request
  spawns its own `fireEventAsync`/`schedule.queue` thread — `schedule.queue`
  only serializes handlers *within* one request, it does not serialize the N
  concurrent per-movie refreshes against each other. (Earlier drafts of this
  note assumed `schedule.queue` provided that cross-request serialization; it
  does not — corrected here after checking `couchpotato/core/_base/scheduler.py`
  and `couchpotato/core/event.py`.)
- **What actually protects the indexers:** the per-host `HttpClient` rate
  limiter (`couchpotato/core/http_client.py`, `_wait_for_rate_limit`), wired
  from each provider's `http_time_between_calls` (newznab: 2s, torrentpotato:
  1s, default: 10s — see `couchpotato/core/plugins/base.py`). This is a real,
  enforced FIFO/blocking limiter per host, so concurrent manual searches
  hitting the *same* indexer still get serialized there; only searches
  spread across *different* indexers run truly in parallel. For a selection
  of a realistic size (tens of movies, not thousands), the per-host throttle
  keeps request pacing to any single indexer sane even with the cache
  bypassed.

If bulk Refresh proves problematic in practice (e.g. users routinely
select hundreds of movies at once), a follow-up could thread
`bypass_cache = False` for bulk-originated refreshes specifically — most
directly by having `bulkRefresh`/`MediaPlugin.refresh` pass a
`bulk = True` flag down to `movie.searcher.single`, which `single()` could
use to force `bypass_cache = False` the same way `searchAll()` does today —
without touching the per-movie manual entry points (single Refresh,
`tryNextRelease`, `markFailedView`) that must keep bypassing the cache.
