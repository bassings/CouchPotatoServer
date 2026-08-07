# PR2B: the browser session stops being the API key

> Planning input for the multi-lens harness (`~/.claude/AGENT-HARNESS.md`).
> Acceptance criteria below are the contract the review cycle verifies against.
> A review finding with no AC behind it is a **spec bug**: record it in
> "Spec gaps found at review" so the planning lens improves.
>
> **This file is T4 of `specs/REMEDIATION-2026-08.md`** (PR 2b), split out
> because plan-cycle needs a spec scoped to one PR rather than the whole
> remediation programme. The parent plan's M15 rule binds: no implementation
> before the lenses write the `AC-<LENS>-<n>` criteria below.

**Status:** draft — acceptance criteria NOT YET WRITTEN
**Lenses run:** none yet · **Skipped:** none yet

## Problem

Logging into the web UI hands the browser the instance's **API key**, verbatim,
as a cookie. Measured on the current tree:

```python
# couchpotato/__init__.py:488
api_key_val = Env.setting('api_key')
response.set_cookie('user', api_key_val, max_age=max_age, httponly=True, path='/')

# couchpotato/__init__.py:196-201  (get_current_user)
user = request.cookies.get('user')
api_key = Env.setting('api_key')
if api_key and hmac.compare_digest(...user..., ...api_key...):
    return user
```

The cookie is not a session token that happens to be long. It **is** the
credential that `/api/{route:path}` authenticates with, so its value is
equivalent to full API access: add, delete, rename, `movie.delete?delete_from=all`.

What follows from that, each verifiable against the code above:

1. **Logout does not end anything.** `logout` calls
   `response.delete_cookie('user', path='/')` (`:497`) — it asks the browser to
   forget the value. Anyone who already has the value keeps it. There is no
   server-side state to revoke, so a session cannot be ended, only forgotten by
   the one party that was not the threat.
2. **Revocation costs every integration.** The only way to invalidate a leaked
   cookie is to rotate `api_key`, which simultaneously breaks the userscript,
   every script, and any downloader or automation holding that key. So in
   practice it is never rotated, and a leaked cookie is valid forever.
3. **The cookie carries no `secure` and no `samesite`.** Grepped across
   `couchpotato/**.py`: zero occurrences of either. Default `SameSite` behaviour
   is browser-dependent, and the deployment is plain HTTP
   (`http://homemedia.maeewing.com:5050`), so the credential also crosses the
   LAN in clear text on every request. The CodeQL suppression already on `:488`
   (`codeql[py/clear-text-storage-sensitive-data]`) marks the known part of this.
4. **`max_age=None` without "remember me"** makes it a browser-session cookie,
   which sounds like an expiry and is not one: it binds to the browser process,
   not to elapsed time, and the value stays valid server-side regardless.
5. **A stolen cookie is indistinguishable from the owner** — there is nothing
   recorded to expire, scope, count or audit.

**Who this costs.** A single-user home server on a LAN, reachable over plain
HTTP, whose owner has probably never rotated the key because doing so breaks
their own automation. The blast radius is the media library: irreplaceable per
this project's own risk ranking.

## Also carried into this PR

From the deferred table in `specs/REMEDIATION-2026-08.md`:

- **L1** — an unauthenticated caller can evict the 5 MB log ring by repeatedly
  tripping the `auth_required` lockout ERROR path. Same auth surface.
