# VENDORED-07 — Replace vendored `unrar2` with `rarfile` + graceful degradation

## Problem

`couchpotato/lib/unrar2` is a vendored, Python-2-era fork of Jimmy
Retzlaff/Konstantin Yegupov's `UnRAR2` bindings. It ships three committed
binaries directly in the repo:

- `couchpotato/lib/unrar2/unrar` (macOS executable, 234,984 bytes)
- `couchpotato/lib/unrar2/unrar.dll` (Windows 32-bit DLL, 165,376 bytes)
- `couchpotato/lib/unrar2/unrar64.dll` (Windows 64-bit DLL, 191,488 bytes)

plus `unix.py` / `windows.py` / `rar_exceptions.py` / `__init__.py`, which
shell out to a bundled or system `unrar` binary via `ctypes`/ `subprocess`.
This is effectively dead on Python 3 (untested, unmaintained, and the
platform-detection/`ctypes` bindings target Python 2 idioms), and shipping
prebuilt binaries in source control is both a supply-chain and Trivy/CodeQL
concern.

The sole consumer was `ExtractorMixin.extractFiles` in
`couchpotato/core/plugins/renamer/extractor.py` (~25 lines): given a `.rar`
archive it opened it with `unrar2.RarFile(path, custom_path=unrar_path)` and
iterated `.infolist()` to extract each entry to the target folder, flattened
to its basename.

RAR is a proprietary format — there is no pure-Python decoder — so any
replacement still needs an external extractor binary for the actual
decompression step. CouchPotato must keep running via a bare
`python CouchPotato.py` on Windows/macOS/Linux, not only inside the Docker
image, so we cannot assume a tool is present.

## Chosen replacement

**`rarfile` (PyPI), pinned at `4.2`** (latest at time of writing, confirmed via
`pip index versions rarfile`).

- **License:** ISC (permissive, GPL-3 compatible).
- Pure-Python for archive **listing** (`RarFile()` / `.infolist()` parse the
  RAR header format directly, no external tool needed).
- **Extraction** (`.open()` / `.extract()`) shells out to whichever of
  `unrar`, `unar`, `7z`/`7zz`, or `bsdtar` it finds on `PATH` (`rarfile`'s own
  `tool_setup()` auto-detection, tried in that order) — configurable via the
  module-level `rarfile.UNRAR_TOOL` for a custom path.
- Actively maintained, widely used (Sonarr/Radarr-adjacent ecosystem), no
  compiled extension (no musllinux/cross-arch build concern).

## Graceful degradation (product decision)

RAR-extraction is **not a hard dependency**. When no extractor tool is
available on the host:

- `rarfile.RarFile.open()`/`.extract()` raises `rarfile.RarCannotExec`.
- `ExtractorMixin.extractFiles` catches this and logs a single
  `log.warning(...)` **once per scan** (guarded by the `self._warned_no_tool`
  instance attribute that `Renamer.scan()` resets at the start of each scan —
  shared across the per-group `extractFiles` calls, not a call-local flag, and
  not a process-lifetime flag) naming the missing tool and giving per-OS
  install hints (`NO_EXTRACTOR_TOOL_MESSAGE` in `extractor.py`).
- The archive is **skipped, not failed**: it is not tagged as `extracted`,
  its constituent files are left on disk untouched, and it will simply be
  picked up again on the next scan once a tool becomes available. This
  matches the existing "files too new, ignoring for now" pattern already
  used elsewhere in `extractFiles`.
- Other `rarfile.Error` subclasses (`BadRarFile`, `NotRarFile`, wrong
  password, etc.) are caught per-archive, logged at `error` level, and that
  one archive is skipped — the scan continues with the remaining archives.
- In effect, the RAR-extraction feature (`unrar` setting, default `False`
  already) defaults to a no-op until an extractor tool is installed.

## Implementation

`couchpotato/core/plugins/renamer/extractor.py`:

