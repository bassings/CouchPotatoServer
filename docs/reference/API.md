# CouchPotato API Reference

CouchPotato uses a FastAPI-based API. All endpoints are prefixed with the configured API base
(default: `/api/<api_key>/`).

## Interactive Documentation

When running, FastAPI provides automatic OpenAPI documentation:
- **Swagger UI**: `http://localhost:5050/docs`
- **ReDoc**: `http://localhost:5050/redoc`
- **OpenAPI JSON**: `http://localhost:5050/openapi.json`

## Changed: parameters are decoded once

In versions after v3.310.0 an API parameter reaches its handler exactly as the
web framework delivered it. A value in a query string or a form body is
percent-decoded once, by the framework, and a value in a JSON body is not
decoded at all. Earlier versions decoded every string a second time, so
`a%41b` arrived as `aAb`. A client that percent-encoded its values twice to work
around that must now encode once; a client that already encoded once is
unaffected. Values that an earlier version stored in changed form are not
repaired and must be entered again.

## Core Endpoints

### Application

| Endpoint | Description |
|----------|-------------|
| `app.available` | Check if the app is running |
| `app.version` | Get application version |
| `app.restart` | Restart the application |
| `app.shutdown` | Shut down the application |

### Movies

| Endpoint | Description |
|----------|-------------|
| `movie.add` | Add a movie to the wanted list |
| `movie.edit` | Edit movie details |
| `media.list` | List all movies (with filters) |
| `media.get` | Get a specific movie |
| `media.delete` | Delete a movie |
| `media.refresh` | Refresh movie metadata |
| `media.available_chars` | Get available first characters for filtering |

### Search

| Endpoint | Description |
|----------|-------------|
| `search` | Search for movies by title |
| `movie.searcher.full_search` | Trigger a full search for all wanted movies |
| `movie.searcher.try_next` | Try next release for a movie |
| `movie.searcher.progress` | Get current search progress |
| `searcher.full_search` | Alternative full search endpoint |
| `searcher.progress` | Alternative search progress endpoint |

### Releases

| Endpoint | Description |
|----------|-------------|
| `release.manual_download` | Manually download a specific release |
| `release.delete` | Delete a release |
| `release.ignore` | Ignore/unignore a release |

### Quality Profiles

| Endpoint | Description |
|----------|-------------|
| `quality.list` | List all quality definitions |
| `quality.size.save` | Save quality size settings |
| `profile.list` | List all profiles |
| `profile.save` | Save a profile |
| `profile.save_order` | Save profile display order |
| `profile.delete` | Delete a profile |

### Categories

| Endpoint | Description |
|----------|-------------|
| `category.list` | List all categories |
| `category.save` | Save a category |
| `category.save_order` | Save category display order |
| `category.delete` | Delete a category |

### Notifications

| Endpoint | Description |
|----------|-------------|
| `notification.list` | Get recent notifications |
| `notification.listener` | Long-poll for new notifications |
| `notification.markread` | Mark notifications as read |

### Dashboard

| Endpoint | Description |
|----------|-------------|
| `dashboard.soon` | Get upcoming/recent movies |
| `charts.view` | View movie charts |
| `charts.ignore` | Ignore a chart entry |
| `suggestion.view` | Get movie suggestions |
| `suggestion.ignore` | Ignore a suggestion |

### Library

| Endpoint | Description |
|----------|-------------|
| `library.query` | Query the library |
| `library.related` | Get related movies |
| `library.tree` | Get library tree structure |

### Automation

| Endpoint | Description |
|----------|-------------|
| `automation.add_movies` | Add movies from automation sources |

### Database

| Endpoint | Description |
|----------|-------------|
| `database.compact` | Compact the database |
| `database.list_documents` | List database documents |
| `database.document.update` | Update a document |
| `database.document.delete` | Delete a document |
| `database.reindex` | Reindex the database |

### Library Management