- **L8** — `auth_required` is parsed by two modules with no shared constant.
- **M2** (deferred from PR 2's review) — the startup `auth_required` migration
  is executed by **no test**; its only guard is a source-order string search.

## Constraints that are already settled

These come from the parent plan's PR 2 planning cycle and are **not** open
questions for the lenses to re-litigate:

- **No new table, no DDL.** `SQLiteAdapter.open()` runs no DDL, so anything
  added to `schema.sql` reaches fresh installs only and the first login on an
  existing install raises `no such table`. This was the accepted
  `lens-simplicity` veto: an HMAC-signed cookie with a rotating secret held in
  the **existing property store**, not a `sessions` table.
- **The property store exists and needs no schema change.**
  `Env.prop(identifier[, value])` → `Settings.getProperty` /
  `Settings.setProperty` (`couchpotato/core/settings.py:640,656`).
- **`db.get('session', ...)` must never be the lookup.** `_query_index`'s
  generic `else` branch discards the key and returns an arbitrary document —
  executed during PR 2 planning: `db.get('session', 'TOKEN_B')` returned a
  **media** document. This repo has shipped that exact defect twice
  (`release_download`, `media`). A signed cookie avoids the lookup entirely,
  which is a large part of why it was chosen.
- **`/api/{route:path}` keeps authenticating by `api_key`.** It is in
  `PUBLIC_ROUTES` deliberately (`tests/unit/test_route_auth_inventory.py`);
  putting a session dependency on it would break every script and the
  userscript. The API key remains the API's credential. This PR stops it being
  the *browser's* credential too.

## Not in scope

- **Rotating or changing the `api_key` itself**, or how the API authenticates.
- **Multi-user accounts, roles, or a user table.** One operator, one password.
- **HTTPS/TLS termination.** Real, and an infrastructure change, not this PR.
  It is the reason `secure` cannot simply be hardcoded True — doing so on a
  plain-HTTP deployment makes the cookie undeliverable and locks the owner out
  of their own server. Whatever the lenses decide here must not be able to
  produce a lockout; the parent plan already has one recorded near-miss of
  exactly that shape.
- **CSP** — deferred to PR 5 with the Tailwind CDN removal.

## The failure this must not repeat

PR 2 shipped a change that made a one-click, unrecoverable lockout possible,
and an earlier attempt at this same auth surface failed **open** for a week.
Any design here is judged first on: what happens to the owner of a running
install when it is wrong? An upgrade must not invalidate a working login
without a route back in that does not require reading the source.

---

## Acceptance criteria

Written by `/plan-cycle` on 2026-08-07. Lenses run: security, qa, simplicity,
product, design, accessibility, data, architecture, operability (nine of nine;
none skipped, because the change touches auth, persisted credentials, the login
template and the startup path). These criteria are the contract the review cycle
verifies against.

### Decisions settled by the planning cycle

Seven of the nine lenses independently raised the same three undecided questions.
They are decided here so the implementer does not decide them silently.

- **D1 — Logout rotates the shared signing secret, and therefore ends every
  session on every device.** A stateless signed cookie holds no per-session
  server state, so secret rotation is the only revocation the settled "no new
  table" constraint permits. That is correct for one operator, and the control's
  visible label and copy must say so rather than implying "this browser only".
- **D2 — The signing secret is created once at startup, before the first request
  is served, and never on a request path.** `Settings.setProperty` is an
  unguarded get-then-act with no uniqueness constraint (measured: four concurrent
  creates produced two rows and lost two writes), and a per-request property read
  takes the adapter's process-wide `RLock`.
- **D3 — Session lifetimes are 24 hours without "remember me" and 30 days with
  it**, both enforced server-side from an absolute expiry inside the signed
  payload. 24 hours clears WCAG 2.2.1's 20-hour exception, so no warn-and-extend
  mechanism is required, and 30 days keeps `login.html`'s existing copy true.
- **D4 — `secure` is set if and only if this server terminates TLS itself**
  (both `ssl_cert` and `ssl_key` configured). Never from `X-Forwarded-Proto`,
  the `Host` header or the request URL scheme: an attacker-settable header that
  turns on `Secure` on a plain-HTTP deployment is the recorded lockout shape.
- **D5 — Legacy `api_key`-valued cookies are rejected from the first request
  after upgrade.** There is no compatibility acceptance window. The route back in
  is the login page with the password already stored, which
  `Core.guardAuthRequired` guarantees exists whenever `auth_required` is on.
- **D6 — Changing the password rotates the secret**, so a password change ends
  every existing session.
- **D7 — The `api_key` remains embedded in every rendered page** as
  `window.CP.apiBase`. That is out of scope, but it is enumerated by an allowlist
  test and stated in one sentence in the PR body, because it means the separation
  this PR builds is one-way.
- **D8 — A sign-out control in the app shell is in scope.** There is none today
  (`grep` for logout across `couchpotato/ui/` and `couchpotato/templates/`
  returns zero hits), so revocation would otherwise be reachable only by typing
  a URL.

### Product

- AC-PROD-2: An operator signed in to the new UI can sign out without typing a URL: an authenticated page exposes a control that reaches the logout route, present on every authenticated page (persistent nav and mobile menu). [merged with AC-DESIGN-1, AC-A11Y-7]
- AC-PROD-3: Ending sessions costs no integration: after the sign-out of AC-SEC-36 the stored `api_key` is byte-identical to its prior value, and an `/api/` request authenticated with that key still succeeds.
- AC-PROD-5: The lifetime the login page promises is the lifetime delivered: the rendered "Remember me" copy states the duration D3 fixes, derived from the same constant the session code uses, asserted for both the ticked and unticked case. [merged with AC-DESIGN-6]
- AC-PROD-7: Scope boundary: the change adds no session-management surface beyond starting and ending a session. No page, route, settings field or template lists, names, counts or individually revokes sessions or devices. [merged with AC-SIMP-8]

### Security

- AC-SEC-30: The cookie is not the `api_key` and the old branch is gone rather than kept as a fallback: after login the cookie value does not contain `Env.setting('api_key')` as a substring (asserted against a realistic 32-character key), and `get_current_user` refuses a cookie whose value equals the `api_key`. Proven load-bearing by reinstating the `hmac.compare_digest(user, api_key)` branch at `couchpotato/__init__.py:199-202` and watching a named test go red. [merged with AC-QA-1, AC-QA-2, AC-QA-3, AC-SIMP-9]
- AC-SEC-31: Forgery is refused in every shape, each a separate named test rather than a loop over one assertion: no signature; empty signature; truncated signature; a signature produced with a different secret; a payload mutated while keeping the original signature; a cookie whose payload is valid but whose signature is the payload itself. [merged with AC-QA-9]
- AC-SEC-32: The signing secret is generated with the `secrets` module, carries at least 32 bytes of entropy, and two freshly created installs produce different secrets. It is never derived from `api_key`, `uuid4().hex`, `md5()`, time, the password hash, or any hardcoded literal. A test asserts the length and uniqueness properties and, via `inspect.getsource` (the idiom at `tests/unit/test_http_client.py:244`), that the generator is `secrets`.
- AC-SEC-33: Fail closed when the secret is unavailable: if the property read or write raises, login issues no cookie and every session validation returns not-authenticated; the code never signs or verifies with an empty string, `None` or a constant fallback; one ERROR is logged naming the `config.ini` recovery path. Proven by monkeypatching `Settings.getProperty` to raise and asserting no `Set-Cookie` and refusal of a previously valid cookie. [merged with AC-QA-20, AC-ARCH-6, AC-OPS-42, AC-OPS-43, AC-DATA-6]
- AC-SEC-34: The signature comparison is constant-time (`hmac.compare_digest` or equivalent), asserted at the verification function's source, and a plain `==` in that position fails the test. Both the signature check and any token-identifier check are covered.
- AC-SEC-35: Expiry is enforced by the server, not the browser: the signed payload carries an absolute expiry checked on every request, so a cookie whose embedded expiry has passed is refused even when the client replays it with `Max-Age` and `Expires` stripped. Both D3 lifetimes have a boundary test (just inside accepted, just outside refused), driven by an injected clock, never by `sleep` and never by patching `time.time` globally. [merged with AC-QA-7, AC-QA-8, AC-A11Y-11]
- AC-SEC-36: Logout revokes rather than forgets: a cookie captured before the logout route is replayed on a fresh client afterwards and is refused. A test asserting only the `Set-Cookie` deletion header does not satisfy this, because that is the behaviour the spec calls the defect. The test goes red if the D1 rotation is removed. [merged with AC-PROD-1, AC-QA-5, AC-DATA-7, AC-OPS-53]
- AC-SEC-37: Revocation cannot be triggered by an unauthenticated caller: an unauthenticated request to the logout route leaves a valid session held by a second client still valid. The logout route is a public unauthenticated GET today (`tests/unit/test_route_auth_inventory.py:41-42`), so under D1 any cross-site `<img src="/logout/">` would otherwise terminate every session on every device, repeatedly. If this is satisfied by making logout an authenticated POST, the same test asserts a client with a broken or expired cookie can still reach the login page.
- AC-SEC-38: Changing the password invalidates every existing session (D6): a cookie issued before a password change is replayed afterwards and refused, driven through the real settings save path (`setting.save.core.password`), not by writing the settings dict directly. The password field's description in `couchpotato/core/_base/_core.py` states the consequence, and a test asserts the description matches the implemented behaviour. [merged with AC-DESIGN-10]
- AC-SEC-39: Cookie attributes are explicit and asserted on the raw `Set-Cookie` header: `HttpOnly` present; `SameSite=Lax` written explicitly; `Path` equal to the app's `web_base`; `Secure` present if and only if D4 holds, tested in both directions on a TLS-configured and a plain-HTTP app. The plain-HTTP case drives the full flow (POST /login, follow the 302, land on `/` with 200 within a bounded hop count) so a cookie the browser would drop shows up as a login loop. Attributes are produced by one function used by both the set and the delete path, so a deletion cannot mismatch. [merged with AC-QA-11, AC-QA-12, AC-ARCH-7, AC-ARCH-8, AC-OPS-52]
- AC-SEC-40: The signing secret is not disclosed to an `api_key` holder: `GET /api/<key>/database.list_documents` does not return the secret's value, filtered or unfiltered, and `database.document.update` / `database.document.delete` refuse to write or remove that document. Measured today: `db.all('id')` returns the property row verbatim and `couchpotato/core/database.py:listDocuments` iterates exactly that, so without this the `api_key` becomes a permanent session-forging key that survives every `api_key` rotation.
- AC-SEC-41: Nothing secret reaches the log: with a real `RotatingFileHandler` attached, drive login, an authenticated page load, a failed login and logout, then grep the file on disk (not `caplog`) for the session secret, every issued cookie value, every signature and the `api_key`: all absent. `PrivacyFilter`'s name lists (`logger.py:28-60`) contain no session-token name today, so the new entry is proven load-bearing by removing it and watching this fail. [merged with AC-QA-28]
- AC-SEC-42: Online password guessing is rate limited on the auth routes regardless of request headers. Measured on this tip with `rate_limit_max=5`: 12 consecutive `POST /login/` with `Accept: text/html` all returned 302 and none returned 429, while `Accept: application/json` was limited from the sixth, because the exemption at `couchpotato/core/rate_limit.py:52-55` keys on the header every browser sends. A test asserts a 429 for `Accept: text/html` on `POST /login`, and restoring the exemption proves it load-bearing.
- AC-SEC-44: The upgrade neither fails open nor silently locks the owner out (D5): on an existing install opened with `SQLiteAdapter.open()` (never `create()`), with `auth_required=1` and a stored password, no DDL runs, no `schema.sql` change is required, every pre-existing `user` cookie stops working with a 302 to `/login/` (never a 500), logging in with the already-configured password immediately yields a working session with no `config.ini` edit and no restart between those steps, and exactly one log line states that existing sessions were invalidated and names the recovery path. [merged with AC-PROD-4, AC-QA-14, AC-DATA-9, AC-OPS-48]
- AC-SEC-46: Minimisation and retention are stated and enforced: the change persists exactly one new document (the property row holding the secret) and writes no per-login record of IP address, user agent, hostname or login timestamp to the database, nor embeds any in the cookie payload. After logins from several distinct client addresses, and after 100 login and logout cycles, `db.all('id')` contains one new property document, no new `_t` value, and an unchanged total row count. At most two secrets are retained at any time. After a login, `grep -r <secret>` across `data_dir` matches only the SQLite database file. [merged with AC-OPS-51]
- AC-SEC-47: The residual `api_key` exposure is enumerated, not implied away (D7): every remaining place the `api_key` reaches the browser (`couchpotato/ui/__init__.py:65-69` into `base.html:193`, and `/getkey/` at `couchpotato/__init__.py:410-439`) is listed in an allowlist with a stated reason in the shape `PUBLIC_ROUTES` already uses, a test fails when a new one appears, the stale "slated for deletion" comment at `tests/unit/test_route_auth_inventory.py:46-49` is corrected, and the PR body states the residual exposure in one sentence.

### Data

- AC-DATA-1: The signing secret round-trips through the property store byte-identically: generated via the production code path, read back with `Env.prop` / `Settings.getProperty`, asserted equal. Raw bytes are not acceptable; the stored form is text-safe (hex or base64) and the test asserts the decoded secret's length in bytes. Measured: `os.urandom(32)` through the property store came back as a 31-character string that did not equal the input.

  **Orchestrator re-measurement (2026-08-07), which strengthens this:** the
  corruption is **not a fixed-length truncation**. `setProperty` calls
  `toUnicode(value)`, which decodes with replacement, so how many characters
  survive depends on which random bytes happen to form valid UTF-8. The lens
  measured 31 characters; re-running it measured **29**:

      $ PYTHONPATH=.:libs .venv/bin/python -c "..."
      input bytes : 32
      output      : str len 29
      equal input : False
      hex len     : 64 round-trips: True

  So a test asserting a specific corrupted length would be **flaky**, and a
  secret stored raw would be silently different on every install and
  irrecoverable after the fact. Hex round-trips exactly. This makes the
  text-safe encoding a correctness requirement, not a tidiness one.
- AC-DATA-2: After at least four concurrent first-time logins against a database with no secret, exactly one property document exists for the secret identifier (asserted by counting rows via `_query_index`, not via `get()`), and every cookie issued by those logins is accepted on a subsequent protected request. [merged with AC-QA-17, AC-QA-18]
- AC-DATA-3: A secret write that loses the compare-and-swap race retries against the current row and never inserts a second property document: forcing a stale `_rev` leaves the row count at one and the value read back is the last successful write. Measured today: the `except Exception` in `setProperty` turns a `ConflictError` into a duplicate insert, after which `get()` returned the older value.
- AC-DATA-4: The secret lookup is proven key-correct with a two-row fixture: with the secret and at least one other property document present, the lookup returns the secret and never the other, and an absent identifier returns nothing rather than an arbitrary document. Single-row fixtures do not satisfy this.
- AC-DATA-5: No code path used to issue or verify a session cookie calls `db.get` or `db.query` with an index name `_query_index` does not handle explicitly. A spy over a full login, authenticated request and logout cycle fails if any unhandled index name is used, which would fall through to the generic `else` branch that discards the key.
- AC-DATA-11: The startup `auth_required` migration is executed by a test rather than guarded only by the source-order string search at `tests/unit/test_auth_required_gate.py:400`, proving three things: booting twice leaves the same value; an explicit stored `0` or `1` is never overwritten; every other option in `config.ini`, including `api_key`, `password` and unknown sections, is present and unchanged afterwards. [merged with AC-QA-25]
- AC-DATA-12: A migration or secret write that fails leaves the previous `config.ini` intact: driving the failure (read-only directory or a save that raises) leaves the file byte-identical, non-empty, and still containing the `api_key` and `password`. Neither-copy states are a fail.
- AC-DATA-13: The restore consequence is documented: restoring a database snapshot taken before a secret rotation re-validates the cookies that rotation revoked, and restoring a snapshot taken before this change (no secret row) yields a working login rather than a permanent denial. The first is stated in the operator docs alongside the deploy procedure; the second is executed.

### Architecture

- AC-ARCH-2: The HMAC computation, the cookie name literal and the session-secret property key literal each appear in exactly one non-test source file, asserted by a grep-based unit test.
- AC-ARCH-3: The session secret is written by exactly one function. Startup bootstrap, logout and password change all call it; there is no second write call site anywhere in the tree, asserted by grep plus a spy driving all three triggers.
- AC-ARCH-4: Session verification performs zero database reads after the first per process: ten consecutive authenticated requests cause no additional `db.get('property', ...)` calls (asserted with a counting spy, which is the enforced assertion), and each verification completes in under 1 ms. Baselines measured during planning: current `get_current_user` 0.47 us/call, hmac sign plus compare 0.97 us/call, a property `get()` 11.5 us/call taken under the adapter's process-wide `RLock`. [merged with AC-QA-22]
- AC-ARCH-5: There is no stale-cache path: after the rotation function of AC-ARCH-3 runs in the same process, the very next verification uses the new secret, and a cookie minted before rotation is rejected without a restart.
- AC-ARCH-6: The verification path never generates a secret: with the property store raising, verification fails closed, `setProperty` is not called, and the stored value is byte-identical afterwards.
- AC-ARCH-10: The startup `auth_required` resolution is a named, module-level function importable from `couchpotato.runner` and callable against a settings double without starting a server. The existing source-order guard at `tests/unit/test_auth_required_gate.py:378-419` is retained, because an executed unit test cannot pin the block's position relative to `loader.run()`. [merged with AC-SIMP-6]
- AC-ARCH-13: The change is reversible by image rollback alone: it touches neither `couchpotato/core/db/schema.sql` nor `SQLiteAdapter.open()`'s index-upgrade block, adds no new `_t` document type, and the only new persisted state is one `property` row that pre-change code ignores. [merged with AC-SIMP-13]
- AC-ARCH-14: Exactly one test helper mints an authenticated client or cookie for the Python unit tests. No test file constructs the session cookie value by hand, so a future format change touches one file rather than the current three (`test_fastapi_web.py`, `test_auth_required_gate.py`, `test_auth_required_lockout_guard.py`).

### Operability

- AC-OPS-41: The signing secret is created exactly once, at startup, before the first request (D2), emitting exactly one record at INFO or above naming the event and stating that existing browser logins are invalidated. A second boot against the same data directory emits no such record and leaves exactly one property row. Executed against a real adapter, not a stub.
- AC-OPS-44: Every class of session rejection is distinguishable from the log alone by a distinct greppable reason token, for at least: no cookie present, malformed cookie, bad signature, expired. No such record contains the cookie value or the secret. At least one record naming each reason reaches a root level of INFO within the suppression window of AC-OPS-45; a reason emitted only at DEBUG fails this.
- AC-OPS-45: Auth-failure logging is bounded so an unauthenticated caller cannot evict the log ring: 1,000 unauthenticated requests emit at most 10 records at INFO or above across the whole auth surface, covering both the existing "Require login is ON but NO PASSWORD" ERROR (`couchpotato/__init__.py:141`) and every new cookie-rejection path, and log lines present before the burst are still present afterwards. Measured baseline: 50 requests produced 50 ERROR records totalling 21,650 bytes, so roughly 11,600 requests evict the entire 500,000 x 11 byte ring configured at `couchpotato/core/logger.py:264`. Both the pre-change and post-change counts are recorded. [closes L1; merged with AC-SEC-43, AC-QA-23, AC-ARCH-11, AC-DATA-14]
- AC-OPS-46: Suppression does not cost the operator the diagnosis: the first record in each window carries the full message including the `config.ini` remedy, and the suppression is visible (a record states that further identical messages were suppressed, and how many). Both directions tested.
- AC-OPS-47: Startup states the authentication posture it will enforce, once and truthfully: exactly one record at INFO or above names the resolved state and, when enforced, that sessions are signed rather than carrying the `api_key`. For each stored `auth_required` value in {absent, `''`, `'0'`, `'1'`, `'true'`, `'garbage'`}, the state reported at startup equals what `auth_is_required()` returns on the request path, asserted by comparing the two directly in one parametrised test. [closes L8 behaviourally; see the veto record below]
- AC-OPS-49: Rollback is executed, not asserted: the previous released version's code is run against a data directory and `config.ini` written by this change; it starts, serves, and a correct login succeeds, with no record at WARNING or above about the unknown property row or any new `config.ini` key. A cookie issued by the new version, presented to the old, redirects to the login page (never a 500, never a redirect loop). The procedure and its measured result are written into this spec, naming who runs it and how long it takes. [merged with AC-QA-15, AC-DATA-10]
- AC-OPS-50: The startup `auth_required` resolution is idempotent: calling it twice against the same settings leaves the stored value unchanged and emits its INFO record only on the first call. If the write-back fails, the setting is left absent so the next boot re-derives, and one ERROR names the failure rather than the process continuing as if the migration succeeded. [closes M2, with AC-ARCH-10 and AC-DATA-11]
- AC-OPS-52: A plain-HTTP deployment cannot be locked out or put into a restart loop: against the real app with auth enforced and a password set, served over http, a correct login followed by a request to the web root returns 200 rather than a redirect back to `/login/`, and the literal `Dockerfile:134` healthcheck command exits 0. The `secure` value chosen by D4 appears in one startup record at INFO or above.

### QA

- AC-QA-4: `/api/{route:path}` is unaffected: a request carrying the `api_key` in the URL, and one carrying it in `X-Api-Key`, both return 200 with no cookie present at all; a valid session cookie with a wrong or absent `api_key` returns 401; the existing `tests/unit/test_api_auth.py` cases still pass unmodified.
- AC-QA-10: Hostile cookie values are refused with a 302 to login, no 500 and no traceback, parametrised over at least: empty string, a single separator, no separator, ten separators, `é`, a NUL byte, invalid base64 or hex, and a 100 KB value. The 100 KB case additionally asserts the request completes in under 100 ms so an accidental quadratic parse is caught.
- AC-QA-13: A wrong password sets no cookie, returns the caller to the login page within a bounded number of redirects (asserted, so an infinite `/` to `/login/` loop fails), and a correct login immediately afterwards succeeds. The existing blank-password contract in `tests/unit/test_login_blank_password.py` still holds unmodified.
- AC-QA-16: Restart persistence: a session issued before the app object is rebuilt against the same database is still accepted afterwards, proving the secret is read back from the property store rather than regenerated per process. Paired negative: rebuilding against a different database refuses the token.
- AC-QA-19: The secret is deleted out from under a running process: existing cookies are refused, no exception escapes, an ERROR names the condition, and a fresh login recovers a working session without a restart. A regeneration on a boot where a secret already existed emits a WARNING naming the trigger.
- AC-QA-21: With `auth_required` off, no session machinery runs and a garbage `user` cookie is harmless: `GET /` returns 200 and the property store is never written, asserted with a counting spy on `setProperty`, so an install that never enabled auth never grows a secret row.
- AC-QA-26: Token minting and verification are reachable through one importable seam whose clock and secret source are injectable, so AC-SEC-35, AC-SEC-31, AC-QA-16, AC-QA-19 and AC-ARCH-5 are provable without sleeping, without patching module-level `time.time` (this repo has a recorded false positive from exactly that: it also freezes `date.today()`), and without a running server.
- AC-QA-27: One E2E runs with authentication actually on and a real password, unconditionally: login form, submit, protected page, reload (session survives), logout, protected page redirects to login. It fails if the login form is absent rather than skipping. The conditional block at `tests/e2e/navigation.spec.ts:13-27` passes silently when auth is off and provides zero proof today; it is replaced or made unconditional, and the suite's skipped count stays at zero. [merged with AC-A11Y-17]
- AC-QA-29: Every new guard is proven load-bearing by breaking the thing it protects, watching the named test fail, restoring, and confirming with `git diff` or a file hash that both the break and the restore landed. The mutations are named in the PR body and include at least: delete the signature comparison; hardcode `secure=True`; delete the expiry check; delete the ERROR suppression of AC-OPS-45; set the cookie value back to the `api_key`; remove the D1 rotation from logout.
- AC-QA-30: The full suite passes three consecutive runs, and `tests/unit/test_route_auth_inventory.py` still reports every route as protected or listed in `PUBLIC_ROUTES`, with any new or newly protected route carrying an inline reason. Repeated runs are required because AC-DATA-2 introduces threads and shared `Env`/settings state, the two known flake sources in this suite.

### Design

- AC-DESIGN-1: The sign-out control renders in the desktop sidebar following the existing pattern (full-width button, inline Heroicon outline 24x24 stroke-width 1.5 with `aria-hidden`, `text-[13px]` label that collapses with the sidebar) and in the mobile menu overlay at phone width. When `auth_is_required()` is False no sign-out control renders at all. [merged with AC-PROD-2]
- AC-DESIGN-2: The sign-out control's visible label states the true scope of the action as implemented (D1: all devices). One test drives the route with two independent authenticated clients, asserts the second client's cookie is invalidated, and asserts the rendered label is the one matching that outcome, so copy and behaviour cannot drift apart. [merged with AC-QA-6, AC-DATA-8]
- AC-DESIGN-3: The login page's message region reuses the design system's error state (exclamation-triangle in `text-cp-danger` plus message) or the warning banner tokens (`bg-cp-warning/20 border-cp-warning/30`), introduces no new component and no new colour, and no message contains `token`, `HMAC`, `cookie`, `signature`, `401` or `302`.
- AC-DESIGN-5: A failed login returns the user to the login page carrying the failure message rather than to the app root: the submitted username is preserved HTML-escaped, the password field is empty with no `value` attribute, and focus lands on the password field. Today `login_post` returns `RedirectResponse(url=web_base)` on both success and failure (`couchpotato/__init__.py:481-491`), which discards the failure. [merged with AC-DESIGN-4]
- AC-DESIGN-7: A session that ends while a page is open never renders the login document inside a content fragment: an authenticated-only partial requested with `HX-Request` and no valid session responds so that the browser performs a full-page navigation to the login page (for example `HX-Redirect`), rather than a 302 whose followed 200 is swapped into the target. Measured on the current tree: `GET /partial/movies` with `HX-Request: true` returns 302 to `/login/`, and htmx 2.0.4's default `responseHandling` swaps any 2xx. Asserted by TestClient on the response, and by a Playwright test that clears the cookie, triggers a lazy-loaded partial, and asserts the browser URL became the login page with no password field inside the main content container. [merged with AC-PROD-6, AC-A11Y-9]

### Accessibility

- AC-A11Y-1: axe-core, with the tags the suite already uses (wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa) and its fail-on-any-violation assertion, reports zero violations on the rendered `/login/` page in light and in dark theme, including the state that shows a failed sign-in message.
- AC-A11Y-2: The login submit button's label meets at least 4.5:1 against its own background in both themes. It does not today: `text-cp-bg` on `bg-cp-accent` (`couchpotato/templates/login.html:141-146`) computes to 1.85:1 in light theme, while the app's other ten accent buttons use `text-black` at 10.44:1.
- AC-A11Y-3: Every focusable control on the login page shows a focus indicator meeting at least 3:1 against adjacent colours in both themes when reached by Tab (not by `focus()`). Today `login.html:73` uses `outline: 2px solid #35c5f4` with no light override (1.85:1 on the light background), `base.html:168`'s existing fix (`#0e7490`, 4.92:1) is absent from `login.html`, and the inputs' `focus:outline-none` resolves the outline to transparent at higher specificity, leaving only a 2.01:1 ring.
- AC-A11Y-4: A sign-in that does not succeed returns visible text identifying the failure, exposed to assistive technology through a `role="alert"` or `role="status"` region inside the page's `main` landmark, covering at minimum: credentials rejected, empty password submitted, and attempt rate-limited (AC-SEC-42). WCAG 3.3.1. [merged with AC-PROD-8]
- AC-A11Y-5: The login page distinguishes in text why it is being shown, with three distinguishable strings: you signed out on purpose; your session ended and you must sign in again (including the D5 upgrade case, which says the update signed you out and that your existing password still works); your last attempt was rejected. A user who has never logged in, and a user with a valid session, see no such message.
- AC-A11Y-6: The status and error text of AC-A11Y-4 and AC-A11Y-5 meets at least 4.5:1 against its surface in both themes. The obvious candidate is not compliant: `cp-danger` `#f04848` computes to 4.93:1 on the dark card but 3.67:1 on the light card.
- AC-A11Y-7: The sign-out control is reachable by Tab from the top of the page with no pointer, hover or URL typing, has an accessible name containing "Log out" or "Sign out", a focus indicator meeting 3:1 in both themes, and an activation target of at least 24x24 CSS px.
- AC-A11Y-8: After the sign-out control is activated, focus lands on a named element of the resulting login page (the `h1`, the status message, or the username field) rather than being lost to `document.body`, and the "you have been signed out" message of AC-A11Y-5 is reachable without hunting.
- AC-A11Y-10: The session-expiry notice of AC-DESIGN-7 is announced exactly once per expiry, not once per failed request. Every page embeds the `api_key` in `CP.apiBase`, so Alpine fetches keep succeeding while cookie-authed htmx requests fail, and `logs.html:135` polls on a 10-second interval, so a per-request announcement would repeat indefinitely into the assertive region at `base.html:449`. Proven by provoking at least two failed fragment requests and asserting the announcer's text changed exactly once.
- AC-A11Y-12: WCAG 2.2 AA 3.3.8 Accessible Authentication holds: the form keeps `autocomplete="username"` and `autocomplete="current-password"` (`login.html:104,119`), paste into both fields is not blocked, and this PR introduces no step requiring the user to transcribe, memorise or retype a token, code, secret or key. The signed cookie and its rotating secret stay entirely invisible to the person signing in.
- AC-A11Y-13: The "Remember me" control's activation area, measured as the bounding box of its label element, is at least 24x24 CSS px (WCAG 2.2 AA 2.5.8). It is currently a 16px checkbox inside a roughly 20px label (`login.html:127-139`), and this PR changes what the checkbox means. The 24px WCAG floor binds here, not the 44px house figure: see the veto record.
- AC-A11Y-14: At 320 CSS px viewport width, and at 200% zoom on 1280x1024, the login page including the new status message reflows with no horizontal scrolling and no clipped or overlapping text, in both themes, and the sign-out control is reachable in the mobile menu without scrolling past the nav items. Only existing `cp-*` tokens and CSS custom properties are used: a grep asserts the new markup introduces no raw hex colour outside the token blocks. [merged with AC-DESIGN-9]
- AC-A11Y-15: Any animation this PR adds is disabled or reduced under `prefers-reduced-motion: reduce`, matching `base.html:179`. If the PR adds no animation, the criterion is satisfied and the review says so explicitly, backed by the diff, rather than leaving it unaddressed.

### Simplicity (vetoes and scope constraints)

The orchestrator verifies these directly against the diff at review; no agent is
needed. Three of the original thirteen were amended because they collided with
the security, accessibility-floor or data-loss ranks, which simplicity cannot
override; the amendments are recorded here and in the veto list.

- AC-SIMP-1: No new runtime dependency. `requirements.txt` is unmodified and the signing uses the standard library only (`hmac`, `hashlib`, `secrets`, `base64`, `time`). Starlette's `SessionMiddleware` is not used: it requires `itsdangerous`, absent from `requirements.txt` and from `.venv`, and it binds its secret at app-construction time, which defeats rotate-on-logout. [merged with AC-SEC-45, AC-ARCH-12]
- AC-SIMP-2: No new configuration setting is introduced. The diff adds no option definition and no `Env.setting()` key that did not exist before. `secure` is derived per D4 and the session lifetimes are module-level constants, never settings: a wrong setting value here makes the cookie undeliverable on a plain-HTTP install, which is the lockout shape the spec forbids.
- AC-SIMP-3 (amended): The set of modified non-test, non-spec, non-docs files is a subset of {`couchpotato/__init__.py`, `couchpotato/runner.py`, `couchpotato/core/rate_limit.py`, `couchpotato/core/database.py`, `couchpotato/core/_base/_core.py`, `couchpotato/core/logger.py`, `couchpotato/templates/login.html`, `couchpotato/ui/templates/base.html`}. The five additions to the original list are each forced by a higher-ranked criterion: AC-SEC-42, AC-SEC-40, AC-SEC-38, AC-SEC-41 and D8 with the accessibility floor.
- AC-SIMP-4 (amended): These paths are unmodified: `couchpotato/core/db/**` (including `schema.sql` and `sqlite_adapter.py`), `couchpotato/core/settings.py`, and every `couchpotato/ui/` template other than `base.html`. This records the no-DDL decision mechanically and keeps the adapter, whose generic `else` branch has shipped this repo's worst defects twice, out of the diff entirely.
- AC-SIMP-5 (amended): At most one new file is added under `couchpotato/`, and only if AC-ARCH-2 and AC-QA-26 cannot both be met inside `couchpotato/__init__.py`. The default is no new file: sign and verify live beside their call sites, matching `auth_is_required` and `_parse_auth_required`.
- AC-SIMP-6 (amended): `couchpotato/runner.py` gains exactly two things: the extraction of the existing `auth_required` migration block into one module-level function with one caller (AC-ARCH-10), and the startup secret bootstrap of D2. No other conditional branch is added.
- AC-SIMP-7: The signed cookie payload carries an expiry timestamp and its signature and nothing else: no format-version prefix, no session identifier, no username, no client IP binding, no user-agent binding.
- AC-SIMP-8: Invalidation is whole-secret rotation. The change writes exactly one new property identifier and adds no per-session record, no session registry or list, no active-sessions UI, and no persisted login audit trail.
- AC-SIMP-9: No legacy-cookie compatibility path exists (D5). `get_current_user` contains no comparison of the cookie against `Env.setting('api_key')` after the change.
- AC-SIMP-10: The change deletes as well as adds: the `# codeql[py/clear-text-storage-sensitive-data]` suppression on the `set_cookie` line is removed rather than carried forward, and `api_key_val` is no longer read in `login_post`.
- AC-SIMP-11 (amended): `create_app` gains no `add_middleware` call and no new brute-force lockout mechanism. AC-SEC-42 is satisfied by changing the existing `RateLimitMiddleware` exemption to key on path prefix, using the adjacent `_EXEMPT_PREFIXES` shape, not by adding a limiter. No CSRF token machinery is added: AC-SEC-37 is satisfied by requiring a valid session to rotate.
- AC-SIMP-12: The L1 fix is implemented at the existing log call sites in `couchpotato/__init__.py` plus, at most, a suppression helper in `couchpotato/core/logger.py`. No new module is added and no logging `Filter` subclass is introduced.
- AC-SIMP-13: No new index name is passed to `db.get()` and no new `_t` document type is written. The secret is stored as a `property` row, which is the only lookup path measured to honour its key.

### Vetoed at planning

Dropped criteria, with the reason. A review finding that re-raises one of these
is rejected with a pointer to this list, per the harness exit condition.

- **AC-ARCH-9 and AC-QA-24 (L8: one shared `auth_required` parser or constant) — VETOED.** The two parsers differ deliberately (`_parse_auth_required` returns `None` so the caller can fall back; `guardAuthRequired` reads anything unrecognised as ON), so this is not pure duplication. Sharing a constant means `couchpotato/core/_base/_core.py` importing from `couchpotato/__init__.py`, a core-to-web edge the same review records as debt in L7, and it edits `guardAuthRequired`, the single function standing between the settings UI and an unrecoverable lockout, inside the PR that rewrites cookie authentication. **L8 returns to the deferred table**, ideally paired with L7 in the dead-code pass (T7). The behavioural guarantee L8 was proxying for is kept by AC-OPS-47, which is executable and needs no import edge.
- **AC-ARCH-1 (session code in a new module under `couchpotato/core/` importing no FastAPI symbol) — VETOED as over-specified structure.** The testability requirement behind it survives as AC-QA-26 (injectable clock and secret source), which a helper in `couchpotato/__init__.py` satisfies. AC-ARCH-2 and AC-ARCH-3 keep the anti-drift value without mandating a file. AC-SIMP-5 leaves the escape hatch if the two cannot be met together.
- **AC-DESIGN-8 (post-login return-to destination, with same-origin validation) — VETOED.** `lens-design` itself nominated it as the first to cut. It adds a `next` parameter and an open-redirect surface not traceable to the spec's stated goal, on the highest-risk path in the tree. Log it as a follow-up if expiry proves annoying in practice.
- **AC-A11Y-16 (a11y of a new session-lifetime or sign-out-everywhere setting) — VETOED as vacuous.** AC-SIMP-2 forbids a new setting, so the criterion can never fail.
- **AC-SEC-42's second half (`check_password` moved to `run_in_threadpool`) — VETOED from this PR.** The credential-guessing path is closed by the rate-limit fix alone. Event-loop occupancy by bcrypt is a performance concern (precedence rank 6) with its own carried finding (T2.4) and belongs with the other event-loop work, not on the branch that rewrites cookie authentication.
- **AC-DATA-13's execution half (`scripts/backup.sh` run end to end against a test data directory) — REDUCED to documentation plus the pre-change-snapshot restore test.** The script copies the whole database file, so that the secret lands in the snapshot follows by construction; the operator-visible consequence (restoring a pre-rotation snapshot undoes the revocation) is the part worth writing down.
- **AC-DESIGN-10's E2E half (drive a password change through the settings UI and assert the user-facing feedback) — REDUCED to the copy assertion in AC-SEC-38.** The behaviour is proven by AC-SEC-38's cookie replay; a full settings-UI E2E for one description string is ceremony.
- **AC-QA-18 (concurrent double-submitted login) — MERGED into AC-DATA-2**, which already drives four or more concurrent logins and asserts every issued cookie verifies.
- **The 44px house touch-target figure — NOT APPLIED to the login form.** AC-A11Y-13 binds at the WCAG 2.2 AA floor of 24x24 CSS px. The existing 40px submit button is accepted as-is: raising it is rework beyond this PR, and `lens-accessibility` declined to invent it.
- **`lens-simplicity`'s original AC-SIMP-3, AC-SIMP-4, AC-SIMP-5, AC-SIMP-6 and AC-SIMP-11 — PARTIALLY OVERRIDDEN**, per the harness rule that simplicity cannot override the data-loss, security or accessibility-floor ranks. The amended forms above are the binding ones. The specific overrides: `couchpotato/core/rate_limit.py` (AC-SEC-42), `couchpotato/core/database.py` (AC-SEC-40), `couchpotato/core/_base/_core.py` (AC-SEC-38), `couchpotato/core/logger.py` (AC-OPS-45/46), `couchpotato/templates/login.html` and `couchpotato/ui/templates/base.html` and `tests/e2e/**` (D8 plus AC-A11Y-1 through AC-A11Y-15), and the startup bootstrap in `couchpotato/runner.py` (D2, forced by the measured duplicate-secret race).
- **`lens-simplicity`'s recommendation to skip `lens-design` and `lens-accessibility` — REJECTED.** It rested on "no UI change", which stopped being true once D8 put the sign-out control and the login-page message region in scope. Both lenses ran and both found floor-level defects already live on `login.html`.

---

## Spec gaps found at review

Findings with no acceptance criterion behind them. Recorded because that list is
how the harness improves rather than merely runs.

**From tranche A (implementation), 2026-08-07. Each verified by the orchestrator
against the repo, not taken from the report.**

1. **`caplog.at_level('INFO')` captures nothing, repo-wide.** `logger.py:24`
   calls `logging.addLevelName(21, 'INFO')`, which overwrites
   `_nameToLevel['INFO']` from 20 to 21, so the string form sets the threshold
   above every genuine INFO record. Verified: the name resolves to 20 before
   importing `couchpotato.core.logger` and 21 after. This produces a false RED
   that reads as "the code never logged" and cost the implementer a detour.
   **No AC covered it**, yet AC-OPS-41, AC-OPS-44, AC-OPS-46, AC-OPS-47 and
   AC-OPS-52 all assert on records at INFO or above, so most of the operability
   set was one obvious idiom away from being unwritable. Closed mechanically by
   a `check-traps` rule rather than a note (commit `9df829ad`).

2. **AC-QA-21's prescribed assertion is vacuous against a correct
   implementation.** It names a counting spy on `Settings.setProperty`, but
   AC-DATA-3 forbids using `setProperty` (its bare `except Exception:` is the
   defect), so the secret is written by a different function and the prescribed
   spy can never fire in any configuration. A criterion that names its own
   assertion mechanism can prescribe one that cannot fail. The behavioural
   promise was kept by an `ast` guard that the bootstrap sits inside
   `if auth_is_required():`.

3. **AC-DATA-2 as worded contradicts D2.** "Four concurrent first-time logins
   against a database with no secret" cannot leave one row when D2 and
   AC-ARCH-6 forbid the request path from creating a secret: with no secret, a
   login issues no cookie at all. Split into two executable halves (concurrent
   `ensure_session_secret` against an empty store; concurrent real logins
   against a bootstrapped one). **The planning cycle produced two criteria that
   cannot both hold** and no lens caught it, because each owned only one.

4. **AC-QA-19 contradicts D2 in the same way, and is still open.** It requires
   that after the secret is deleted from under a running process "a fresh login
   recovers a working session without a restart", which needs the login path to
   regenerate — exactly what D2 forbids. Current behaviour: locked out until
   restart, with an ERROR naming `config.ini`. **Whoever takes that tranche must
   reopen the D2 wording rather than quietly satisfying one and dropping the
   other.**

5. **Tranche A introduces a live secret-disclosure hole that only a later
   tranche closes.** Executed by the orchestrator against a real adapter:
   `ensure_session_secret` creates one `property` row with `identifier =
   session_secret`, and `db.all('id')` returns it verbatim, which is exactly
   what `database.py:197-213` iterates. So `GET /api/<key>/database.list_documents`
   would return the signing secret in cleartext, and it survives every `api_key`
   rotation. AC-SEC-40 covers the fix, but **nothing in the plan said the
   tranches could not be shipped independently.** The sequencing constraint is
   now explicit: **AC-SEC-40 must land in the same PR, and this branch must not
   reach `master` without it**, because a push to `master` auto-publishes a beta.

6. **The plan assumed a pre-push hook that the implementer could not find.** It
   reported "no git hooks installed" from `.git/hooks` (samples only) and used
   `--no-verify`. Wrong: the hook is wired through
   `core.hooksPath = .githooks`, which holds an executable `pre-push`. Harmless
   here because the gate was run by hand, but a sub-agent concluding "there is
   no gate" is one step from concluding "so I need not run one".
