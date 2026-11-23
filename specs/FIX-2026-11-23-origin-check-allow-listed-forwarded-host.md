# X-Forwarded-Host cannot vouch for an origin on the CORS allow-list

Owner decision 2026-11-23: fix it now, as its own change.

## Problem

`_cross_origin_request` (`couchpotato/__init__.py`) counts every value of
`X-Forwarded-Host` as this app's own identity. Its comment says a hostile page
cannot send that header because a `fetch` that tried "would trigger a CORS
preflight it cannot satisfy". That holds only while the `cors_origins` setting is
empty.

Measured against master with `cors_origins='http://dash.invalid'`:

- a preflight with `Access-Control-Request-Headers: content-type,x-forwarded-host`
  from `Origin: http://dash.invalid` returns 200 with the origin allowed and
  credentials allowed (`allow_headers=["*"]`);
- a request carrying `Origin: http://dash.invalid`, `Host: cp.invalid:5050` and
  `X-Forwarded-Host: dash.invalid` is judged same-origin by both
  `_cross_origin_post` and `_cross_origin_guarded_route`.

So an origin the operator listed for CORS can reach the logout POST and every
route in `ORIGIN_CHECKED_API_ROUTES`, including `renamer.operator_replace`, which
permanently deletes a media file.

## Decision

When the stated origin (the `Origin` header, or the origin derived from `Referer`)
is on the configured CORS allow-list, `X-Forwarded-Host` does not count as this
app's identity: only the `Host` header does. Everything else is unchanged: an
origin not on the list is judged exactly as before (`Host` and `X-Forwarded-Host`
both count), absent evidence behaves as before for both callers, and the
comma-split of both headers is unchanged.