| Endpoint | Description |
|----------|-------------|
| `manage.update` | Trigger library scan |
| `manage.progress` | Get scan progress |

### Settings

| Endpoint | Description |
|----------|-------------|
| `settings` | Get all settings |
| `settings.save` | Save one setting. Refuses the columns of a multi-row group, and option names the config file cannot hold, such as an empty one (see below) |
| `settings.save_group` | Save every column of one multi-row group in one request |

#### Multi-row groups: `settings.save_group`

Newznab and Torrentpotato indexers, and the IMDB, iTunes and Letterboxd
automation lists, are stored as comma-separated columns that the readers pair
by position. They are saved as a unit, so a row can never be paired with another
row's key. Which settings these are comes from the `combine` declarations the
providers register (`settings` returns each group's columns and state), not from
a list kept here.

**Request.** `POST /api/<api_key>/settings.save_group/` with
`Content-Type: application/json` and a body of exactly two keys:

```json
{"section": "newznab", "rows": [{"use": "1", "host": "https://indexer.example", "api_key": "...", "extra_score": "0", "custom_tag": ""}]}
```

Each row is an object holding every column of the group as a string (a comma, a
control character or a missing or unknown column is refused). The server writes
every column from the rows and saves once, or saves nothing. Any other method,
any content type but `application/json`, any query parameter other than the
cache-buster `t`, or an extra or missing top-level key is refused with HTTP 400.

**Success.** `{"success": true}`. The body never carries a cell value.

**Refusal.** `{"success": false, "error": "<fixed text>", "invalid": [{"row": 1,
"column": "host", "reason": "comma"}]}`. `row` is the 0-based row as sent and
`column` the column name; both are `null` when the whole request is at fault.
`reason` is one of `comma`, `control_character`, `not_string`, `not_encodable`,
`missing_column`, `unknown_column`, `not_writable`, `unknown_section`,
`malformed`, `misaligned`. The response names rows and columns and never a
value. A refused save leaves `config.ini` and the in-memory settings unchanged.
A write failure returns `{"success": false, "error": "..."}` with no `invalid`.

**Events.** A group save fires no `setting.save.<section>.<option>` event (nor
`.after` or `.committed`): it sets the columns and saves directly. No hook is
registered for any column of these groups today.

**Where an operator finds a refusal.** One WARNING per refused save in the log,
with no value, in one of four forms:

- a refused group save: `Refused a settings group save: section=... first_row=...
  first_column=... reason=... offences=N`;
- a request that was not a JSON POST of exactly `section` and `rows` (HTTP 400):
  `Refused a settings group save: the request was not a JSON POST of exactly the
  expected keys`, which names nothing the caller sent;
- a per-column save through `settings.save` that was refused: `Refused a
  per-column save of "section.option": it is saved with its group, not on its
  own` (the registered column, never the caller's spelling), or `Refused a
  settings save: the option name is not allowed (section=...)`, or `Refused a
  settings save: the section or the option name was not text`;
- a per-column save of an option's access-flag name: `Refused a settings save:
  the option name is an access flag (section=...)`.

> **Breaking change for scripts.** `settings.save` now refuses every column of
> a multi-row group, in any case or with leading or trailing whitespace in the
> name (`host`, `API_KEY`, ` host `). It returns
> `{"success": false, "error": "\"newznab.host\" is saved together with the rest
> of its group, not on its own. ..."}`, writes nothing, fires no hook and logs
> one WARNING naming `section.option` and no value. Scripts that wrote these
> columns one at a time must send the whole group to `settings.save_group`. A
> Settings tab opened before the upgrade shows the same text in its error toast
> until it is reloaded. Options outside a group (`newznab.enabled`,
> `newznab.custom_categories`, `torrentpotato.jackett_url`, and every other
> setting) still save one at a time. Separately, `settings.save` refuses, for every section, any
> option name that is empty, contains whitespace, a control character, `=` or `:`, or starts
> with `[`, `#` or `;` (the config file cannot hold them: `=` and `:` break every
> later save until restart, and a leading `#` or `;` reloads as a comment), and a
> `section` or `name` that is not text. The name is never echoed in the refusal.
> It also refuses, for every section, the name of an option's access flag
> (`<option>_internal_meta`, which holds `ro`, `hidden` or `rw`) in any case and
> with leading or trailing whitespace, whether or not the option is registered:
> `{"success": false, "error": "An option flag cannot be changed through
> settings.save. Nothing was saved."}`. Nothing but the server's own option
> registration writes a flag, and registration sets each declared flag to its
> declared value at every start.
>
> **Operator note.** Versions before this fix accepted a flag name in another
> letter case. After upgrading, declared flags are restored automatically at
> start-up. An operator who suspects earlier tampering should look in
> `config.ini` for `_internal_meta` lines on options that should be changeable
> (for example the password or the authentication switch) and remove them with
> the server stopped. The server does not remove flags for options that declare
> none.
>
> **Behaviour change: option names are matched without regard to case.**
> `settings.save` handles an option under its registered (lower-case) name
> whatever case the caller sends, so the same validation, password hashing,
> `auth_required` check, soft chroot confinement, masked-value refusal and events
> apply to `core.PASSWORD` as to `core.password`. A script that sent an
> upper-case name and relied on it skipping one of those steps no longer can. A
> section name is still matched exactly.

### Jackett

| Endpoint | Description |
|----------|-------------|
| `torrentpotato.jackett_test` | Ask Jackett for its configured indexers and return them. Writes nothing |
| `torrentpotato.jackett_sync` | Do the same, then write the indexers into the TorrentPotato rows (merge by default, or replace) |

Both are called as `/api/<api_key>/<endpoint>/`, by GET or POST, with the
CouchPotato API key like every other route (a wrong or missing key is HTTP 401
`API key required`, whatever the headers). They are also **Origin-checked**:
once the key is accepted, a request that carries no `Origin` or `Referer`, or
one from another origin, is refused with HTTP 403 `{"success": false, "error":
"Cross-origin request refused"}` before the route runs, because a plain GET can
otherwise be sent by a page on another site. Send `Origin` (or `Referer`) with
the address the server is reached at. The answers below are HTTP 200 with
`success` true or false.

**Parameters** (all optional):

| Parameter | Meaning |
|-----------|---------|
| `jackett_url` | Jackett base address. Must come with its own `jackett_api_key` |
| `jackett_api_key` | Jackett API key. Empty or blank counts as not sent |
| `replace` | `jackett_sync` only. Replaces every stored indexer only for `true` or the text `true`, `1`, `yes` or `on`; anything else merges, and a merge is refused when the stored rows do not line up |

With no parameters both routes use the **saved** Jackett address and API key
(Settings, TorrentPotato, "Jackett URL" and "Jackett API Key"). With a
`jackett_url` and a `jackett_api_key` both use exactly those two, and the saved
key is never sent. A `jackett_url` without a key is refused ("A Jackett URL must
be sent with its own API key. The saved API key is only used with the saved
URL."). A key without a URL is sent to the saved address. A supplied pair, or a
supplied key alone, is not checked against the binding below and does not change
it.

**Success.** `jackett_test`: `{"success": true, "indexers": [{"id", "title",
"potato_url", "configured", "supports_movies"}], "count": N}`. `jackett_sync`:
`{"success": true, "message": "...", "added": N, "skipped": N, "total": N,
"indexers": [...]}`. Only indexers Jackett reports as configured and able to
search movies are listed.

**Failure.** `{"success": false, "error": "<text>"}`. The texts a caller can
meet:

| `error` | When |
|---------|------|
| `Check the Jackett URL is right, then copy the API key from your Jackett dashboard, paste it above and press Sync. This is needed once after this update, or after the URL changes.` | The saved key may not be used with the saved address (the next section). Nothing was sent to Jackett and nothing was written. The text carries no address and no key. "Paste it above" and "press Sync" describe the Settings page and the setup wizard; an API caller is told the same thing |
| `Jackett did not accept the API key. Copy it again from your Jackett dashboard.` | Jackett answered the request with HTTP 401, or its reply contains an `<error>` element (the whole reply, or inside it) whose `code` is exactly `100`. Only the status and that code are read; nothing else from the reply, and never the exception text (which carries the request URL and so the key), is returned or logged |
| `Jackett URL and API key are required` (`jackett_sync` adds ` Please configure them in settings.`) | No saved key and none supplied; or a key is supplied but there is no saved address (a key sent alone goes to the saved address); or a saved address but no key. A saved key that is blank after stripping counts as no key. A **saved key with an empty saved address is not this case**: it gets the refusal text above, with `reason=unbound` |
| `Jackett returned an error response` | The reply contains an `<error>` with any other code, or none |
| `Failed to connect to Jackett: <ExceptionName>` | The request failed (for example a connection error, or an HTTP status other than 401). Only the exception's class name is shown |
| `No response from Jackett`, `Failed to parse Jackett response XML`, and (`jackett_sync` only) `No configured indexers found in Jackett` | As worded |
| `Jackett URL and API key must be text` | A value that is not text was sent |
| `The saved TorrentPotato rows do not line up, so a sync could pair a key with the wrong host. Fix the rows in Settings first. Nothing was changed.` | `jackett_sync` merge, stored rows misaligned. Normally this is checked before any request to Jackett; the rows are checked again when they are written, so if they go out of line while the request is in flight, the refusal in the second row below comes back after the request |
| `None of the N Jackett indexers could be saved: their address, name or the API key contains a comma or a control character` | `jackett_sync`: every indexer Jackett returned has a cell the settings file cannot hold. Jackett was asked; nothing was written. (If only some cannot be stored, the sync succeeds and `skipped` counts them) |
| `The stored rows do not line up. Fix them in Settings first. Nothing was saved.` | `jackett_sync` merge: the rows went out of line between the check above and the write (another save landed meanwhile). Jackett was asked; nothing was written |
| `The settings could not be saved. Nothing was changed.` | `jackett_sync`: writing the rows to `config.ini` failed. Jackett was asked; the settings and `config.ini` are as they were |

An HTTP 401 that does not come from Jackett (for example basic authentication
on a reverse proxy in front of it) is also reported as the key being rejected,
which re-copying the key will not fix. Neither the 401 nor the `code` 100 reply
has been observed against a real Jackett: both come from Jackett's documented
behaviour. CouchPotato's HTTP client stops calling a host for 15 minutes after six
failed requests, for any host other than `localhost`, a loopback address or a
private (RFC 1918) address; a 401 does not count towards that, so wrong keys do
not pause the host (or the searches through it).

#### The saved key is only sent to the address it was saved for

CouchPotato remembers which address the saved API key belongs to (the
"binding", one hidden option in the `torrentpotato` section of `config.ini`,
beside the key). A parameterless `jackett_test` or `jackett_sync` sends the
saved key only when the binding is not empty and equals the saved address,
compared after the address is normalised (scheme and host in lower case, the
default port and a trailing slash dropped, userinfo and path kept exactly). The
address that is checked is the address that is used, from one read.

- Saving the key writes the binding in the same `config.ini` write, as the
  address saved at that moment. If that address cannot be normalised (see the
  limits below) the binding is left empty. Saving an empty or blank key clears
  the binding in the same write. Saving the address alone never touches it.
  Nothing binds a key automatically, at start-up or otherwise.
- A change of `jackett_url` through `settings.save` therefore cannot send the
  saved key to the new address: the next parameterless call is refused, with the
  text above and no request to Jackett. Changing the address back makes it work
  again without entering the key. Entering the key again, after checking the
  address, binds it to whatever address is saved.
- The binding cannot be read, written or removed through `settings.save`,
  `settings.save_group` or the settings read, in any spelling of its name or its
  access flag. It is not shown on any page.
- Searches and downloads are not affected: each stored TorrentPotato row sends
  its own `pass_key` to its own host.
- A refusal writes nothing and clears nothing. It logs one WARNING per refused
  call and nothing else: `Refused torrentpotato.jackett_sync: the saved Jackett
  API key is not bound to the saved address (reason=<code>)` (or
  `torrentpotato.jackett_test`). The reason is `mismatch` when the binding is not
  empty and differs from the saved address, and `unbound` when the binding is
  empty or absent, or the saved address has no normal form. No address, key or
  binding appears in the log line or the response. A refusal does not affect
  start-up, the health check or any other route.

#### Upgrade, rollback and restore

1. The change adds one option to `config.ini` (the binding, with its access
   flag `jackett_key_binding_internal_meta`) and no database change, so rolling
   the image back needs no data step.
2. The stable releases before this change (v3.278.0 and earlier) ignore the
   binding and do not show its value: their settings read shows an option they
   do not know as asterisks of the same length.
3. Rolling back and forward with no settings changed leaves a bound key bound to
   the same address. After restoring an older `config.ini` backup, or after
   changing the Jackett address while running a build that writes the binding
   but does not check it (the betas from v3.298.0-beta.1 up to the one before
   v3.306.0-beta.1), or while running v3.278.0 or earlier, the saved key is
   unbound or mismatched and the next `jackett_test` or `jackett_sync` is
   refused until the key is entered again. Nothing re-binds it automatically.
4. After upgrading, every existing install has a saved key and no binding, so its
   first `jackett_sync` (or `jackett_test`) is refused once with the text above:
   check the address, enter the key once, and it is bound. Searches and downloads
   carry on with no action.
5. v3.278.0 and earlier do not maintain the binding: a key replaced while
   running one keeps the earlier key's binding. After upgrading again, the saved
   key can only be sent to the address the earlier key was bound to (an address
   this install once trusted with a Jackett key), never to a new one. Enter the
   key again on the upgraded release to bind it.

Releases, for the facts above: stable v3.278.0 is the last without the binding;
betas from v3.298.0-beta.1 save the binding when the key is saved but do not
check it, and from v3.306.0-beta.1 they check it, so an install that ran one of
those betas may already have a binding. The first stable release with the check
is v3.310.0.

A binding value that `config.ini` held before this release first ran (the
option did not exist, so someone planted it) is emptied once at the first start,
and the clear is logged once at INFO naming the section and option only.

#### Known limits

- **The Jackett key is readable by a holder of the CouchPotato API key.** `GET
  /api/<api_key>/settings` shows `torrentpotato.jackett_api_key` masked, but
  `torrentpotato.pass_key` is a "combined" setting (one comma-separated list
  that holds a value for every indexer row) and is returned unmasked, and a
  Jackett sync copies the Jackett key into the `pass_key` of every indexer it
  adds. So this change (SEC-005, the binding) does **not** protect the Jackett
  key from a holder of the CouchPotato API key: after any sync, including one
  they start themselves with `torrentpotato.jackett_sync` and a matching
  `Origin`, they read the key from `pass_key`. What the binding stops is
  narrower: an actor who can cause a settings write but cannot read the reply
  from having the saved key sent to an address of their choosing. Masking those
  rows is open work: see "Credentials in combined rows are returned unmasked by
  the settings read" in `docs/technical-debt.md`.
- **The key cannot be redirected by a settings write, except through the
  outbound proxy settings, for a Jackett on plain http.** `core.use_proxy` and
  `core.proxy_server` are ordinary writable options, so a settings write can
  route an http request to Jackett, key included, through a host the writer
  chose. This affects every credential sent over http and is not closed here.
- **A redirect from Jackett that keeps the query forwards the key**, because it
  travels in the query string. Not closed here.
- **A merge sync does not update the `pass_key` of indexers already stored** when
  the Jackett key is rotated.
- **Addresses that have no normal form cannot be bound.** A key saved over such
  an address stores an empty binding, so every `jackett_test` and `jackett_sync`
  is refused until the address is fixed and the key entered again. That covers
  an address with a query or a fragment (even an empty one), whitespace or a
  control character inside it, a backslash, an invalid port or bracket, and any
  address on which the two URL parsers CouchPotato uses disagree. In particular:
  - A host written in non-ASCII characters (`http://bücher.example`) cannot be
    bound; write it in its punycode form (`http://xn--bcher-kva.example`), which
    can. (The Kelvin sign, U+212A, is read as ASCII `k`, so a host written with it
    binds as the ASCII host.)
  - An address with non-ASCII characters in its path or its userinfo
    (`http://h:9117/jackétt`) may have synced before and is now refused: the
    key cannot be bound to it. The percent-encoded spelling
    (`http://h:9117/jack%C3%A9tt`) can be bound, and in versions after v3.310.0
    it can be typed directly into the Jackett URL field: it is stored as typed,
    and a key entered after it is bound to it. The setup wizard and a saved
    field behave the same way, and saving the field again keeps the value.
    **v3.310.0 and earlier only:** typing it into Settings does not work, because
    the settings save decoded every value one more time, so `jack%C3%A9tt` was
    stored as `jackétt` and the binding stayed empty (the same by form, JSON or
    GET). Two ways that do work on those versions. (a) Type the double-encoded
    spelling (`http://h:9117/jack%25C3%25A9tt`) in the Jackett URL field; it is
    stored as `jack%C3%A9tt`; then enter the key again. (b) Take a copy of
    `config.ini` first. With CouchPotato stopped, set `jackett_url` in
    `config.ini` to `http://h:9117/jack%C3%A9tt`, start it, then enter the key
    again. Both bind, and a parameterless sync is not refused. A value stored
    either way is kept as it is when you upgrade to a later version, and the
    caution not to save the field again no longer applies there. Rows already
    stored under the old spelling are matched by exact text, so a merge sync can
    add a second copy of each.
- **A planted access flag defeats the start-up clear.** Someone who can write
  settings on a release before the access-flag fix could also plant the
  binding's access flag (those releases accept it under a different letter
  case), and the clear would then leave their value. That person can already take
  the Jackett key directly on such a release.

### Downloaders

| Endpoint | Description |
|----------|-------------|
| `download.<name>.test` | Test downloader connection |

### Logging

| Endpoint | Description |
|----------|-------------|
| `logging.get` | Get log entries |
| `logging.partial` | Get partial log |
| `logging.log` | Submit a log entry |
| `logging.clear` | Clear logs |

### Updater

| Endpoint | Description |
|----------|-------------|
| `updater.info` | Get update information |
| `updater.check` | Check for updates |
| `updater.update` | Trigger update |

### File Browser

| Endpoint | Description |
|----------|-------------|
| `directory.list` | List directory contents (for UI file browser) |
| `file.cache/(.*)` | Serve cached files |

### Userscripts

| Endpoint | Description |
|----------|-------------|
| `userscript.add_via_url` | Resolve a movie-site page URL to a movie and return its metadata (used by the new-UI add-by-URL flow / bookmarklet) |

> The legacy iframe/bookmarklet endpoints (`userscript`, `userscript.includes`,
> `userscript.bookmark`, `userscript.get/<provider>/<script>`) were retired in
> UI-CLEANUP-02; add-by-URL is now served through the new UI at `/add/?url=`.

## Authentication

API calls require the API key in the URL path: `/api/<api_key>/<endpoint>`.
The API key is generated on first run and stored in settings.

## Response Format

Most endpoints return JSON with the structure:
```json
{
  "success": true,
  ...
}
```
