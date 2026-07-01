# UI-CLEANUP-01 — Retire the legacy MooTools/SCSS asset layer

> **Implementation note (deviation from this spec — read first).** As written,
> the delete-list and acceptance grep below would remove `clientscript.py`, the
> 4 compiled `combined.*` bundles, `static/fonts/**`, `index.html`, and
> `index()`. During implementation a live consumer was found:
> `couchpotato/core/plugins/userscript/main.py` (`Userscript.iFrame`, the
> `userscript` API view) calls `index()`, which renders `index.html` via the
> `clientscript.*` events. That whole chain was therefore **kept**, and only the
> genuinely-orphaned assets were deleted. So the acceptance grep below does
> **not** come back clean for `clientscript`/`combined.min`/`static/fonts` — that
> is expected. Full retirement is deferred to follow-up **UI-CLEANUP-02**, gated
> on porting/removing the userscript add-via-URL embed. See `specs/UI-MIGRATION.md`.

## Problem

The classic `/old` MooTools UI is dead: `/old/*` is a redirect-only shim
(`couchpotato/__init__.py`), and the old `views`/`addView` machinery that rendered
`index.html`/`api.html`/`database.html` is populated but never read. The legacy
asset layer (SCSS sources + compiled `combined.min.css`, the icon font + Open Sans
+ Lobster binaries, the MooTools/Uniform/classic JS, and `clientscript.py`) still
ships but is now unreferenced by the modern UI (`couchpotato/ui/**`) — dead weight.

**Precondition (already done in UI-PORT-02):** `couchpotato/templates/login.html`
has been ported to the Tailwind design system and no longer calls
`fireEvent('clientscript.*')`. `clientscript.py` therefore has no live consumer.
Re-verify this before deleting: `grep -rn "clientscript" couchpotato/templates/`
must return nothing.

## What the modern UI needs — PRESERVE (do NOT delete)

Verified via `grep` over `couchpotato/ui/templates/**`, the modern UI references
ONLY these under `couchpotato/static/`:
- `static/scripts/ui/**` (index.js, suggestion-loader.js, …)
- `static/scripts/vendor/new-ui/**` (alpine-3.x.min.js, htmx-2.0.4.min.js, tailwindcss-cdn.js)
- `static/icons/**`, `static/images/**`, `static/manifest.json`
Preserve all of the above. `login.html` uses the Tailwind CDN + Google-Fonts Inter
(not `static/fonts/**`).

## Fix — delete the legacy layer

Delete the following (verify each is unreferenced by `couchpotato/ui/**` and by any
served route/test first; if anything IS still referenced, STOP and report instead
of deleting it):

1. **Styles:** `couchpotato/static/style/**` (all: `_fonts.scss`, `_mixins.scss`,
   `main.scss`, `login.scss`, `api.scss`, `settings.scss`, `combined.min.css`).
2. **Fonts:** `couchpotato/static/fonts/**` (icon font `icons.*`, `Lobster-*`,
   `OpenSans-*`, `config.json`).
3. **Legacy JS** under `couchpotato/static/scripts/`:
   `combined.vendor.min.js`, `combined.base.min.js`, `combined.plugins.min.js`,
   `couchpotato.js`, `api.js`, `page.js`, `block.js`, the `page/`, `block/`,
   `library/` directories, and the MooTools-era `vendor/` libs
   (`mootools.js`, `mootools_more.js`, `dynamics.js`, `fastclick.js`,
   `history.js`, `Array.stableSort.js`, `requestAnimationFrame.js`).
   **Keep `vendor/new-ui/` and `ui/`.**
4. **Dead templates:** `couchpotato/templates/index.html`,
   `couchpotato/templates/api.html`, `couchpotato/templates/database.html`.
   **Keep `login.html`.**
5. **Plugin SCSS sources** (9 files, orphaned — no build pipeline consumes them):
   `couchpotato/core/media/movie/_base/static/movie.scss`,
   `couchpotato/core/media/_base/search/static/search.scss`,
   `couchpotato/core/plugins/wizard/static/wizard.scss`,
   `couchpotato/core/plugins/category/static/category.scss`,
   `couchpotato/core/plugins/quality/static/quality.scss`,
   `couchpotato/core/plugins/userscript/static/userscript.scss`,
   `couchpotato/core/plugins/profile/static/profile.scss`,
   `couchpotato/core/plugins/log/static/log.scss`,
   `couchpotato/core/_base/updater/static/updater.scss`.
6. **ClientScript plugin:** `couchpotato/core/_base/clientscript.py` (autoloaded via
   the loader; deleting the file de-registers it — confirm no other reference).
7. **Dead view machinery in `couchpotato/__init__.py`:** remove the `views` dict
   and `addView`, and the now-unreferenced view functions `index()`, `apiDocs()`,
   `databaseManage()`, `manifest()` (and the `static/fonts` `os.walk` inside
   `manifest()`). Keep the `/old/*` redirect handler, the `/login*`, `/logout`,
   and all API routes. Be surgical — only remove code that is provably unreachable
   after this deletion (grep to confirm each symbol has no remaining reader).

## Acceptance criteria

- `grep -rn "clientscript\|combined.min\|combined.vendor\|combined.base\|combined.plugins\|mootools\|Uniform\|static/style\|static/fonts" couchpotato/` returns only matches in docs/specs (no runtime code/templates).
- The app imports and boots with no error: starting it does NOT log a ClientScript
  plugin-load failure, and `GET /`, `GET /login/`, `GET /wizard`, `GET /settings/`
  all return 200 (or the expected redirect).
- `ruff check .` clean.
- Full unit suite passes: `.venv/bin/python -m pytest tests/unit/ -q`.
- Existing E2E specs still pass (or, if they can't run headless here, they contain
  no reference to any deleted asset — grep `tests/e2e/` to confirm).
- No dangling references to deleted files anywhere in `couchpotato/` runtime code.

## Tests

- Update/verify `tests/unit/test_old_ui_redirect.py` still passes (the `/old`
  redirect handler is retained).
- If `couchpotato/integration_test.py` asserts on `static/style`/`static/scripts`
  returning 200, update those assertions to accept 404 (the dir is gone) or remove
  the now-obsolete assertion — but only if it references deleted paths.
- Add a small regression test asserting the app starts and the ClientScript event
  (`clientscript.get_styles`) is no longer registered / login renders without it
  (can extend `tests/unit/test_login_page.py` or add a boot smoke test).
- Do NOT weaken any existing test to make deletion pass.

## Files

- Deletions per the list above.
- `couchpotato/__init__.py` (remove dead view machinery).
- `specs/UI-MIGRATION.md` — mark the legacy layer retired / update status.
- Test updates as needed (integration_test.py, a boot smoke test).
