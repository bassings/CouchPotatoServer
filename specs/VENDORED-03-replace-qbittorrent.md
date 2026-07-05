# VENDORED-03 — Replace vendored qBittorrent client (`lib/qbittorrent`) with `qbittorrent-api`

## Problem

`couchpotato/lib/qbittorrent/client.py` is a vendored copy of an early
`python-qbittorrent` client that speaks qBittorrent's **legacy WebUI v1
API**. That API was **removed in qBittorrent 4.2 (December 2019)** — the
vendored client is broken against any qBittorrent release from the last six
years. Its endpoints (`/login`, `/query/torrents`, `/command/download`, etc.)
simply no longer exist on a modern qBittorrent instance; every call would
404.

The sole consumer is `couchpotato/core/downloaders/qbittorrent_.py`
(`from couchpotato.lib.qbittorrent.client import QBittorrentClient`).

The vendored client also:

- reconnected (built a brand-new client and called `login()`) on **every
  single operation** — `download()`, `getAllDownloadStatus()`, `pause()`,
  `processComplete()` all called `self.connect()` first, which unconditionally
  logged out and re-logged in. Modern qBittorrent bans an IP after repeated
  failed logins, so this pattern is actively dangerous against a real
  instance, not just inefficient.
- read the private `self.qb._is_authenticated` attribute to determine auth
  state instead of any public API.
- had no way to add a torrent already paused: qBittorrent's legacy `/command/download`
  endpoint the vendored client used had no paused/stopped parameter, so CP's
  own `paused` config option was silently a no-op for this downloader.
- used bare `except Exception` everywhere, so a real auth failure and a
  transient network blip were indistinguishable.

## Chosen replacement

**`qbittorrent-api` (PyPI), import name `qbittorrentapi`, pinned at
`2026.6.1`** (latest at time of writing — confirmed via
`pip index versions qbittorrent-api`).

- **License:** MIT (compatible with CP's GPL-3).
- Pure-Python; its only dependencies are `requests`, `urllib3`, and
  `packaging` (all already present in `requirements.txt`), so no
  musllinux/cross-arch build concern for the Alpine Docker image, and it
  installs unmodified on Windows/macOS/Linux for direct (non-Docker) runs.
- Actively maintained (frequent CalVer releases), talks qBittorrent's modern
  WebUI v2 API (the only API any supported qBittorrent version exposes),
  and exposes typed exceptions instead of forcing callers to guess at
  falsy/truthy return values.
- **Supported qBittorrent floor: v4.1+** (per the package's own PyPI summary,
  "Python client for qBittorrent v4.1+ Web API") — strictly newer than the
  vendored client's v1-API ceiling of qBittorrent < 4.2, i.e. this migration
  trades support for an already-six-years-dead API surface for support of
  every qBittorrent release from the last ~7 years plus all future ones.

## Call-surface mapping (verified against the installed 2026.6.1 source via
`inspect.signature`)

| CP usage (vendored v1 client) | qbittorrent-api 2026.6.1 equivalent | Notes |
|---|---|---|
| `QBittorrentClient(url)` + `.login(username=, password=)` | `qbittorrentapi.Client(host=, username=, password=)` + `.auth_log_in()` | `Client.__init__` also accepts `VERIFY_WEBUI_CERTIFICATE`, `api_key`, etc. — not needed here, defaults are fine |
| `.qb._is_authenticated` (private attr) | `.is_logged_in` (public property; performs a cheap authenticated call to check the session cookie is still accepted) | Public, documented API — no more reaching into a private attribute |
| `.logout()` | `.auth_log_out()` | |
| `.download_from_link(magnet, label=)` | `.torrents_add(urls=magnet, category=, is_stopped=)` | `label` -> `category` (qBt "category" is the WebUI v2 successor to v1 "label"); returns `"Ok."`/`"Fails."` (or, on very new Web API versions, a `TorrentsAddedMetadata` JSON object) — checked via `str(result) == 'Fails.'` |
| `.download_from_file(filedata, label=)` | `.torrents_add(torrent_files=filedata, category=, is_stopped=)` | same as above |
| `.torrents(status='all', label=)` reading `hash/name/state/progress/ratio/eta/save_path` | `.torrents_info(status_filter='all', category=)` | Returns `TorrentInfoList` of `TorrentDictionary` — both subclass `dict` (via `AttrDict`), so `torrent['hash']` etc. keep working unmodified; field names are qBittorrent's raw WebUI JSON keys, unaffected by the client library swap |
| `.get_torrent_files(hash)` reading `.name` | `.torrents_files(torrent_hash=hash)` | Same dict-subclass behavior, `f['name']` still works |
| `.get_torrent(hash)` (existence check) | `.torrents_info(torrent_hashes=hash)` — first result, or `None` if empty | No 1:1 method; wrapped in a small `_getTorrent()` helper in `qbittorrent_.py` |
| `.pause(hash)` / `.resume(hash)` | `.torrents_pause(torrent_hashes=hash)` / `.torrents_resume(torrent_hashes=hash)` | These are aliases for `torrents_stop`/`torrents_start` and internally pick the right WebUI endpoint name (`pause`/`stop`, `resume`/`start`) based on the connected qBittorrent's Web API version — no CP-side version branching needed |
| `.delete(hash)` / `.delete_permanently(hash)` | `.torrents_delete(delete_files=False, torrent_hashes=hash)` / `.torrents_delete(delete_files=True, torrent_hashes=hash)` | |

