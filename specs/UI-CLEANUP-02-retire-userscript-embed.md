# UI-CLEANUP-02 — Retire the legacy userscript embed + delete the last legacy chain

## Problem

UI-CLEANUP-01 kept a chain alive because `Userscript.iFrame` called
`couchpotato.index()`: `iFrame → index() → index.html → clientscript.* → the 4
compiled combined.* bundles + static/fonts`. Investigation (2026-07) confirmed
that whole embed is **already broken** (the API dispatch JSON-encodes `iFrame`'s
HTML string, so the browser never gets `text/html`; and the `getUserScript`
`static=True` route is dead — shadowed by the `api/{route:path}` catch-all). So
retiring it loses no working capability. The working resolver
`userscript.add_via_url` (`getViaUrl`) is independent and is being surfaced in the
new UI by UI-PORT-03 — so the legacy embed can now be deleted, closing Gap 1.

## Fix

1. **`couchpotato/core/plugins/userscript/main.py`** — remove the dead/broken
   legacy surface, KEEP the working resolver:
   - Remove methods + their `addApiView` registrations: `iFrame`,
     `getUserScript`, `bookmark`, `getIncludes` (and the
     `userscript.get/(.*)/(.*)`, `userscript`, `userscript.bookmark`,
     `userscript.includes` routes).
   - Remove `from couchpotato import index` and any now-unused imports
     (`os`, `traceback`, `time`, `b64encode`/`b64decode`, `RedirectResponse`,
     etc. — only remove what's genuinely unused after the deletions; run ruff).
   - **KEEP** `getViaUrl` + `addApiView('userscript.add_via_url', self.getViaUrl)`
     and `addEvent('userscript.get_version', ...)` / `addEvent('app.test', ...)`
     UNLESS grep proves them dead. Verify no remaining code fires
     `userscript.get_includes` / `userscript.get_excludes` after `bookmark`/
     `getIncludes` are gone (if a provider still fires them and nothing listens,
     that's fine — merge events tolerate no listeners; but confirm you're not
     removing the only listener something depends on for correctness).
   - Delete the legacy static/template assets the removed methods rendered:
     `couchpotato/core/plugins/userscript/static/userscript.js`,
     `.../static/*.js_tmpl` (bookmark.js_tmpl, template.js_tmpl), and any
     `cp_popup`/icon assets only referenced by them. Verify each is unreferenced
     elsewhere before deleting.
2. **`couchpotato/__init__.py`** — remove `index()` (now zero callers — grep to
   confirm; UI-PORT-03 does NOT reintroduce a caller) and its explanatory
   comment block. Confirm no remaining `fireEvent('clientscript.*')` anywhere.
3. **Delete the legacy chain** (now fully unreferenced):
   - `couchpotato/templates/index.html`
   - `couchpotato/core/_base/clientscript.py`
   - `couchpotato/static/style/combined.min.css`
   - `couchpotato/static/scripts/combined.vendor.min.js`,
     `combined.base.min.js`, `combined.plugins.min.js`
   - `couchpotato/static/fonts/**`
   Before deleting each, grep the repo (excl. .venv/.git/node_modules) to confirm
   no live code/template/served route references it. `login.html` uses the
   Tailwind CDN + Google Fonts, NOT static/fonts — reconfirm.
4. **Tests** — `tests/unit/test_login_page.py` currently has
   `TestPreservedUserscriptChain` and `TestBootAfterLegacyAssetCleanup` asserting
   the chain EXISTS. Invert them: assert `couchpotato` no longer exposes `index`,
   `couchpotato.templates/index.html` is gone, `clientscript.py` is gone, and the
   app still boots + `/login/` still 200. Do not just delete the coverage — keep
   equivalent assertions for the new (deleted) state.

## Acceptance criteria

- `grep -rn "clientscript\|combined.min\|combined.vendor\|combined.base\|combined.plugins\|templates/index.html\|couchpotato import index\|def index(" couchpotato/` returns only docs/comments — no live code.
- App boots with NO ClientScript plugin load and NO error/traceback; `GET /`,
  `/login/`, `/settings/`, `/wizard` still 200 (or expected redirect).
- `userscript.add_via_url` still registered and callable.
- `ruff` clean; full `.venv/bin/python -m pytest tests/unit/ -q` passes.
- `scripts/check_conformance.py` clean.
- Update `specs/UI-MIGRATION.md`: mark the legacy asset layer FULLY retired /
  Gap 1 closed.

## Files

- `couchpotato/core/plugins/userscript/main.py`, `couchpotato/__init__.py`
- deletions per the list above (git rm)
- `tests/unit/test_login_page.py` (invert chain tests)
- `specs/UI-MIGRATION.md`
