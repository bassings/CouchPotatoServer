# FIX — bencode bytes-key bug in uTorrent/Deluge/Hadouken torrent-file adds

## Problem

`bencodepy.decode()` (imported as `bdecode`) returns a dict keyed by **bytes**
(`b'info'`, `b'announce'`, ...), never by `str`. Three downloaders still
looked up the decoded `info` dict with a **string** key, which raises
`KeyError` on every real `.torrent` file:

- `couchpotato/core/downloaders/utorrent.py:91` — `bdecode(filedata)['info']`
- `couchpotato/core/downloaders/deluge.py:323` — `bdecode(torrent)["info"]`
  (inside `DelugeRPC._check_torrent()`)
- `couchpotato/core/downloaders/hadouken.py:103` — `bdecode(filedata)['info']`

Magnet-link adds are unaffected — that branch never calls `bdecode()`, it
extracts the info-hash from the magnet URI's `urn:btih:` instead. Only
**torrent-FILE** adds (searcher-downloaded `.torrent` files handed to
`download(..., filedata=...)`) hit this path, so the failure only shows up
for trackers/providers that return actual torrent files rather than magnet
links.

This is the same class of bug already fixed for qBittorrent
(`couchpotato/core/downloaders/qbittorrent_.py`) and rTorrent
(`couchpotato/core/downloaders/rtorrent_.py`), both of which already use
`bdecode(...)[b"info"]`.

## Fix

Change the string-key lookup to the bytes key in all three files:

```python
info = bdecode(filedata)[b'info']   # utorrent.py, hadouken.py
info = bdecode(torrent)[b"info"]    # deluge.py (DelugeRPC._check_torrent)
```

`sha1(bencode(info)).hexdigest()` re-encodes the bytes-keyed `info` dict
correctly — bencode's canonical key-sort ordering is defined on the raw key
bytes, so re-bencoding a bytes-keyed dict produces the identical byte
sequence (and therefore identical info-hash) that a `str`-keyed encode would
if `dict['info']` had ever actually worked. No other string-key access on a
`bdecode()` result exists in any of the three files — each only does the one
`['info']`/`["info"]` lookup before re-bencoding.

### Error-handling: follow-up — now guarded to match qBittorrent

The initial version of this fix left the `bdecode()` call unguarded in all
three files (see history below). A follow-up round of review asked for
consistency with qBittorrent's handling
(`couchpotato/core/downloaders/qbittorrent_.py:173-182`), which wraps its
`bdecode(filedata)[b"info"]` + `sha1(bencode(info))` computation in
`try/except (BencodeDecodingError, KeyError, ValueError, TypeError) as e:` and
turns a corrupt/malformed `.torrent` into a specific logged error
(`'Invalid/corrupt torrent file, cannot add to qBittorrent: %s'`) plus a clean
`False` return, instead of letting the exception escape to `fireEvent`'s
blanket handler. All three files now adopt the identical pattern, importing
the same `from bencodepy.exceptions import DecodingError as
BencodeDecodingError`:

- **utorrent.py** (`download()`) and **hadouken.py** (`download()`): the
  decode + info-hash computation is wrapped in the same
  `try/except (BencodeDecodingError, KeyError, ValueError, TypeError)`,
  logging `'Invalid/corrupt torrent file, cannot add to uTorrent/Hadouken:
  %s'` and returning `False` — the add-file RPC (`add_torrent_file`/
  `add_file`) is never reached on corrupt input.
- **deluge.py** (`DelugeRPC._check_torrent()`): also wrapped with the same
  exception tuple, logging `'Invalid/corrupt torrent file, cannot check with
  Deluge: %s'` and returning `False`. This is belt-and-braces: the callers
  (`add_torrent_file()`/`add_torrent_magnet()`) already wrap the whole body in
  a broad `try/except Exception as err: log.error(...)`, so a decode failure
  was already caught before this change — but it produced a generic traceback
  log rather than a specific, actionable one. With the guard inside
  `_check_torrent()`, corrupt input never reaches the outer handler at all:
  `_check_torrent()` returns `False` cleanly, which the caller assigns to
  `torrent_id`/`remote_torrent` and folds into its existing
  "falsy → log + return False" path, so no caller behaviour changes.

## Tests (TDD)