**Consequence, documented and not fixed.** An operator who lists this app's OWN
public origin in `cors_origins` AND runs behind a reverse proxy that rewrites
`Host` to the upstream address while sending `X-Forwarded-Host` (for example Apache
`mod_proxy` without `ProxyPreserveHost On`, or nginx configured to add that header
without preserving `Host`) will have sign-out and the origin-checked routes
refused from that origin. Remedy: remove the entry (it is not needed for
same-origin use) or make the proxy preserve `Host`. A proxy that rewrites `Host`
and sends no `X-Forwarded-Host` (nginx's default `proxy_pass`) was refused before
this change, listed or not. With `Host` preserved, or with `cors_origins` empty
(the default), nothing changes.

## Design

- One function, `_parse_cors_origins(raw)`, turns the setting into the list of
  allowed origins (split on commas, strip surrounding spaces, drop empties and
  `*`). `create_app` uses it to build the CORS middleware and stores the very same
  list on `app.state.cors_origins`, which the origin helpers read from the
  request, so the two cannot drift. (The helpers keep their one-argument
  signatures: existing tests wrap `_cross_origin_post(request)`.)
- **Comparison rule (AC-3).** An origin is "on the list" when its
  `scheme://host[:port]` string, as sent by the browser (or built from `Referer`),
  is exactly equal to an entry. That is how Starlette's `CORSMiddleware` matches
  (`origin in self.allow_origins`), so a request the middleware would refuse is
  not treated as listed. Consequently: an entry with a trailing slash never matches
  (the middleware never matches it either); surrounding spaces are stripped (the
  middleware's own parse strips them); `*` is dropped by the shared parse and never
  counts; case, port and scheme variants of a listed origin are NOT listed, and
  are judged as before, because the middleware would not allow them to send the
  header in the first place.
- **Runtime changes (AC-6).** The list is the value captured when `create_app`
  built the middleware, not the live setting. The middleware does not change after
  creation, so reading the live setting could drop an entry from the check while
  the middleware still allows it, which is exactly the window this fix closes.
  Reading the captured list cannot leave a window in either direction.

## Acceptance criteria

1. **AC-1 (listed origin, forwarded host).** With `cors_origins` listing
   `http://dash.invalid`, a request with `Origin: http://dash.invalid`,
   `Host: cp.invalid:5050` and `X-Forwarded-Host: dash.invalid` is cross-origin for
   BOTH `_cross_origin_post` and `_cross_origin_guarded_route` (helper level), and
   through the real app (a) the logout POST is refused with the session secret not
   rotated, and (b) a route registered under the real name
   `renamer.operator_replace` answers 403 with its handler (a spy that deletes
   nothing) not called. Each integration test first asserts that the CORS
   preflight for `content-type,x-forwarded-host` from that origin is allowed (200
   with `Access-Control-Allow-Origin`), so the probe is proven hostile.
2. **AC-2 (Referer only).** The same, with the origin arriving only through
   `Referer` and no `Origin` header.
3. **AC-3 (variants).** `X-Forwarded-Host` as a comma list containing the listed
   origin's host is still cross-origin. The comparison rule above holds: a
   trailing-slash entry never matches; spaces around entries are ignored; a `*`
   entry never counts; a case, port or scheme variant of a listed origin is judged
   as before (and the CORS preflight for such a variant is not allowed, proving
   the two agree).
4. **AC-4 (unchanged).** With `cors_origins` empty, `Origin: https://media.invalid`,
   `Host: 127.0.0.1:5050`, `X-Forwarded-Host: media.invalid` is same-origin for
   both helpers. With `http://dash.invalid` listed, an origin NOT on the list is
   judged as before. With neither `Origin` nor `Referer`, `_cross_origin_post` is
   False and `_cross_origin_guarded_route` is True. The existing tests pass
   unmodified.
5. **AC-5 (own origin listed, Host preserved).** A listed origin whose host equals
   the real `Host` header is same-origin for both helpers, and the logout POST
   still signs out.
6. **AC-6 (one allow-list).** `create_app` derives the CORS middleware's origins
   and the origin helpers' allow-list from one function and one captured value
   (see Design). A test builds the app with one setting value, changes the live
   setting afterwards, and shows the check still follows the captured list.
7. **AC-7 (comment).** The comment in `_cross_origin_request` is corrected to say
   what is now true; the matching sentence in `TestTheOriginCheckDoesNotBreakSignOutBehindAProxy`
   is left alone (a test docstring, and the proxy case it describes still holds).
8. **AC-8 (docs).** `docs/reference/API.md` has a "Changed" note for versions after
   v3.313.0-beta.1 (the newest tag when written; it points at the commit before
   this fix) with the behaviour, the own-origin-behind-proxy consequence and its
   remedy.

9. **AC-9 (refusal log).** When the stated origin is on the list, both refusal
   warnings (sign-out and the origin-checked routes) say that the origin is
   listed in `cors_origins`, so `X-Forwarded-Host` is not trusted for it, and name
   both remedies (remove the entry, or have the proxy preserve `Host`). For an
   unlisted origin the original advice is unchanged and the listed-origin text
   does not appear. No header value is logged beyond the three already logged.
10. **AC-10 (recorded limit).** A listed origin's credentialled GET of a UI page is
    answered with the allow-origin header and the page holds the API key. This
    is pinned by a test named as a recorded limit, backed by an open entry in
    `docs/technical-debt.md`, and stated in the API.md note: this change stops
    such a page reaching sign-out and the origin-checked routes, not reading the
    key and calling the other routes.

## Also

A reviewer noted that `tests/integration/test_settings_jsonp_refused.py`
registers `test.jsonp_other` into the global `api` registry and never removes it.
Measured: `group_settings` (under `live_world`) already restores `api`,
`api_locks` and `api_docs` on teardown, so nothing leaks. A module-scoped
teardown assertion now makes that a checked fact; its guard was proven by
stopping the helper restoring `api`.

## Not in scope

- Giving `X-Forwarded-Host` a trusted-proxy list.
- Changing `allow_headers=["*"]`, or limiting credentialled CORS to `/api/`
  routes (recorded as debt, AC-10).

## Affected files

- `couchpotato/__init__.py`
- `tests/unit/test_origin_check_allow_listed_forwarded_host.py`
- `tests/integration/test_origin_check_allow_listed_forwarded_host.py`
- `tests/integration/test_settings_jsonp_refused.py`
- `docs/reference/API.md`, `docs/technical-debt.md`

## Verification

Red, green, refactor. Mutations: (a) remove the rule; (b) match the list by host
name only, ignoring the port; (c) ignore the Referer-derived origin; (d) treat a
listed origin as cross-origin even when its host equals `Host`. Each must fail a
named test. Unit and integration suites and `ruff check .`.