- New `ExtractorMixin.extractArchive(rar_path, extr_path,
  custom_tool_path=None)`: opens the archive with `rarfile.RarFile`, iterates
  `.infolist()`, skips directories (`info.isdir()`), and for each file streams
  it via `rar_handle.open(info)` to `open(dest, 'wb')` in 1 MiB chunks —
  unless a file already exists at the flattened destination, in which case
  the re-write I/O is skipped. Returns **all** target files present at the
  destination after the call (newly written OR already present), so the list
  is empty only for a genuinely empty/all-directory archive. This is
  deliberate for idempotency: if a crash/restart lands between writing the
  files and persisting the `extracted` tag, the next scan finds every target
  already on disk; returning them (not `[]`) lets `extractFiles` still tag and
  clean up the release instead of retrying it forever. Raises `rarfile.Error`
  subclasses (including `RarCannotExec`) to the caller rather than swallowing
  them, so `extractFiles` can apply the shared warn-once-and-skip /
  log-and-skip policy above (on those failures it returns nothing/raises, so
  the archive is skipped without tagging).
- `extractFiles` now calls `self.extractArchive(...)` instead of the old
  `unrar2.RarFile(...)` + manual `.extract()` loop; the surrounding
  archive-discovery, `.partNN.rar` handling, date-check, and leftover-file
  move logic is unchanged.
- `unrar_modify_date` (existing setting) applies `os.utime` per extracted
  file. In the old code `os.utime` was already inside the per-file loop, so
  that part was correct; the new code iterates the returned `extracted` list
  instead.
- Latent bug fixed in the release-**tagging** logic: the old code decided
  whether to tag the release as `extracted` by testing the loop variable
  `extr_file_path` *after* the `for` loop finished — so it keyed off whatever
  the last-iterated entry happened to be (which could be a directory or a
  skipped/already-existing file), meaning tagging could silently not fire for
  a genuinely-extracted release (or the variable could be undefined for an
  empty archive). The new code tags based on the non-empty `extracted` list
  returned by `extractArchive`, so tagging fires exactly when at least one
  file was actually extracted.
- The "no extractor tool" warning is scoped to the whole scan, not to a
  single `extractFiles` call: `Renamer.scan()` resets `self._warned_no_tool
  = False` at the start of every scan, and `extractFiles` reads/sets that
  shared instance attribute. Because `scan()` calls `extractFiles` once per
  movie group (via `_processGroup`), a call-local flag would emit one warning
  per group; the instance-scoped flag collapses them to one per scan.
- If `unrar_path` (existing "Custom path to unrar bin" setting) is set, it
  is applied via `rarfile.UNRAR_TOOL = custom_tool_path` followed by
  `rarfile.tool_setup(force=True)` to force `rarfile` to re-probe using that
  path first. When the setting is later cleared, `extractArchive` restores
  `rarfile.UNRAR_TOOL` to its captured default (`DEFAULT_UNRAR_TOOL`) and
  re-probes, so auto-detection is not left pinned to the stale custom path
  (`rarfile.UNRAR_TOOL` is a module global).

## Binaries deleted

`git rm -r couchpotato/lib/unrar2`, removing:

- `couchpotato/lib/unrar2/unrar` (macOS binary)
- `couchpotato/lib/unrar2/unrar.dll` (Windows 32-bit)
- `couchpotato/lib/unrar2/unrar64.dll` (Windows 64-bit)
- `couchpotato/lib/unrar2/__init__.py`, `unix.py`, `windows.py`,
  `rar_exceptions.py`

`couchpotato/lib/__init__.py` (the shared vendored-libs `sys.path` shim) is
kept — other vendored libraries (`rtorrent`, `subliminal`, `caper`'s
successor, etc.) still rely on it.

## Dockerfile

Added `7zip` to the runtime-stage `apk add` line in `Dockerfile` — Alpine's
`7zip` package provides `7zz`, one of `rarfile`'s auto-detected tools — so
the official container image can extract RAR archives out of the box with
no additional user setup, same as before (the old vendored binary only
covered macOS/Windows; Docker/Linux previously had no bundled extractor at
all, so this is a net new capability there, not a regression).

