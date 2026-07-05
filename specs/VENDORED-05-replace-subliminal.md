# VENDORED-05: Replace vendored subliminal with modern subliminal + OpenSubtitles.com account

## Problem

`couchpotato/lib/subliminal` is a vendored copy of subliminal **0.6.2**, a
Py2-era library. On Python 3 it is effectively dead: `couchpotato/core/plugins/subtitle.py`
imports it (`from couchpotato.lib import subliminal`) and calls
`subliminal.download_subtitles(...)`, and `couchpotato/core/plugins/scanner/media_parser.py`
imports `couchpotato.lib.subliminal.videos.Video` to detect already-present
subtitle languages during scanning — but the vendored code no longer works
correctly under Python 3, so the subtitle feature silently does nothing.

Its provider set is also stale: several services (`thesubdb`, `subswiki`,
`subscenter`, `wizdom`) are dead sites, and `opensubtitles.org`'s legacy
XML-RPC API is being sunset in favor of `opensubtitles.com`'s REST API.

## Fix

Replace the vendored tree with the maintained **subliminal 2.6.0** from PyPI
(latest per `pip index versions subliminal` as of 2026-07-06), rewrite the two
call sites against its modern API, and add an optional OpenSubtitles.com
account (username/password) settings field wired into the provider config.

### API delta summary (old vendored 0.6.2 -> modern 2.6.0)

| Old (vendored) | New (subliminal 2.6.0) |
|---|---|
| `subliminal.download_subtitles(files, multi=True, force=..., languages=[...], services=[...], cache_dir=...)` | `subliminal.download_best_subtitles({video}, {Language, ...}, providers=[...], provider_configs={...})` then `subliminal.save_subtitles(video, subtitles)` |
| Language as bare 2-letter strings | `babelfish.Language.fromalpha2('en')` objects |
| `services` (thesubdb, subswiki, subscenter, wizdom, opensubtitles) | `providers` (stevedore-plugin names): default set is `['opensubtitlescom', 'podnapisi', 'opensubtitles']` |
| Implicit/no cache config | `subliminal.region.configure('dogpile.cache.dbm', arguments={'filename': ...})`, guarded by `region.is_configured` (idempotent across plugin reloads; `RegionAlreadyConfigured` otherwise) |
| `couchpotato.lib.subliminal.videos.Video.from_path(path).scan()` (embedded + external subtitle language detection) | `subliminal.scan_video(path)` / `subliminal.Video.fromname(basename)` to build a `Video`; `subliminal.core.search_external_subtitles(path)` for sidecar-file language detection (embedded-track detection dropped — see Scope note below) |
| `d_sub.path`, `d_sub.language.alpha2` | `subtitle.get_path(video)`, `subtitle.language.alpha2` |

**Scope note:** the old vendored `Video.scan()` detected both external
(sidecar) *and* embedded (in-container) subtitle tracks. The rewrite only
detects external sidecar files via `search_external_subtitles` (filename-suffix
matching, e.g. `movie.en.srt` -> `en`), because embedded-track detection in
modern subliminal goes through `subliminal.refine()` + `knowit`, which needs a
metadata backend (mediainfo/ffmpeg/mkvmerge) to actually extract anything. Not
requiring a native library just to *scan* a group keeps the feature
dependency-light and crash-proof; this can be added later as a
`refine()`-based enhancement if wanted.

## New dependencies (added to `requirements.txt`)

All verified via `pip index versions <pkg>` before pinning (installed and
confirmed to import cleanly in `.venv`, `pip check` clean):

