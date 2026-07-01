# UI-PORT-03 — Add-by-URL in the new UI (replaces the broken legacy bookmarklet)

## Problem

The legacy "userscript / bookmarklet / add-via-URL" feature is broken today (the
iframe embed returns JSON-encoded HTML, and the compiled-script route is
dead-shadowed by the API catch-all). Its actual resolver — the
`userscript.add_via_url` API view (`Userscript.getViaUrl`,
`couchpotato/core/plugins/userscript/main.py`) — still works and is independent
of the legacy UI: it resolves a page URL (IMDb/TMDB/Trakt/Letterboxd/etc.) to a
movie via the `userscript` providers and returns a dict. The new UI has no
add-by-URL entry point. This ports one in, so UI-CLEANUP-02 can delete the legacy
embed without losing the capability.

## Fix

1. **Route** in `couchpotato/ui/__init__.py` (mirror the existing `partial_search`
   at ~line 163 which calls `callApiHandler('movie.search', q=q)` and renders
   `partials/search_results.html`):
   - Add `GET {new_base}partial/add-via-url?url=...` → call
     `callApiHandler('userscript.add_via_url', url=url)`. Read `getViaUrl`
     (`main.py`) for the exact return shape (a dict — inspect whether it returns
     `{'movie': {...}}` / `{'error': ...}` / `{'success': bool}`) and render the
     resolved movie through the existing search-results movie card (reuse
     `partials/search_results.html` by passing `movies=[resolved]`, or a small
     dedicated partial if the shapes differ). On failure/no match, render a clear
     error/empty state consistent with the app's states.
2. **`/add/` supports `?url=`**: when `add_movie` (`ui/__init__.py:100-104`) is
   hit with a `?url=` query param, render `add.html` so it auto-resolves that URL
   on load (htmx `hx-trigger="load"` against the new partial, showing the
   resolved movie + an Add action). Keep the existing title-search box working.
   This is what a bookmarklet targets: `{host}/add/?url=<page-url>`.
3. **Bookmarklet UI**: surface a draggable bookmarklet on the add page (a small
   "Add from a movie site" disclosure) whose `href` is
   `javascript:(function(){window.location.href='{{ absolute_base }}add/?url='+encodeURIComponent(location.href)})()`.
   Use the app's real base URL. Plain page navigation — NO iframe, NO injected
   script, NO MooTools. Keep it accessible (real `<a>`, label, instructions).
4. Do NOT modify `couchpotato/core/plugins/userscript/main.py` — this task only
   consumes the existing `userscript.add_via_url` API. (UI-CLEANUP-02 handles the
   legacy plugin surface.)

## Acceptance criteria

- `GET {base}partial/add-via-url?url=<imdb url>` returns HTML rendering the
  resolved movie card (or a clear error state) — verified by calling
  `userscript.add_via_url` via `callApiHandler`.
- `GET {base}add/?url=...` renders a page that resolves + shows the movie.
- A bookmarklet is presented in the new UI, pointing at `/add/?url=`.
- No dependency on `index.html`, `clientscript`, or the legacy bundle.
- `ruff` clean; new + existing tests pass; `scripts/check_conformance.py` clean
  (the new template must use cp-* tokens, no raw hex / icon-* / w-10 h-5).

## Tests (TDD)

- `tests/unit/test_add_via_url.py`: the partial route resolves a URL (mock
  `callApiHandler('userscript.add_via_url', ...)` or the underlying event to
  return a known movie dict) and renders the movie card; the error/no-match path
  renders the error state; `/add/?url=` returns 200 and includes the auto-resolve
  wiring. Reuse the app-client fixture pattern from `tests/unit/test_fastapi_web.py`.
- Extend `tests/e2e/` only if practical; otherwise assert at the unit/route level.

## Files

- `couchpotato/ui/__init__.py` (new partial route + `/add/?url=` handling)
- `couchpotato/ui/templates/add.html` (url param handling + bookmarklet)
- possibly `couchpotato/ui/templates/partials/add_via_url_result.html` (new)
- `tests/unit/test_add_via_url.py` (new)
