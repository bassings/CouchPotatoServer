# CouchPotato API Reference

CouchPotato uses a FastAPI-based API. All endpoints are prefixed with the configured API base
(default: `/api/<api_key>/`).

## Interactive Documentation

When running, FastAPI provides automatic OpenAPI documentation:
- **Swagger UI**: `http://localhost:5050/docs`
- **ReDoc**: `http://localhost:5050/redoc`
- **OpenAPI JSON**: `http://localhost:5050/openapi.json`

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
with no value, in one of three forms:

- a refused group save: `Refused a settings group save: section=... first_row=...
  first_column=... reason=... offences=N`;
- a request that was not a JSON POST of exactly `section` and `rows` (HTTP 400):
  `Refused a settings group save: the request was not a JSON POST of exactly the
  expected keys`, which names nothing the caller sent;
- a per-column save through `settings.save` that was refused: `Refused a
  per-column save of "section.option": it is saved with its group, not on its
  own` (the registered column, never the caller's spelling), or `Refused a
  settings save: the option name is not allowed (section=...)`, or `Refused a
  settings save: the option name is an access flag (section=...)`, or `Refused a
  settings save: the section or the option name was not text`.

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
> settings.save. Nothing was saved."}`. The flags are written only by the
> server's own option registration.

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
