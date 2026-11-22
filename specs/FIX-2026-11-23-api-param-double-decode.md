# API parameters are URL-decoded a second time

Owner decision 2026-11-23: fix this as the change after SEC-005 P4, ahead of
the outbound-proxy plan.

## Problem

Every API request goes through `callApiHandler` (`couchpotato/api.py`), which
passes its arguments to `getParams` (`couchpotato/core/helpers/request.py`).
`getParams` runs `urllib.parse.unquote` on every string value, flat and
nested. The web framework has already decoded the query string and the form
body, and a JSON body was never encoded, so this is a second decode of text
that is already the caller's value.

Measured through the real `settings.save` route (placeholder values):

- `placeholder-pa%41ss` is stored as `placeholder-paAss`.
- `placeholder-p%25w` is stored as `placeholder-p%w`.
- A `%FF`-style escape that is not UTF-8 is replaced by U+FFFD, so what was
  typed cannot be recovered from what is stored.
- The save replies `success: true`.

It is not specific to settings. Any API argument that contains `%` followed by
two hex digits is changed before its handler sees it: an API key, a downloader
or proxy password, `core.password`, a folder path, a search term, a URL handed
to `userscript.add_via_url`. A Jackett address in percent-encoded form cannot
be saved as typed, which is why SEC-005 documents a double-encoding workaround.

The behaviour is inherited from the original CouchPotato, where the same
helper ran after Tornado had already decoded the arguments.

## Decision

Remove the second decode in the one place it happens. `getParams` no longer
calls `unquote`. Nothing else about `getParams` changes: nested bracket keys
are still expanded, the text `true` / `false` in a flat value is still turned
into a boolean, non-string values still pass through.

A per-route fix (settings only) was ruled out: it would leave the same fault on
every other route and add a branch naming routes to shared plumbing.

## Acceptance criteria

1. **AC-1 (the fault).** A flat string value, a nested bracket-key value and a
   value inside a JSON body each reach the handler exactly as the framework
   delivered them. Cases: `a%41b`, `p%25w`, `%2C`, `%2c`, `%252C`, `%FF`,
   `100%`, `a+b`, `a&b=c`, `jack%C3%A9tt`, and a non-ASCII value (`jackétt`).
   Proven at `getParams` and through the real HTTP route for query string,
   form body and JSON body.
2. **AC-2 (settings round trip).** `settings.save` of a value containing
   `%41`, `%25` and `%FF` text stores exactly the characters sent, by form, by
   JSON and by query string, for a plain option and for a `password` option.
3. **AC-3 (one decode remains).** A value the client percent-encodes once in a
   query string or form body, as every page of the UI does
   (`encodeURIComponent`), still reaches the handler decoded once:
   `directory.list?path=%2Ftmp%2Fa%20b` is handled as `/tmp/a b`.
   Example: a real folder named `a%41b` (or `p%25w`) holding a child folder is
   listed by `directory.list` when its name is sent encoded once (`a%2541b`);
   before the fix the route replied `Unable to list directory`, because the
   name was decoded to `aAb`.
4. **AC-4 (unchanged behaviour).** Bracket-key nesting, natural key ordering,
   `dictToList`, the flat `true` / `false` coercion and the pass-through of
   non-string values behave as before; the existing tests for them pass
   unmodified.
5. **AC-5 (the comma check).** The combined-group save still refuses a literal
   comma by every transport. An encoded comma (`%2C`) sent by form or by
   bracket key is now three literal characters, as it already was by JSON: it
   is stored as sent and the number of stored positions equals the number of
   rows. The two SEC-004 tests that pin "refused after decoding" are rewritten
   to pin this, and the SEC-004 spec gets a dated note; no SEC-004 criterion
   text is changed.
6. **AC-6 (Jackett address).** A Jackett address typed in percent-encoded form
   (`http://h.invalid:9117/jack%C3%A9tt`) is stored as typed through
   `settings.save`, and a key saved after it is bound to it.
7. **AC-7 (login).** A UI password containing `%41`-style text saved through
   `settings.save` is accepted by the login form when the same text is typed.
   This turns the "reasoned, not driven" note in the debt entry into a driven
   test.
8. **AC-8 (docs).** `docs/technical-debt.md`: the entry "Settings values are
   URL-decoded a second time on save" is closed with what remains (values
   already stored in changed form are not repaired; re-enter them).
   `docs/reference/API.md`: the Jackett known-limit text says the
   percent-encoded spelling can now be typed directly, names the version
   boundary, and drops the double-encoding workaround for versions with this
   fix. A short "Changed" note states that a client which percent-encoded its
   values twice to work around the old behaviour must now encode once.
9. **AC-9 (scope).** Product CODE changes are confined to
   `couchpotato/core/helpers/request.py`. No route gains a decode of its own.
   The now-unused `unquote` import is removed. Two comments in
   `couchpotato/__init__.py` (on `STRICT_JSON_API_ROUTES` and in the
   `_strict_json_refusal` docstring) are corrected because they described the
   removed decode; no code line there changes.

## Not in scope

- Repairing values that were stored in changed form by earlier versions. They
  cannot be told apart from values the user meant.
- The `true` / `false` coercion of flat values (a password of exactly `true`
  is still turned into a boolean). Recorded as debt if not already.
- The outbound proxy gap (SEC-005 gap (j)).

## Risks

- A third-party client that encodes twice to work around the old behaviour
  will now have its values stored with one layer of encoding left. None is
  known; the UI's own callers all encode once (four `encodeURIComponent`
  sites, all query strings).
- A user who used the documented double-encoding workaround for a Jackett
  address has the correct value stored already; saving the field again after
  this fix keeps it, where before it broke it.

## Affected files

- `couchpotato/core/helpers/request.py`
- `tests/unit/` (new `getParams` tests), `tests/integration/` (route tests;
  `test_settings_group_save_route.py` rewrites)
- `docs/technical-debt.md`, `docs/reference/API.md`,
  `specs/SEC-004-combined-settings-save.md` (dated note only)

## Verification

Red, green, refactor. Mutation: restore `unquote` on the flat branch only, then
on the nested branch only; each must fail a named test. `make verify`, two
independent reviews (one executing, one security) before the push.
