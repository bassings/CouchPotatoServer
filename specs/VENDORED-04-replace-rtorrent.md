# VENDORED-04 — Replace vendored rTorrent client (`lib/rtorrent`) with `rtorrent-rpc` + a requests-backed auth transport

## Problem

`couchpotato/lib/rtorrent/` (~2500 lines, MIT-licensed, a vendored fork of
Chris Lucas's `python-rtorrent`) is dead under Python 3:
`connection.py` did `self.scheme = urllib.splittype(self.uri)[0]` —
`urllib.splittype` was removed in Python 3, so every connection attempt
raised `AttributeError` before a single RPC call could be made. rTorrent has
been completely non-functional as a CouchPotato downloader since the Python 3
migration.

The sole consumer was `couchpotato/core/downloaders/rtorrent_.py`
(`from couchpotato.lib.rtorrent import RTorrent`).

## Chosen replacement

**`rtorrent-rpc` (PyPI), import name `rtorrent_rpc`, pinned at `0.9.7`**
(latest on PyPI at time of writing — confirmed via
`pip index versions rtorrent-rpc`).

- **License:** MIT (compatible with CP's GPL-3).
- **Why this package:** it is a small, actively-typed rTorrent XML-RPC
  client supporting `scgi://` (TCP and Unix socket) and `http(s)://`
  addresses, and — critically — exposes its underlying
  `xmlrpc.client.ServerProxy` as a public, documented attribute (`rt.rpc`),
  explicitly intended for direct dotted RPC calls
  (`rt.rpc.d.multicall2(...)`, `rt.rpc.load.raw(...)`, etc.). That public
  surface is exactly what CouchPotato needs and is stable regardless of
  churn in the library's higher-level ruTorrent-flavoured convenience
  methods (`add_torrent_by_file`, tag/label helpers, choke groups, etc.),
  none of which CP uses.
- Pure XML-RPC dotted-call semantics mean the same call pattern works
  whether the underlying proxy came from `rtorrent_rpc.RTorrent(...).rpc`
  (scgi) or a hand-built `xmlrpc.client.ServerProxy` (http/https) — see
  below.

## Adapter design (`couchpotato/core/downloaders/rtorrent_.py`)

A private `_RTorrentAdapter` class picks one of three transport paths based
on the connection URL's scheme, all converging on the same `self.rpc`
(`xmlrpc.client.ServerProxy`-compatible) attribute so the rest of the
adapter (`get_torrents`, `load_magnet`, `load_torrent`, etc.) never needs to
know which path was used:

1. **`scgi://host:port`** (TCP) and **`scgi:///path/to/socket`** (Unix
   socket) — passed straight to
   `rtorrent_rpc.RTorrent(url, timeout=_RPC_TIMEOUT).rpc` (`_RPC_TIMEOUT` =
   30s).
   No auth concept applies to raw SCGI (CP's auth dropdown is documented as
   being for http(s) connections only), so no transport shim is needed here.
   **Cross-platform note:** scgi TCP works identically on Windows/macOS/
   Linux; the Unix-socket form is POSIX-only (unchanged limitation from the
   vendored lib — a Windows CouchPotato instance cannot use a local Unix
   socket path, though it could still reach a remote scgi TCP endpoint).

2. **`http://` / `https://` with no auth configured** — still routed through
   the custom requests-backed transport described below (rather than
   `rtorrent_rpc`'s own `_HTTPTransport`), for consistency and so
   `verify_ssl`/CA-bundle handling is uniform across the auth and no-auth
   cases.

3. **`http://` / `https://` with basic/digest auth and/or TLS verification
   config** — a custom `xmlrpc.client.Transport` subclass
   (`_RTorrentAuthTransport`), backed by a `requests.Session`. This is the
   core new piece, required because `rtorrent_rpc`'s public
   `RTorrent`/`_HTTPTransport` has **no per-instance way** to:
   - set HTTP Basic or Digest authentication,
   - verify TLS against a custom CA bundle path, or
   - disable TLS verification per connection (its only escape hatch is the
     process-wide environment variable `PY_RTORRENT_RPC_DISABLE_TLS_CERT=1`,
     which would affect every rTorrent connection made by the process — a
     footgun for a single downloader instance's settings, so it is
     deliberately not used).

   `_RTorrentAuthTransport.__init__(secure, auth=None, verify_ssl=True)`:
   - `auth=None` → anonymous (`session.auth` left at its default `None`).
   - `auth=('basic', user, pass)` → `session.auth = requests.auth.HTTPBasicAuth(user, pass)`.
   - `auth=('digest', user, pass)` → `session.auth = requests.auth.HTTPDigestAuth(user, pass)`.
   - `verify_ssl` (`True`/`False`/a CA-bundle path string, from
     `getVerifySsl()`) is passed straight through to `session.verify` —
     `requests` natively accepts all three forms, no conversion needed.

   `single_request()` POSTs the XML-RPC body via the session with a
   `Content-Type: text/xml` header **and a `timeout=_RPC_TIMEOUT` (30s)**
   (VENDORED-04 review — SHOULD-FIX), then parses the streamed response via
   `self.getparser()` + `feed()`/`close()` — the same shape as the deleted
   vendored lib's own `lib/xmlrpc/transports/requests_.py`, kept as a
   reference while writing this (now removed along with the rest of
   `couchpotato/lib/rtorrent/`). The timeout matters: without it an http(s)
   endpoint that accepts the TCP connection but never responds (firewall
   black-hole, hung daemon) would block the calling thread forever
   (`getAllDownloadStatus()`/`download()` hang instead of failing over to
   their `except Exception` handler). `_RPC_TIMEOUT` is the single shared
   connect+read timeout used for both transports — the scgi
   `rtorrent_rpc.RTorrent(url, timeout=_RPC_TIMEOUT)` construction and this
   requests `session.post(..., timeout=_RPC_TIMEOUT)`.

   Because the POST uses `stream=True`, the read/parse is wrapped in
   `try/finally: response.close()` (VENDORED-04 cloud review round 2 —
   SHOULD-FIX): urllib3 only returns the connection to its pool once the
   response body is drained/closed, so a `response.close()` on **every** path
   (success, the non-200 `ProtocolError`, and a malformed-XML `p.feed` raise)
   is required — otherwise a persistently-bad endpoint (401/WAF loop) leaks a
   pooled connection on every `connect()`/status poll.

   A plain `xmlrpc.client.ServerProxy(url, transport=transport)` is then
   constructed and used exactly like `rtorrent_rpc`'s own `rt.rpc` — dotted
   calls (`.d`, `.f`, `.system`, ...) are ordinary `ServerProxy` behavior,
   nothing `rtorrent_rpc`-specific about them.

### `httprpc(+https)://` URL rewrite

CouchPotato's `host` config option accepts a CP-specific `httprpc://`
pseudo-scheme (ruTorrent's httprpc plugin), which `rtorrent_.py`'s existing
`connect()` already upgrades to `httprpc+https://` when SSL is enabled
(unchanged). A new `_rewrite_httprpc_url()` helper then rewrites this to the
plugin's fixed `action.php` mount point, **preserving host/port and any
existing path prefix** (e.g. a ruTorrent install mounted under `/rutorrent`):

```
httprpc://host           -> http://host/plugins/httprpc/action.php
httprpc://host/rutorrent -> http://host/rutorrent/plugins/httprpc/action.php
httprpc+https://host     -> https://host/plugins/httprpc/action.php
```

This exactly replicates the deleted vendored lib's
`Connection._transform_uri` (which joined the httprpc plugin's relative
path onto whatever path prefix was already present, rather than discarding
it) — necessary for the fairly common case of ruTorrent mounted under a
sub-path rather than the web server's root. The `rpc_url` config value
(default `RPC2`) is **not** appended in the httprpc case (it's only
meaningful for the plain http(s) scgi-pass-through case, where `rpc_url` is
literally the RPC mount path on an otherwise-generic web server / nginx scgi
proxy).

## Field parsing (`get_torrents()`)

`rpc.d.multicall2("", "main", "d.hash=", "d.name=", "d.complete=",
"d.is_open=", "d.ratio=", "d.state=", "d.left_bytes=", "d.down.rate=",
"d.directory=")` returns one tuple per torrent, positions matching the call
order. Each is turned into a lightweight `_RTorrentTorrent` object matching
exactly what `getAllDownloadStatus`/`getTorrentStatus` in `rtorrent_.py`
already read:

| Raw field | Conversion | Why |
|---|---|---|
| `d.hash` | `str(x).upper()` → `.info_hash` | matches CP's own upper-cased magnet/torrent hash computation, used for matching against `ids` |
| `d.complete` | `bool(int(x))` → `.complete` | raw value is `0`/`1` |
| `d.is_open` | `bool(int(x))` → `.open` | raw value is `0`/`1` |
| `d.ratio` | `int(x) / 1000.0` → `.ratio` | rTorrent reports ratio as a **per-mille integer** (e.g. `1500` for a 1.5 ratio); verified against the deleted vendored lib's `Method(Torrent, 'get_ratio', 'd.ratio', post_process_func=lambda x: x / 1000.0)`. Getting this wrong makes every displayed seed ratio 1000x too large. |
| `d.state`, `d.left_bytes`, `d.down.rate`, `d.directory`, `d.name` | pass through unchanged | `.state`/`.left_bytes`/`.down_rate`/`.directory`/`.name` |

Per-torrent operations are issued as separate on-demand `rpc.d.*`/`rpc.f.*`
calls keyed by `info_hash` (not batched into the multicall above, matching
the original task's operation split):

| CP call | RPC issued |
|---|---|
| `torrent.get_files()` | `rpc.f.multicall(info_hash, "", "f.path=")` → list of objects with `.path` |
| `torrent.set_custom(1, label)` | `rpc.d.custom1.set(info_hash, label)` (generic: `set_custom(key, value)` dispatches to `custom{key}.set`, but CP only ever uses slot 1) |
| `torrent.set_directory(dir)` | `rpc.d.directory.set(info_hash, dir)` |
| `torrent.start()` | `rpc.d.start(info_hash)` |
| `torrent.pause()` | `rpc.d.stop(info_hash)` — CP's "pause" maps to rTorrent's "stop" (confusing but unchanged, existing contract) |
| `torrent.resume()` | `rpc.d.start(info_hash)` |
| `torrent.erase()` | `rpc.d.erase(info_hash)` — does **not** touch the filesystem; CP's own `processComplete()` still does `os.unlink` first |
| `torrent.is_multi_file()` | `bool(int(rpc.d.is_multi_file(info_hash)))` — a fresh RPC call, deliberately not part of the multicall2 field list |

`rt.find_torrent(hash)` pulls `get_torrents()` and returns the
case-insensitive match, or `None`.

## Loading torrents

- **Magnet:** `rt.load_magnet(magnet_url, info_hash, verify_retries=10)` —
  issues `rpc.load.start("", magnet_url)` (the `""` first arg is rTorrent's
  required-but-unused target parameter), then polls `get_torrents()` (with a
  1-second `time.sleep` between attempts, skipping the sleep after the final
  attempt) until a torrent with matching `info_hash` appears **and its name
  has resolved away from the raw info-hash placeholder** (rTorrent reports a
  just-added magnet's name AS the info-hash until metadata is fetched from
  peers). This `require_name_resolved` wait mirrors the old vendored client's
  second poll loop — returning the placeholder early would hand CP a torrent
  whose name/files aren't yet meaningful. Returns the resolved torrent or
  `None`.
- **Torrent file:** `rt.load_torrent(filedata, info_hash, verify_retries=10)`
  — issues `rpc.load.raw("", xmlrpc.client.Binary(filedata))`, then the same
  poll loop **without** the name-resolution wait (a `.torrent` file's
  metadata is known immediately, so a name that happens to equal the hash is
  accepted right away).

**bencode bytes-key fix (VENDORED-04 review — BLOCKER):** `download()`'s
torrent-file branch computes the info-hash via
`sha1(bencode(bdecode(filedata)[b"info"]))`. The key MUST be the **bytes**
literal `b"info"`, not the string `"info"`: `bencodepy.decode()` (pinned
`bencodepy==0.9.5`) returns a dict with **bytes** keys, so `["info"]` raises
`KeyError` on every real `.torrent` file. This was dormant while the old
client crashed on connect; once rTorrent actually connects it is the next
thing every torrent-file add hits. The regression test
`test_download_torrent_file_loads_raw_and_sets_label` now uses a **real**
`bencodepy.encode`/`decode` round-trip (no mocking of `bdecode`/`bencode`)
and asserts the computed hash matches an independent computation — it fails
against `["info"]` and passes against `[b"info"]`.

**Deviation from the original task framing:** the deleted vendored lib's
`load_torrent` computed `info_hash` itself internally (via its own
`TorrentParser`, re-parsing the torrent's bencoded `info` dict), since the
call site never passed a hash. `rtorrent_.py`'s `download()` **already**
computes the exact same hash (via `bdecode`/`bencode`/`sha1`) *before*
calling `load_torrent`, purely to build the `torrent_hash` for
`downloadReturnId()`. Rather than duplicate that computation inside the new
adapter, `download()`'s call site was changed to pass the
already-computed `torrent_hash` straight into
`self.rt.load_torrent(filedata, torrent_hash, verify_retries=10)`. This is
strictly internal (the `_RTorrentAdapter`/`rTorrent.rt` boundary is private
to this module — nothing external observes its signature) and avoids a
redundant bencode round-trip. `download()`'s external behavior/API is
unchanged.

## Connectivity check

The old code did `self.rt.connection.verify()` (asserting on
`AssertionError`) — `rtorrent_rpc.RTorrent` has no such method, and
constructing an `xmlrpc.client.ServerProxy`/`_RTorrentAdapter` never
touches the network (XML-RPC proxies are lazy). `connect()` now calls
`self.rt.rpc.system.client_version()` immediately after construction — a
real RPC round-trip that fails loudly (any exception) if the endpoint isn't
a working rTorrent instance. `self.error_msg = str(e)` on failure (the old
code used `e.message`, a Python 2-only `Exception` attribute that never
existed in Python 3 — a latent bug fixed as a side effect here).

## Cross-platform notes

- scgi over TCP (`scgi://host:port`) and http(s) both work identically on
  Windows, macOS, and Linux (both are ordinary TCP sockets).
- scgi over a Unix domain socket (`scgi:///path/to/socket`) is
  **POSIX-only** — this is an unchanged limitation from the vendored lib,
  not a regression. A CouchPotato instance running on Windows cannot use a
  local Unix socket path (though it can still reach a remote scgi-TCP or
  http(s) endpoint from Windows).

## What `rtorrent_rpc`'s public surface couldn't express (beyond the
called-out auth/verify_ssl/connectivity-check gaps)

- No way to drive a `scgi:///path` Unix socket transport with per-call
  authentication (not relevant in practice, since raw SCGI has no auth
  concept at the protocol level regardless of client library).
- Its higher-level convenience methods (`add_torrent_by_file`,
  `stop_torrent`/`start_torrent`, tag/custom helpers) assume ruTorrent's
  "addtime"/tag encoding conventions and depend on `bencode2` — none of
  which map onto CP's plain hash-keyed `d.*`/`f.*` RPC usage, so they were
  not used at all; the adapter drives `.rpc` directly throughout. No other
  genuine expressiveness gap was found beyond the three already identified
  (per-instance auth, per-instance TLS verification/CA-bundle, and a real
  connectivity-verify call) — everything else CP needs is a one-to-one
  dotted RPC call, which both `rtorrent_rpc.RTorrent(...).rpc` and a
  hand-built `ServerProxy` support identically.

## Files changed

- `couchpotato/core/downloaders/rtorrent_.py` — replaced
  `from couchpotato.lib.rtorrent import RTorrent` and all vendored-lib usage
  with `_RTorrentAdapter`/`_RTorrentTorrent`/`_RTorrentFile`/
  `_RTorrentAuthTransport`/`_rewrite_httprpc_url` (all private to this
  module). `migrate()`, `settingsChanged()`, `test()`, `download()`,
  `getAllDownloadStatus()`, `pause()`, `removeFailed()`,
  `processComplete()`, `getTorrentStatus()`, and the `config` block keep
  the same external signatures/behavior — only their internals were
  rewired to the new adapter.
- `couchpotato/lib/rtorrent/` — deleted entirely (`git rm -r`).
- `requirements.txt` — added `rtorrent-rpc==0.9.7`.
- `couchpotato/lib/__init__.py` — untouched (its `sys.path` shim is still
  needed by the remaining vendored libs, e.g. `subliminal`).

## Tests added (`tests/unit/test_downloaders.py`)

Six new classes, all mocking at the `rpc` (XML-RPC proxy) boundary — no
real sockets, no real HTTP, no real rTorrent:

- `TestRTorrentAdapter` — `get_torrents()` field conversion (ratio ÷ 1000.0,
  bool coercion, hash upper-casing), the exact `d.multicall2` call issued,
  `find_torrent()` case-insensitive matching, `load_magnet()`/
  `load_torrent()` polling (found immediately / found after a couple of
  polls / never found → `None` without crashing, `time.sleep` mocked so
  tests don't actually sleep), **the magnet name-resolution wait
  (VENDORED-04 review): `load_magnet` skips a present-but-name-still-hash
  torrent and waits for the resolved name, returns `None` if the name never
  resolves, while `load_torrent` accepts a name-equals-hash torrent
  immediately**, and the unsupported-scheme `ValueError`.
- `TestRTorrentTorrentOperations` — `get_files()`, `set_custom(1, ...)` →
  `d.custom1.set`, `set_directory` → `d.directory.set`, `start`/`pause`/
  `resume` → `d.start`/`d.stop`/`d.start`, `erase()` → `d.erase` **and**
  asserts no filesystem call is made, `is_multi_file()` bool coercion.
- `TestRTorrentUrlRewrite` — the `httprpc://` and `httprpc+https://`
  rewrites (including the path-prefix-preserving case), and pass-through
  for non-httprpc schemes.
- `TestRTorrentAuthTransport` — digest vs. basic vs. no-auth session
  construction, `verify_ssl` (`True`/`False`/CA-bundle path) flowing through
  to `session.verify`, **and (VENDORED-04 review) `single_request()`'s full
  round-trip** (mocking `requests.Session.post`): a 200 XML-RPC body parsed
  correctly via getparser/Unmarshaller and returned, http-vs-https URL
  construction, **the `timeout=_RPC_TIMEOUT` kwarg passed to
  `session.post`** (VENDORED-04 cloud review — the thread-hang guard), a
  non-200 response raising `xmlrpc.client.ProtocolError` with the right
  host/handler/status, a 200 body carrying an XML-RPC `<fault>` still raising
  `xmlrpc.client.Fault`, and **`response.close()` called on both the success
  and the non-200 error path** (VENDORED-04 cloud review round 2 — the
  connection-leak guard).
- `TestRTorrentRpcSignatureGuard` (VENDORED-04 review) — a
  `pytest.importorskip('rtorrent_rpc')` guard asserting
  `inspect.signature(rtorrent_rpc.RTorrent.__init__)` still accepts the
  `(url, timeout=...)` call CP makes and that a constructed instance exposes
  `.rpc` — for **both** the scgi TCP form (`scgi://host:port`) **and the unix
  socket form (`scgi:///path.sock`)** (VENDORED-04 cloud review), so a future
  lib upgrade that drifts the constructor/`.rpc` surface or drops unix-socket
  support fails CI loudly (mirrors the putio/qbittorrent precedent).
- `TestRTorrentDownloaderConnect` — the `system.client_version()`
  connectivity check (success sets `self.rt`/clears `error_msg`; a raised
  exception sets `self.rt = None` and a non-empty `error_msg`), `test()`'s
  success/failure-tuple mapping, and the httprpc URL rewrite as observed
  through `connect()` (rpc_url not appended, path prefix preserved,
  ssl-enabled → https).
- `TestRTorrentDownload` — `download()`'s magnet and torrent-file paths:
  correct `load_magnet`/`load_torrent` args, label/`start()` applied to the
  returned torrent, and a falsy `load_magnet` result correctly propagating
  to `download()` returning `False`.
- `TestRTorrentDownloaderStatus` (VENDORED-04 cloud review round 2) — the
  integration seam where the downloader consumes adapter (`_RTorrentTorrent`)
  output, previously untested. Covers `getTorrentStatus` derivation
  (busy/seeding/completed), `getAllDownloadStatus` (full release-dict
  derivation, id filtering, relative-vs-absolute file-path joining, and the
  `timeleft` −1-vs-computed branch from `left_bytes`/`down_rate`),
  `pause()`/resume/missing-torrent, and `processComplete`/`removeFailed`
  (erase-without-delete, unlink-and-erase with delete, multi-file directory
  teardown, missing-torrent → `False`, and `removeFailed` delegating with
  `delete_files=True`). Uses a `_FakeTorrent` stub mirroring
  `_RTorrentTorrent`'s field/method surface so the assertions are on the real
  derived values, not tautologies.

## Acceptance criteria

- [x] `.venv/bin/python -m pytest tests/unit/ -q` green (978 passed after the
  VENDORED-04 cloud-review round 2 — count includes the putio/qbit/git
  vendored work merged into the branch from master).
- [x] `.venv/bin/ruff check .` clean.
- [x] No remaining references to `couchpotato.lib.rtorrent` /
  `lib.rtorrent` anywhere in the tree (only a comment in the new test file
  referencing the old path historically).
- [x] `couchpotato/lib/__init__.py`'s `sys.path` shim left intact.