Added to `tests/unit/test_downloaders.py`. None of the new tests mock
`bdecode`/`bencode` — a string-keyed mock return value is exactly the
false-confidence pattern that hid this bug in the first place. Each test
builds a real torrent dict, `bencodepy.encode()`s it to bytes, feeds that as
`filedata`/`torrent`, and asserts against an independently-computed
`sha1(bencode(bdecode(...)[b'info'])).hexdigest()`.

- `TestUTorrentDownloadFile`
  - `test_download_file_computes_info_hash_and_adds_file` — torrent-FILE add:
    asserts `uTorrentAPI.add_torrent_file` is called with the raw filedata and
    `set_torrent` with the correct upper-hex info-hash.
  - `test_download_magnet_does_not_touch_bencode` — magnet path untouched by
    the fix (no bdecode involved, hash comes straight from the magnet URI).
- `TestDelugeCheckTorrent`
  - `test_check_torrent_file_computes_info_hash_when_known_to_deluge` —
    `DelugeRPC._check_torrent()` in isolation, the exact call site of the bug.
  - `test_check_torrent_file_returns_false_when_not_found` — unknown-hash
    branch still returns `False`.
  - `test_add_torrent_file_falls_back_to_check_torrent_when_id_missing` —
    exercises the **production call path**: `add_torrent_file()` falling back
    to `_check_torrent()` when Deluge's RPC returns no id.
- `TestHadoukenDownloadFile`
  - `test_download_file_computes_info_hash_and_adds_file` — torrent-FILE add:
    asserts `HadoukenAPI.add_file` is called with the raw filedata and the
    correct upper-hex info-hash.
  - `test_download_magnet_does_not_touch_bencode` — magnet path untouched.

Each of the five file-add tests fails with `KeyError: 'info'` (or, for the
Deluge fallback test, an assertion mismatch caused by the swallowed
`KeyError`) against the pre-fix `['info']`/`["info"]` code, and passes once
the lookup uses `[b'info']`/`[b"info"]`.

### Follow-up: corrupt-input guard tests

Added per downloader, feeding intentionally-corrupt bytes as
`filedata`/`torrent` (`b'garbage'` — invalid bencoding, raises
`BencodeDecodingError`; `b'i5e'` — valid bencode integer, decodes to a
non-subscriptable tuple, raises `TypeError` on `[b'info']`). Each asserts the
graceful-failure return (`False`), that the client's add method was **not**
called, and that a single specific `log.error` call was made containing
`'Invalid/corrupt torrent file'`. Every one of these new tests fails against
the pre-guard code (the exception escapes `download()`/`_check_torrent()`
uncaught) and passes once the guard is in place.

- `TestUTorrentDownloadFile::test_download_corrupt_torrent_file_returns_false_without_raising`
  (parametrized `invalid-bencoding` / `non-dict-bencode`)
- `TestDelugeCheckTorrent::test_check_torrent_file_corrupt_returns_false_with_specific_error`
  (parametrized, exercises `_check_torrent()` directly)
- `TestDelugeCheckTorrent::test_add_torrent_file_returns_false_on_corrupt_torrent_without_raising`
  (exercises the production `add_torrent_file()` entry point, confirming only
  the specific message is logged — not a second generic traceback from the
  outer `except Exception`)
- `TestHadoukenDownloadFile::test_download_corrupt_torrent_file_returns_false_without_raising`
  (parametrized `invalid-bencoding` / `non-dict-bencode`)

## Acceptance Criteria

- [x] All three sites use the bytes key `[b'info']` / `[b"info"]`.
- [x] No other string-key access on a `bdecode()` result remains in any of
      the three files.
- [x] New tests fail against the pre-fix code (`KeyError`) and pass post-fix.
- [x] `pytest tests/unit/ -q` fully green (1031 passed).
- [x] `ruff check .` clean.
- [x] `utorrent.py`, `deluge.py`, `hadouken.py` all import cleanly.
- [x] CodernityDB untouched.
- [x] Corrupt/malformed torrent input in `utorrent.py`, `deluge.py`, and
      `hadouken.py` is now guarded identically to
      `qbittorrent_.py` (`try/except (BencodeDecodingError, KeyError,
      ValueError, TypeError)`, specific log message, clean `False`/falsy
      return, no exception escapes).