No behavior change was needed to the torrent-hash computation
(`bencodepy`/`sha1` logic) or to `getTorrentStatus()`'s ratio/progress
reading — those operate on the same raw qBittorrent WebUI field values
either way.

## Behavior deltas (new library vs. vendored v1 client)

1. **Connect once, reuse the session (fixes an active hazard).** `connect()`
   now only builds a new `qbittorrentapi.Client` if one doesn't already exist,
   and only calls `auth_log_in()` when `is_logged_in` reports the existing
   session cookie is no longer valid. Every operation (`download()`,
   `getAllDownloadStatus()`, `pause()`, `processComplete()`) calls `connect()`
   as before, but it's now a cheap reuse-check instead of a full
   logout+relogin cycle. `test()` is the one place that still forces a fresh
   client (`connect(reconnect=True)`), so testing the connection from Settings
   always reflects whatever host/username/password the user just typed rather
   than a stale client.
2. **`paused` setting now honoured (fixes a latent no-op bug).**
   `download()` passes `is_stopped=self.conf('paused')` to `torrents_add()`.
   The vendored v1 client's `/command/download` endpoint had no such
   parameter at all, so previously-added torrents always started immediately
   regardless of this setting.
3. **No more private-attribute reads.** `.is_logged_in` (a public property)
   replaces `.qb._is_authenticated`.
4. **Typed exceptions instead of falsy returns / bare `except Exception`.**
   Every operation now catches `qbittorrentapi.APIError` — the common base
   class for every typed exception the library raises (`LoginFailed`,
   `Forbidden403Error`, `Conflict409Error`, `APIConnectionError`, etc.) — so a
   real qBittorrent-reported error is distinguishable from, say, a Python
   `TypeError` in CP's own code, which would now propagate instead of being
   silently swallowed.
5. **`label` config maps to qBt's WebUI v2 "category" concept**, passed as
   `category=` on every relevant call (`torrents_add`, `torrents_info`). This
   is the direct v2 successor to the v1 API's "label" and is exposed
   identically in qBittorrent's UI, so no user-facing settings change.
6. **qBittorrent 5.0 state rename (`pausedUP` -> `stoppedUP`) handled.**
   `getTorrentStatus()`'s seeding-state check now includes `stoppedUP` and
   `forcedUP` alongside the original `uploading`/`queuedUP`/`stalledUP`, so
   the "seeding" status keeps being detected correctly against both
   pre-5.0 and 5.0+ qBittorrent (Web API v2.11.0 renamed the state string but
   `torrents_pause`/`torrents_resume` transparently pick the right underlying
   endpoint for either version).
7. **No credentials configured:** if `username`/`password` aren't set, `None`
   is passed to `Client(...)` for both (rather than skipping login
   entirely, as the old code did). If qBittorrent's "Bypass authentication
   for clients on localhost" is active, `is_logged_in`'s lightweight check
   succeeds without ever calling `auth_log_in()`, matching the old
   behavior. If auth actually is required and no credentials are configured,
   `auth_log_in()` now raises `LoginFailed` immediately (returning `False`
   from `connect()`) instead of silently proceeding to fail on the first
   real API call — a clearer failure, not a regression.

## Files changed

- `couchpotato/core/downloaders/qbittorrent_.py` — swapped the vendored
  import for `import qbittorrentapi`; reworked `connect()` to build/reuse a
  single client and login only when needed; `test()` now forces a fresh
  client via `connect(reconnect=True)`; `download()`, `getAllDownloadStatus()`,
  `pause()`, `processComplete()` ported to the `torrents_*` method names
  above; added a small `_getTorrent()` helper for the existence-check that
  the old client's `get_torrent()` provided directly.