| Package | Version | Wheel coverage | Notes |
|---|---|---|---|
| subliminal | 2.6.0 | `py3-none-any` | pure Python |
| babelfish | 0.6.1 | `py3-none-any` | pure Python; language objects |
| dogpile.cache | 1.5.0 | `py3-none-any` | pure Python; cache backend (dbm) |
| stevedore | 5.9.0 | `py3-none-any` | pure Python; provider plugin loading |
| pysubs2 | 1.8.1 | `py3-none-any` | pure Python; subtitle format conversion |
| **pymediainfo** | **7.0.1** | macOS/Windows/**manylinux** wheels bundle a native `libmediainfo`; **no musllinux wheel** | See "libmediainfo degradation" below |
| knowit | 0.5.11 | `py3-none-any` | pure Python; metadata backend dispatcher (mediainfo/ffmpeg/mkvmerge/enzyme) |
| rebulk | 3.2.0 | `py3-none-any` | pure Python; guessit's rule engine (guessit already pinned at 3.8.0, unchanged) |
| srt | 3.5.3 | **sdist only, no prebuilt wheel** | pure Python (no C extension) — builds instantly on any platform including musllinux, no compiler needed |
| tomlkit | 0.15.0 | `py3-none-any` | pure Python |
| click-option-group | 0.5.9 | `py3-none-any` | pure Python |
| defusedxml | 0.7.1 | `py2.py3-none-any` | pure Python |
| trakit | 0.2.5 | `py3-none-any` | pure Python |
| decorator | 5.3.1 | `py3-none-any` | pure Python |

`enzyme==0.5.2` and `guessit==3.8.0` were already pinned in `requirements.txt`
(pre-existing CouchPotato deps, reused by knowit/subliminal — no version bump
needed). `pip check` is clean with the full set installed.

### libmediainfo degradation (the one dep needing a native lib)

`pymediainfo` is a pure-Python ctypes wrapper (confirmed via its sdist:
`pdm-backend`, no compiled extension). Its macOS/Windows/manylinux wheels
*bundle* a prebuilt `libmediainfo`; there is no musllinux wheel, so on Alpine
pip falls back to the sdist, which has no bundled native library. Either way,
`pymediainfo.MediaInfo.can_parse()` wraps the native-library lookup in a bare
`try/except` and returns `False` if it can't find one — it never raises on
import or on a missing library. `knowit`'s `refine()` path (used only for the
richer metadata refiner, which this plugin does not call) logs a warning and
tries the next backend when a configured one isn't available.

Critically, **CP's rewritten `Subtitle.scanVideo()` never calls `refine()`/knowit
at all** — it only uses `subliminal.scan_video()` (guessit + file size, no
native library involved) with a `Video.fromname()` fallback for anything that
makes even that fail. So the search-and-download feature works identically
with or without libmediainfo; the library only matters if a future enhancement
adds `refine()`-based embedded-subtitle/metadata detection.

The Dockerfile **already** runs `apk add --no-cache ... mediainfo libstdc++`
in the runtime stage (pre-existing, see `Dockerfile` line ~48-52) — Alpine
users get full `libmediainfo` for free with no changes needed here.

## OpenSubtitles.com account field

Added to `couchpotato/core/plugins/subtitle.py`'s `config`:
- `opensubtitles_com_user` (optional, advanced)
- `opensubtitles_com_password` (optional, advanced, `type: password`)

`Subtitle.getProviderConfigs()` wires both into
`provider_configs={'opensubtitlescom': {'username': ..., 'password': ...}}`
only when **both** are set; otherwise `opensubtitlescom` is omitted from
`provider_configs` and runs anonymously (subliminal ships a default public API
key for `opensubtitlescom`, so anonymous search/download already works —
credentials just raise the quota). Settings description documents that the
legacy opensubtitles.org XML-RPC API is deprecated in favor of this REST API.

## Graceful degradation / crash safety

- `Subtitle.scanVideo()`: `scan_video()` -> on any exception, falls back to
  `Video.fromname(basename)` -> on any exception, logs and returns `None`
  (caller skips that file).
- `Subtitle.searchSingle()`: download failures, save failures, and any
  unexpected exception are all caught, logged, and the loop continues to the
  next file / returns cleanly rather than propagating into the renamer.
- `Subtitle.configureCache()`: guarded by `subliminal.region.is_configured` so
  repeated plugin construction (module reload) never hits
  `RegionAlreadyConfigured`; any configure failure (e.g. unwritable cache dir)
  is caught and logged, not raised.
- `MediaParserMixin.getSubtitleLanguage()`: `search_external_subtitles` import
  is wrapped in `try/except ImportError` (mirrors the old `Video` guard) and
  the scan itself stays inside the existing outer `try/except`.

## Files changed

- `couchpotato/core/plugins/subtitle.py` — rewritten against subliminal 2.x;
  added OpenSubtitles.com settings + provider_configs wiring; cache region
  configuration.
- `couchpotato/core/plugins/scanner/media_parser.py` — `getSubtitleLanguage()`
  rewritten to use `subliminal.core.search_external_subtitles` instead of the
  vendored `Video.from_path().scan()`.
- `requirements.txt` — added the 14 new pins listed above.
- `couchpotato/lib/subliminal/` — **deleted** (vendored tree fully removed;
  `libs/` sys.path shim for other vendored libs is untouched).
- `tests/unit/test_subtitle_plugin.py` — new: language-object building,
  provider-config wiring (OS.com creds present/absent), `scanVideo` fallback
  chain, `searchSingle` (download/save success, already-available-language
  skip, `force` override, download/save failure degradation, unscannable-file
  skip, unexpected-exception handling), `configureCache` idempotency, and a
  subliminal 2.x signature-drift guard (`download_best_subtitles`,
  `save_subtitles`, `scan_video`, `region.configure`/`is_configured`,
  `Video.fromname`, `search_external_subtitles`).
- `tests/unit/test_scanner_modules.py` — new `TestGetSubtitleLanguage` class:
  sidecar-subtitle detection (single/multiple languages), no-sidecar case,
  DVD-group skip, and missing-subliminal degradation.

## Acceptance criteria

- [x] `couchpotato/lib/subliminal/` deleted; no remaining `lib.subliminal` /
      `from couchpotato.lib import subliminal` references.
- [x] `subtitle.py` and `media_parser.py` import cleanly with `libs/` on
      `sys.path` (as `CouchPotato.py` sets it) — verified directly and via
      `tests/unit/test_plugin_import_sweep.py`.
- [x] Subtitle search/download preserves prior public behavior: configured
      languages, skip languages already present (unless `force`), save next
      to the video file, update `group['files']['subtitle']`,
      `group['before_rename']`, `group['subtitle_language']`.
- [x] OpenSubtitles.com username/password optional settings field added and
      wired into `provider_configs`; omitted (anonymous) when unset.
- [x] All new/changed code degrades gracefully (logs, doesn't crash) on
      provider failure, save failure, unscannable file, and missing
      libmediainfo.
- [x] `pytest tests/unit/ -q` — 902 passed.
- [x] `ruff check .` — clean.
