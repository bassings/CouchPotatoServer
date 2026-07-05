# REG-002 — Run blocking API handlers off the event loop

## Problem

Every FastAPI route in this app is `async def` and calls the synchronous,
blocking `callApiHandler()` directly on the event loop — both the main API
dispatcher (`_dispatch_api` in `couchpotato/__init__.py`) and all the
`/partial/*` + page handlers in `couchpotato/ui/__init__.py`. Any slow handler
therefore freezes the **entire server** for its duration.

This was invisible while the slowest handlers (the chart scrapers) were dead
(see REG-001). With them restored, it's fatal — measured on this branch:

- cold `charts.view` = **84s** of network scraping (IMDB, Blu-ray.com, …)
- while it runs, concurrent `GET /settings/` and `GET /wanted/` hang
  (curl timed out at 40s); after it finishes they return instantly
- the full Playwright E2E suite fails 9 tests with `page.goto` timeouts
  (settings, wanted, navigation, search specs) purely from this head-of-line
  blocking — on master (charts dead) the same suite is 130/130.

## Fix

Dispatch blocking handler work in the threadpool instead of on the loop, via
`starlette.concurrency.run_in_threadpool` (Starlette ships it; it accepts
kwargs):

1. `couchpotato/__init__.py` `_dispatch_api()`: the
   `result = callApiHandler(route, **kwargs)` call becomes
   `result = await run_in_threadpool(callApiHandler, route, **kwargs)`.
   Leave the `api_nonblock` long-poll path as-is (it's already
   callback/future-based) unless it also calls blocking code inline — read it
   and decide; explain in your report.
2. `couchpotato/ui/__init__.py`: every `callApiHandler(...)` call site inside
   the async handlers (partial_movies, partial_movie_detail, partial_search,
   partial_add_via_url, partial_suggestions, partial_charts,
   partial_settings_profiles, partial_profiles — enumerate by grep, don't
   trust this list) gets the same `await run_in_threadpool(...)` treatment.
3. Template rendering and other CPU-trivial work stays on the loop — do NOT
   blanket-wrap everything; only the `callApiHandler` dispatches.

### Why this is safe

- The DB layer is already multi-thread aware: `SQLiteAdapter` uses
  `check_same_thread=False` plus an `RLock` around writes, and background
  threads (searchers, scheduler jobs, renamer scans) already call handlers and
  the DB concurrently with web requests today. The event-loop serialization
  was accidental, not a designed invariant.
- Known technical debt (CLAUDE.md): read-modify-write races exist in some DB
  patterns regardless; this change restores the legacy threaded execution
  model the code was written for rather than introducing a new one.

## Tests (TDD — write first, watch fail on current code)

`tests/unit/test_api_dispatch_concurrency.py`:

- Build the app via `couchpotato.create_app(...)` the same way existing tests
  do (see `tests/unit/test_fastapi_web.py` / `test_api_auth.py` for the
  bootstrap pattern), register two fake API views through
  `couchpotato.api.addApiView`: `slowtest.sleep` (blocks ~1.5s via
  `time.sleep`) and `fasttest.ping` (returns immediately).
- Using `httpx.AsyncClient` + `asyncio.gather`, fire the slow request and,
  ~0.2s later, the fast one. Assert the fast response arrives well before the
  slow one completes (e.g. fast elapsed < 1.0s while slow elapsed ≥ 1.5s).
  On current code this fails (fast waits behind slow); after the fix it
  passes.
- Keep the timing margins generous (no flaky <100ms assertions).

## Acceptance criteria

- New concurrency test fails before the fix, passes after.
- `.venv/bin/python -m pytest tests/unit/ -q` fully green (770 expected).
- `ruff check .` clean.
- Boot check from this worktree:
  `/Volumes/Storage/home/scott.b/repos/CouchPotatoServer/.venv/bin/python CouchPotato.py --data_dir=.reg002-data --console_log`,
  wait ~15s, then with the api key from `.reg002-data/config.ini`: start
  `curl "http://localhost:5050/api/<key>/charts.view"` in the background and
  immediately `curl -m 10 http://localhost:5050/login/` — the login page must
  return in well under 10s while charts is still fetching. Kill the server and
  delete `.reg002-data` afterwards (not gitignored — do not commit it).
- No UI/template changes.
- Conventional commit on `fix/reg-001-plugin-loading`. **STOP after
  committing — do NOT push.**

## Files

- `couchpotato/__init__.py`
- `couchpotato/ui/__init__.py`
- `tests/unit/test_api_dispatch_concurrency.py` (new)
