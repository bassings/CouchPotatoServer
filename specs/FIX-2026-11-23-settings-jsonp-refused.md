# The settings read is no longer available as JSONP

Owner decision 2026-11-23: close it for the settings read now; other routes are
out of scope.

## Problem

`GET /api/<key>/settings?callback_func=steal`, sent with a foreign `Origin`,
answered 200 `text/javascript` with the body `steal({...})`. The body holds every
setting the read returns, including indexer API keys (`newznab.api_key`,
`torrentpotato.pass_key`) and every host. A page on any origin that knows the
API key can therefore read the settings from the visitor's browser with a
`<script>` tag, even when the server is reachable only from that browser.
Nothing in the app requests `settings` as JSONP.

## Decision

The API dispatch refuses a request to a route named in one module-level set when
it carries a `callback_func`, before the handler runs. The set holds `settings`
only. Other routes keep JSONP, recorded as debt.

## Acceptance criteria

1. **AC-1 (refusal).** A request to the `settings` route carrying a non-empty
   `callback_func` is refused with HTTP 400 and the JSON body
   `{'success': False, 'error': 'JSONP is not available for this route'}`, with a
   JSON content type, whatever the Origin (none, same-origin, foreign) and
   whether `callback_func` arrives in the query string, a form body or a JSON
   body. Neither the body nor the headers contain a setting value (asserted
   against a sentinel placeholder stored in a fixture setting), and the content
   type is not `text/javascript`.
2. **AC-2 (before dispatch).** `Settings.view` is not called for a refused
   request (a counter around the real registered handler, which still calls the
   real one).
3. **AC-3 (unchanged read).** `GET /api/<key>/settings` without `callback_func`
   returns the settings JSON as before, including with the cache-buster `t`.
4. **AC-4 (other routes).** JSONP on other routes is unchanged: the existing
   `test.jsonp?callback_func=myFunc` test passes unmodified, and an invalid
   callback name is still refused with `Invalid callback`.
5. **AC-5 (shape).** The refused routes are one module-level constant,
   `JSONP_REFUSED_API_ROUTES`, beside the other route guards in
   `couchpotato/__init__.py`, with a comment giving the reason. The check is one
   branch in the dispatch that reads it, before the handler is dispatched. One
   WARNING is logged per refusal, naming the route only (no parameter value, no
   Origin, no key).
6. **AC-6 (docs).** `docs/reference/API.md` has a "Changed" note for versions
   after v3.312.0 (the newest stable tag when written). `docs/technical-debt.md`
   records that JSONP remains on every other GET route, with the condition for
   revisiting.

## Not in scope

- JSONP on any other route (recorded as debt).
- Removing JSONP altogether, or requiring an Origin check on GET reads.

## Affected files

- `couchpotato/__init__.py`
- `tests/integration/test_settings_jsonp_refused.py`
- `docs/reference/API.md`, `docs/technical-debt.md`

## Verification

Red, green, refactor. Mutations: (a) empty the constant; (b) move the check to
after `callApiHandler`; (c) read only the query string. Each must fail a named
test. Unit and integration suites and `ruff check .`.