## Per-OS setup docs

The `unrar` and `unrar_path` settings descriptions in
`couchpotato/core/plugins/renamer/api.py` now document how to obtain a tool:

- **Windows:** install UnRAR.exe or 7-Zip and add it to `PATH`.
- **macOS:** `brew install unar` (or `brew install rar`).
- **Linux:** install the distro's `unrar` or `unar` package.
- **Alpine/Docker:** `apk add 7zip` (already included in the official
  image).

The same per-OS guidance is embedded in `NO_EXTRACTOR_TOOL_MESSAGE`, the
warning logged at runtime when no tool is found.

## Tests

`tests/unit/test_extractor.py` (new), TDD against a mocked `rarfile.RarFile`
(no extractor tool is installed in the dev/CI sandbox, so a real `.rar`
fixture can't be produced without one — mocking the library boundary is the
practical alternative):

- `TestExtractArchive`: successful extraction flattens nested paths to
  basename, skips directory entries, does **not** re-write files that already
  exist at the destination but still reports their paths, propagates
  `rarfile.RarCannotExec` (raised from `open()`, the real seam) and
  `rarfile.BadRarFile` to the caller, and applies/clears a custom tool path
  via `rarfile.UNRAR_TOOL` + `tool_setup(force=True)`.
- `TestExtractFilesGracefulDegradation`: end-to-end through
  `ExtractorMixin.extractFiles` with a minimal fake Renamer double —
  confirms exactly **one** warning is logged across two archives when no
  tool is available, that the release is **not tagged**, and that a
  `BadRarFile` on a single archive logs an error and is skipped without
  raising.
- `TestExtractFilesAlreadyExtractedIdempotency`: an archive whose target
  files are all already on disk (crash-between-write-and-tag) is still
  tagged `extracted` (cleanup=False) and its source archive still cleaned up
  (cleanup=True) — i.e. the release is not stuck retrying forever — while the
  existing files are not re-written.
- `TestScanScopedWarning`: the no-tool warning is emitted once per whole
  `scan()` across multiple groups, and re-armed on the next scan.
- `TestNoExtractorToolMessage`: the warning text names every supported tool
  (including `bsdtar`) and gives install hints for all four OS families.

## Acceptance criteria

- [x] `rarfile==4.2` pinned in `requirements.txt`, importable in the shared
      `.venv`.
- [x] `couchpotato/lib/unrar2/` (all 7 files, including the 3 binaries)
      deleted via `git rm`.
- [x] `Dockerfile` runtime stage installs `7zip`.
- [x] `ExtractorMixin.extractArchive` extracts via `rarfile`, flattening to
      basename and skipping already-extracted files.
- [x] Missing extractor tool: exactly one warning per scan, archive
      skipped, release not tagged/failed.
- [x] Other archive errors (`BadRarFile`, etc.): logged per-archive, that
      archive skipped, scan continues.
- [x] Per-OS install instructions present in both the settings description
      and the runtime warning message.
- [x] `tests/unit/test_extractor.py` covers success, no-tool degradation,
      and bad-archive skip.
- [x] `pytest tests/unit/ -q` green (860 passed), `ruff check .` clean.
- [x] `couchpotato.core.plugins.renamer.extractor` and
      `couchpotato.core.plugins.renamer.main` (`Renamer`) import cleanly.

## Files

- `couchpotato/core/plugins/renamer/extractor.py` (rewritten)
- `couchpotato/core/plugins/renamer/api.py` (settings descriptions updated)
- `requirements.txt` (`rarfile==4.2` added)
- `Dockerfile` (`7zip` added to runtime `apk add`)
- `couchpotato/lib/unrar2/` (deleted: `__init__.py`, `unix.py`, `windows.py`,
  `rar_exceptions.py`, `unrar`, `unrar.dll`, `unrar64.dll`)
- `tests/unit/test_extractor.py` (new)