- `couchpotato/lib/qbittorrent/` — deleted (`__init__.py`, `client.py`).
- `couchpotato/lib/__init__.py` — left intact; still needed by the other
  vendored libs (`git`, `pio`, `rtorrent`, `subliminal`, `tus`, `unrar2`).
- `requirements.txt` — added `qbittorrent-api==2026.6.1`.
- No `Dockerfile` change needed: the image install step is
  `pip install -r requirements.txt`, and `qbittorrent-api` (plus its
  `requests`/`urllib3`/`packaging` dependencies) are pure-Python, already
  present in the image.

## Tests added (`tests/unit/test_downloaders.py`, `TestQBittorrent`)

All tests mock `qbittorrentapi.Client` (via
`patch.object(qbt_main.qbittorrentapi, 'Client', ...)`, leaving the real
typed exception classes intact so `except qbittorrentapi.APIError` continues
to work in tests) — no real network calls, no real qBittorrent instance
needed:

- Client construction/reuse: `test_connect_constructs_client_with_host_username_password`,
  `test_connect_passes_none_for_missing_credentials`,
  `test_connect_reuses_client_and_skips_relogin_when_session_still_valid`
  (asserts the client is constructed exactly once across 3 calls to
  `connect()` — pins the "log in once" fix),
  `test_connect_logs_in_when_session_not_valid`,
  `test_connect_returns_false_when_login_fails` /
  `test_connect_returns_false_on_forbidden_banned_ip` (typed-exception
  handling), `test_test_logs_out_old_session_and_builds_fresh_client` /
  `test_test_tolerates_logout_failure_on_already_dead_session`.
- `download()`: `test_download_magnet_sends_category_and_honours_paused_setting`
  (pins the paused-now-honoured fix), `test_download_magnet_defaults_to_started_when_not_paused`,
  `test_download_magnet_returns_false_on_fails_response`,
  `test_download_magnet_returns_false_on_api_error`,
  `test_download_file_sends_torrent_files_and_category`,
  `test_download_file_without_filedata_fails_before_connecting`,
  `test_download_returns_false_when_connect_fails`.
- `getTorrentStatus()`: parametrized over all seeding states including
  `stoppedUP`/`forcedUP` (pins the qBt5 rename fix), plus completed/busy
  cases.
- `getAllDownloadStatus()`: single-file torrent (asserts the exact
  `torrents_info(status_filter='all', category=...)` call and file path),
  multi-file torrent (asserts the `os.walk()` subfolder path using real
  `tmp_path` directories), ignoring non-matching ids, and API-error /
  connect-failure paths returning `[]`.
- `pause()`/resume: `test_pause_stops_torrent_when_it_exists`,
  `test_resume_starts_torrent_when_it_exists`,
  `test_pause_returns_false_when_torrent_missing`,
  `test_pause_returns_false_on_api_error`,
  `test_pause_returns_false_when_connect_fails`.
- `processComplete()`/`removeFailed()`: keep-files vs delete-files-and-data,
  missing-torrent and API-error paths, and
  `test_removeFailed_delegates_to_processComplete_with_delete_files`.
- `test_qbittorrentapi_signatures_match_what_cp_passes` — imports the REAL
  `qbittorrentapi` and asserts (`inspect.signature`) that every kwarg CP
  passes (`Client.__init__`'s `host`/`username`/`password`,
  `torrents_add`'s `urls`/`torrent_files`/`category`/`is_stopped`,
  `torrents_info`'s `status_filter`/`category`/`torrent_hashes`,
  `torrents_files`'s `torrent_hash`, `torrents_delete`'s
  `delete_files`/`torrent_hashes`) and methods
  (`torrents_pause`/`torrents_resume`/`torrents_stop`/`torrents_start`,
  `is_logged_in` as a property, the `APIError`/`LoginFailed`/
  `Forbidden403Error` exception hierarchy) still exist — turns a future
  `qbittorrent-api` upgrade that silently renamed something CP depends on
  into a caught CI failure instead of a production breakage.

## Acceptance criteria

- [x] `.venv/bin/python -m pytest tests/unit/ -q` green (854 passed).
- [x] `.venv/bin/ruff check .` clean.
- [x] No remaining references to `couchpotato.lib.qbittorrent` /
  `QBittorrentClient` anywhere in the tree.
- [x] `couchpotato/lib/__init__.py`'s `sys.path` hack left intact (still
  needed by `git`, `pio`, `rtorrent`, `subliminal`, `tus`, `unrar2`).
