# UI-PORT-02 — Port the login page to the Tailwind design system

## Problem

`couchpotato/templates/login.html` is the last page still rendered by the legacy
stack. It is served at `GET /login/` and `/login`
(`couchpotato/__init__.py:341-348`) and pulls its CSS/JS via
`fireEvent('clientscript.get_styles' / 'clientscript.get_scripts')`
(`login.html:11-14`), which resolves through
`couchpotato/core/_base/clientscript.py` — hard-coding `style/combined.min.css`
and the `combined.*.min.js` bundles. This is the one live dependency blocking
retirement of the legacy asset layer (Phase 1). Until login is decoupled,
deleting `static/style/**` leaves the login page unstyled and logs a ClientScript
plugin-load error on every startup.

## Fix

Rewrite `couchpotato/templates/login.html` as a **self-contained** page that
matches the modern design system, with **no** `fireEvent('clientscript.*')`
calls and no dependency on `static/style/**`, `static/fonts/**`, MooTools, or
Uniform.

Mirror the head/token setup from the modern `couchpotato/ui/templates/base.html`:

- Tailwind CDN: `{{ web_base }}static/scripts/vendor/new-ui/tailwindcss-cdn.js`
- The same `tailwind.config` (`darkMode: 'class'`, Inter font, `cp.*` colors).
- The same `:root` / `:root.light` CSS variables (`--cp-bg`, `--cp-card`,
  `--cp-surface`, `--cp-border`, `--cp-text`, `--cp-muted`) and the Inter font
  `<link>`. Default to dark (`<html lang="en" class="dark">`) to match base.html.
- Keep PWA/favicon meta consistent with base.html
  (`{{ web_base }}static/icons/...`, `manifest.json`, `theme-color #35c5f4`).
- Do NOT pull htmx/Alpine unless needed — the login form is a plain HTML POST and
  should work without JS.

Preserve exact form semantics (behavioural parity — the route is unchanged):

- `<form method="post" action="">` posting to the same URL.
- Fields: `username` (text), `password` (password), `remember_me`
  (checkbox, value `1`, checked by default). Keep the same `name` attributes so
  `login_post` (`__init__.py:350-373`) keeps working unchanged.
- Keep `autofocus` on username; keep the autocomplete/autocorrect/spellcheck
  attributes.

Accessibility (design-system CONFORMANCE.md):

- Proper `<label>`s associated with inputs (`for`/`id`), a visible focus ring
  matching the app (`focus:ring-2 focus:ring-cp-accent`), sufficient contrast,
  a real submit `<button>`.
- Centered card on `bg-cp-bg`, using `bg-cp-card`/`border-cp-border`, rounded,
  matching the modern card treatment. CouchPotato wordmark as plain text (no
  Lobster).
- Responsive / mobile-friendly (single column, tap targets ≥ 40px).

Route cleanup:

- In `couchpotato/__init__.py` `login_get` (line 347-348), the template no longer
  needs `fireEvent`. Update the `tmpl.render(...)` call to stop passing
  `fireEvent` (pass only what the new template uses, e.g. `Env`). Do not change
  `login_post` behaviour.

Do NOT delete `clientscript.py` or any `static/**` asset in this task — that is
Phase 1 (UI-CLEANUP-01). This task only decouples login so Phase 1 becomes safe.

## Acceptance criteria

- `GET /login/` returns 200 and renders the new login form.
- The rendered login HTML contains **no** reference to `combined.min.css`,
  `clientscript`, `static/style`, MooTools, or Uniform.
- The rendered HTML references the Tailwind CDN + Inter font (design-system head).
- The form still POSTs username/password/remember_me with unchanged `name`s;
  `login_post` still authenticates (existing login tests still pass).
- `ruff check .` clean; new + existing unit tests pass.

## Tests (TDD — write failing tests first)

Add `tests/unit/test_login_page.py` (or extend an existing login test) that:

1. Renders `login.html` (via the app test client `GET /login/`, or by rendering
   the Jinja template directly with the same context `login_get` passes) and
   asserts the response is 200 and the body contains the username/password
   inputs and the submit control.
2. Asserts the body does NOT contain `combined.min.css`, `clientscript`,
   `mootools`, or `Uniform` (case-insensitive).
3. Asserts the body DOES contain the Tailwind CDN path and the `cp-` design
   tokens (e.g. `--cp-bg` / `bg-cp-bg`).

Reuse existing login test scaffolding in `tests/unit/` (see `test_api_auth.py` /
`test_fastapi_web.py` for the app-client pattern) rather than inventing new
mocking.

## Files

- `couchpotato/templates/login.html` (rewrite)
- `couchpotato/__init__.py` (login_get render call only)
- `tests/unit/test_login_page.py` (new)
