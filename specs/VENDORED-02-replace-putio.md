# VENDORED-02 — Replace vendored put.io client (`lib/pio` + `lib/tus`) with `putio.py`

## Problem

`couchpotato/lib/pio` is a vendored, Python-2-era fork of the official put.io
API client. It is broken under Python 3:

- `strptime()` in `couchpotato/lib/pio/api.py` used `d.iteritems()` (removed
  in Python 3 — `dict` has no `.iteritems`), which would raise `AttributeError`
  the moment it ran.
- `_str()` referenced the bare name `unicode` (Python 2 builtin, gone in
  Python 3) inside a `try/except NameError` — it "worked" only by accident,
  swallowing the `NameError` every call.
- The token was sent as a `?oauth_token=` query parameter, which get logged
  in full (including the secret) by any HTTP access log, proxy, or debug log
  line that prints the request URL.

`couchpotato/lib/tus` (a resumable-upload helper) was DEAD code: it is only
reached via `_File.upload_tus`, and nothing in CouchPotato calls
`upload_tus` — CP only ever **downloads** from put.io (torrents/magnets are
sent to put.io via `Transfer.add_url`, then the resulting file is pulled back
down with `File.download`). It never uploads anything.

The sole consumer of both was
`couchpotato/core/downloaders/putio/main.py` (`from couchpotato.lib.pio import
api as pio`).

## Chosen replacement

**`putio.py` (PyPI), import name `putiopy`, pinned at `8.8.0`** (latest on
PyPI at time of writing — confirmed via `pip index versions putio.py`).

- **License:** MIT (compatible with CP's GPL-3; permissive, no obligations).
- **Why this package:** it is the *same lineage* as the vendored copy — both
  descend from Cenk Altı's original `putio.py` client, so the call surface CP
  already used maps ~1:1 with only the deltas below. It is pure-Python (no
  compiled extension — no musllinux/cross-arch build concern for the Alpine
  Docker image), actively maintained, and its only extra dependency
  (`tus.py`) is itself pure-Python and irrelevant to CP (CP never calls the
  upload/tus path).
- Cross-platform: works unmodified on Windows/macOS/Linux, matching the "must
  run via bare `python CouchPotato.py`" requirement (not just Docker).

## Call-surface mapping (verified against the installed 8.8.0 source,
`site-packages/putiopy.py`)

| CP usage (`putio/main.py`) | putiopy 8.8.0 signature | Compatible? |
|---|---|---|
| `pio.Client(oauth_token)` | `Client(access_token, use_retry=False, extra_headers=None, timeout=5)` | Yes — single positional arg |
| `client.File.list(folder)` / `client.File.list(parent_id=...)` | `File.list(parent_id=0, per_page=1000, sort_by=None, content_type=None, file_type=None, ...)` | Yes — `folder`/`parent_id` is still the first param; CP reads `.content_type`/`.name`/`.id` off each result, which come from the raw put.io JSON payload (unaffected by the client library) |
| `client.Transfer.add_url(url, callback_url=, parent_id=)` | `Transfer.add_url(url, parent_id=0, callback_url=None)` | Yes — CP never passed the vendored copy's `extract` kwarg (which putiopy 8.8.0 dropped), so no call-site change needed; reads `.id` off the result |
| `client.Transfer.list()` reading `.id/.status/.name/.estimated_time/.file_id/.finished_at` | `Transfer.list()` | Yes — `_BaseResource.__init__` only special-cases `created_at` (parses it via `strptime`); every other JSON field, including `finished_at`, is set verbatim via `self.__dict__.update(resource_dict)`. `finished_at` stays a raw `"YYYY-MM-DDTHH:MM:SS"` string, so CP's own `datetime.strptime(t.finished_at, "%Y-%m-%dT%H:%M:%S")` in `getAllDownloadStatus` keeps working unmodified |
| `client.File.download(f, dest=, delete_after_download=)` | `File.download(self, dest=".", delete_after_download=False, chunk_size=CHUNK_SIZE, save_as="")` | Yes — CP calls it in the unbound-method style (`client.File.download(f, ...)`, passing the file instance as `self`), which is valid Python 3 |

No call sites needed behavioral changes beyond the import line itself.

## Behavior deltas (new library vs. vendored copy)

1. **Auth transport:** the vendored client put the token in the URL query
   string (`params['oauth_token'] = self.access_token`); putiopy 8.8.0 sends
   it as an `Authorization: token <token>` header instead
   (`headers["Authorization"] = "token %s" % self.access_token`). This is
   **strictly better** — it stops the OAuth token from leaking into any
   logged/proxied request URL — and is a drop-in change from CP's point of
   view (CP never inspected the request URL).
