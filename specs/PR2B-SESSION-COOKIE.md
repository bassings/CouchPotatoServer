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

**NOT YET WRITTEN.** `/plan-cycle` writes them here. Per M15 in the parent plan,
no implementation starts before this section is populated.

### Product
### Security
### Data
### Architecture
### Operability
### QA
### Simplicity (vetoes and scope constraints)

---

## Spec gaps found at review

<Filled by the review cycle: findings with no AC behind them.>
