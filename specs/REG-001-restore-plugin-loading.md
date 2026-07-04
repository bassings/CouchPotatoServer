# REG-001 — Restore silently-dropped plugins (fireEvent import regression from #148)

## Problem

PR #148 removed `from couchpotato.core.event import fireEvent` from
`couchpotato/__init__.py` (it looked unused *within that file*). But nine plugin
modules import it **via the package root** — `from couchpotato import fireEvent` —
and `Loader.loadModule()` (`couchpotato/core/loader.py:151`) catches
`ImportError` and logs it at **DEBUG**, so all nine plugins vanished silently.
CI stayed green because nothing imports these modules in tests and the loader
never surfaces the failure.

### Confirmed casualties (verified on v3.8.0, local + production)

Automation / chart providers (`couchpotato/core/media/movie/providers/automation/`):
- `imdb.py` — IMDB charts **and** IMDB watchlist automation
- `bluray.py` — Blu-ray.com chart
- `tmdb_charts.py` — TMDB charts
- `popularmovies.py`
- `yifypopular.py`
- `trakt/main.py` (`from couchpotato import Env, fireEvent`) — Trakt watchlist automation

Userscript URL resolvers (`couchpotato/core/media/movie/providers/userscript/`):
- `filmweb.py`, `reddit.py`, `rottentomatoes.py`

### User-visible symptoms
- Suggestions page → "Charts" section: "No charts available" (charts.view returns 0 charts).
- Settings: all chart/automation provider config sections gone (their `config`
  blocks never register).
- Trakt/IMDB watchlist automation silently dead.
- Add-via-URL no longer resolves filmweb/reddit/rottentomatoes URLs.

The "For You" (suggestion.view) feature is NOT broken — `couchpotato/core/plugins/suggestion.py`
doesn't use the root import.

## Fix

1. **The nine modules:** import from the canonical homes instead of the package root:
   - `from couchpotato import fireEvent` → `from couchpotato.core.event import fireEvent`
   - `trakt/main.py`: `from couchpotato import Env, fireEvent` →
     `from couchpotato.environment import Env` + `from couchpotato.core.event import fireEvent`
   - Do NOT re-add the re-export to `couchpotato/__init__.py` (ruff would flag it
     unused; prod `custom_plugins/` is empty so nothing external relies on it).

2. **Loader visibility (the meta-bug):** in `Loader.loadModule()`, log
   `ImportError`/`SyntaxError` at **ERROR** with the traceback (keep returning
   `None` so one broken plugin doesn't abort the rest). A plugin that fails to
   import must never again disappear silently.

3. **Regression tests (TDD — write these first, watch them fail on current code):**
   a. `tests/unit/test_plugin_import_sweep.py`: walk every module under
      `couchpotato.core` with `pkgutil.walk_packages` and import each one;
      collect failures and assert the list is empty (report module + error in
      the assertion message). Skip nothing except non-package dirs
      (`static/` has no `__init__.py`, so walk_packages won't yield it).
      Note: `import couchpotato` needs `libs/` on `sys.path`
      (`CouchPotato.py:28` does `sys.path.insert(0, .../libs)`); mirror that in
      the test/conftest if pytest doesn't already provide it. This test must
      fail on current master naming exactly the nine modules above.
   b. Loader test: a module raising ImportError gets logged at ERROR
      (use `caplog` against `Loader.loadModule` with a fabricated module name,
      or monkeypatch importlib).

## Acceptance criteria

- New sweep test fails before the fix (listing the 9 modules), passes after.
- `.venv/bin/python -m pytest tests/unit/ -q` fully green.
- `ruff check .` clean.
- Boot check: `.venv/bin/python CouchPotato.py --data_dir=.reg001-data --console_log`
  logs `Loaded media_movie_providers_automation:` lines for imdb, bluray,
  tmdb_charts, popularmovies, yifypopular, trakt AND
  `Loaded media_movie_providers_userscript:` for filmweb, reddit, rottentomatoes;
  `GET /api/<key>/settings` contains sections `imdb`, `bluray`, `tmdb_charts`,
  `popularmovies`, `yifypopular`, `trakt`. Kill the server and delete
  `.reg001-data` afterwards (it is not gitignored — do not commit it).
- No UI/template changes → no E2E updates needed.
- Conventional commit(s) locally. **STOP after committing — do NOT push.**

## Files

- `couchpotato/core/media/movie/providers/automation/{imdb,bluray,tmdb_charts,popularmovies,yifypopular}.py`
- `couchpotato/core/media/movie/providers/automation/trakt/main.py`
- `couchpotato/core/media/movie/providers/userscript/{filmweb,reddit,rottentomatoes}.py`
- `couchpotato/core/loader.py`
- `tests/unit/test_plugin_import_sweep.py` (new)