2. **Default request timeout (handled — 30s on the streaming path):** the
   vendored client passed no `timeout` to `requests`, so a stalled connection
   would hang forever. putiopy 8.8.0 defaults `Client(..., timeout=5)` (5
   seconds), applied to both the connect and read phases of every request,
   including the chunked `iter_content()` reads during `File.download()`. A
   put.io-side stall of more than 5s between chunks during a large-file
   download would therefore raise a `ReadTimeout` where the old code simply
   hung. **Resolved (VENDORED-02 review):** `putioDownloader()` — the only
   method that performs the streaming file pull — now builds its client as
   `pio.Client(self.conf('oauth_token'), timeout=30)`, giving each chunk read
   30s of headroom (chunks arrive frequently, so 30s is plenty). The light
   metadata calls (`test()`, `download()`'s add-transfer, `getAllDownloadStatus()`)
   keep putiopy's 5s default, which is appropriate for them.
   `test_putioDownloader_uses_generous_timeout_for_streaming_download` in
   `tests/unit/test_downloaders.py` asserts the download client is constructed
   with `timeout=30`.
3. **Vestigial OAuth code-flow removed.** `PutIO.getAuthorizationUrl` /
   `PutIO.getCredentials` (and their `downloader.putio.auth_url` /
   `downloader.putio.credentials` API views, plus the `oauth_authenticate`
   class attribute) were deleted rather than ported. They implemented a
   redirect through `api.couchpota.to`, a proxy service that is no longer
   running (`oauth_authenticate` was already hard-coded to `''`, so
   `getAuthorizationUrl` built a target URL of the literal form
   `"?target=..."` — a relative URL back to CP itself, not put.io — meaning
   this flow was already 100% non-functional before this change). The
   manual `oauth_token` settings field (the only way this downloader has
   actually been configurable) is untouched and still works exactly as
   before. Note: the legacy MooTools settings-page JS
   (`couchpotato/core/downloaders/putio/static/putio.js`) still calls the
   now-removed `downloader.putio.auth_url` endpoint from a "Register your
   put.io account" button; that JS belongs to the legacy asset layer being
   retired separately (see `specs/UI-CLEANUP-02-retire-userscript-embed.md`)
   and was out of scope here — the button already did nothing useful before
   this change (dead redirect target) and will now just fail its API call
   instead, no functional regression for the only supported flow (manual
   `oauth_token` entry in Settings).

## Files changed

- `couchpotato/core/downloaders/putio/main.py` — `from couchpotato.lib.pio
  import api as pio` → `import putiopy as pio`; removed `getAuthorizationUrl`,
  `getCredentials`, the `oauth_authenticate` class attribute, and their
  `addApiView` registrations; dropped the now-unused `cleanHost` import.
- `couchpotato/lib/pio/` — deleted (`__init__.py`, `api.py`).
- `couchpotato/lib/tus/` — deleted (`__init__.py`), dead code, no consumer.
- `requirements.txt` — added `putio.py==8.8.0`.
- No `Dockerfile` change needed: the image install step is
  `pip install -r requirements.txt`, so the new dependency is picked up
  automatically; `putio.py` and its `tus.py` dependency are both pure-Python
  wheels, so no new build toolchain / musllinux concern.

## Tests added (`tests/unit/test_downloaders.py`, `TestPutIO`)

All tests mock `putiopy.Client` (via `patch.object(putio_main.pio, 'Client',
...)`) — no real network calls, no real put.io credentials needed:

- `test_download_constructs_client_with_oauth_token` — `Client()` is
  constructed with the configured `oauth_token`.
- `test_download_sends_transfer_add_url_and_returns_download_id` —
  `download()` calls `Transfer.add_url(url, callback_url=None, parent_id=0)`
  and returns the transfer's `.id` via `downloadReturnId`.
- `test_download_builds_callback_url_when_download_enabled` — the
  `callback_url` is built correctly when `download` is enabled in config.
- `test_test_returns_true_when_file_list_succeeds` /
  `test_test_returns_false_on_client_error` — `test()` maps `File.list()`
  success/exception to `True`/`False`.
- `test_getAllDownloadStatus_marks_completed_when_not_downloading` /
  `test_getAllDownloadStatus_ignores_transfers_not_in_ids` /
  `test_getAllDownloadStatus_busy_when_still_transferring` — status mapping
  from `Transfer.list()` results.
- `test_getAllDownloadStatus_parses_finished_at_as_raw_string` — pins the
  behavior that matters most for this migration: a transfer's `finished_at`
  is still a raw string after going through putiopy's `_BaseResource`, so
  CP's own `datetime.strptime(t.finished_at, "%Y-%m-%dT%H:%M:%S")` parsing
  keeps working unmodified.
- `test_getAllDownloadStatus_busy_within_race_condition_window` — the
  5-minute post-completion race-condition guard still works against a
  putiopy `Transfer`.
- `test_putioDownloader_downloads_matching_file` /
  `test_putioDownloader_skips_non_matching_files` — `File.download()` is
  called with the correct file object / `dest` / `delete_after_download`,
  only for the file matching the requested `file_id`.
- `test_convertFolder_returns_zero_for_root` /
  `test_recursionFolder_finds_matching_named_folder` — folder-name lookup
  via `File.list()` still works against putiopy's result objects.

## Acceptance criteria

- [x] `.venv/bin/python -m pytest tests/unit/ -q` green (801 passed).
- [x] `.venv/bin/ruff check .` clean.
- [x] No remaining references to `couchpotato.lib.pio` / `couchpotato.lib.tus`
  anywhere in the tree (`grep -rn "lib.pio\|lib.tus"`).
- [x] `couchpotato/lib/__init__.py`'s `sys.path` hack left intact (still
  needed by the other vendored libs: `caper`, `git`, `qbittorrent`,
  `rtorrent`, `subliminal`, `unrar2`).
