# VENDORED-01 — Remove dead vendored `caper` + unused TV-episode matcher module

## Problem

`couchpotato/lib/caper/` is a vendored TV-episode release-name parser (14
files, ~76K on disk; the task brief's "~172K/14 files" figure includes prior
git-history size, not the current working-tree size). Its only consumer is
`couchpotato/core/media/_base/matcher/` (3 files: `__init__.py`, `base.py`,
`main.py`), a plugin that:

- imports and wraps `Caper` (`from couchpotato.lib.caper import Caper`)
- registers events `matcher.parse`, `matcher.match`, `matcher.flatten_info`,
  `matcher.construct_from_raw`, `matcher.correct_title`,
  `matcher.correct_quality`, plus a `<media-type>.matcher.correct` hook via
  `MatcherBase.__init__`
- operates entirely on TV-episode concepts — `correctTitle()` reads
  `chain.info['show_name']`, and the parser chains are season/episode-based —
  even though this fork is **movies-only** (there is no TV media type
  registered anywhere in `couchpotato/core/media/`).

The real, live release-matching path is `Searcher.correctRelease()` /
`Searcher.correctName()` in `couchpotato/core/media/_base/searcher/main.py`
(exercised by `tests/unit/test_searcher_matching.py`), which never touches
`caper` or the `matcher` module. `guessit` (PyPI, already pinned in
`requirements.txt`) is the parser actually used at runtime, in
`couchpotato/core/plugins/scanner/folder_scanner.py`, and covers the one
theoretical name-parsing use case caper might have served.

## Evidence — zero live consumers

```
$ grep -rn "caper" couchpotato/ tests/ --include="*.py" | grep -v "couchpotato/lib/caper"
couchpotato/core/media/_base/matcher/main.py:5:from couchpotato.lib.caper import Caper
couchpotato/core/media/_base/matcher/main.py:15:        self.caper = Caper()
couchpotato/core/media/_base/matcher/main.py:27:        return self.caper.parse(name, parser)
```

Only the matcher module itself references caper. For each event the matcher
registers:

```
$ for ev in matcher.parse matcher.match matcher.flatten_info \
    matcher.construct_from_raw matcher.correct_title matcher.correct_quality; do
    grep -rn "$ev" couchpotato/ tests/ --include="*.py" \
      | grep -v couchpotato/core/media/_base/matcher/main.py
  done
# (no output for any of them — no external caller anywhere)
```

No subclass of `MatcherBase` exists anywhere (`grep -rn "MatcherBase"` only
matches its own definition and `Matcher(MatcherBase)`), so the
`<type>.matcher.correct` hook it half-wires up is also never fired by
anything. No import of `couchpotato.core.media._base.matcher` exists outside
the module's own `__init__.py`. `couchpotato/core/loader.py` autoloads
plugins purely by directory scan (`pkgutil.iter_modules`) — nothing hardcodes
a path to `matcher/`, so deleting the directory is sufficient; no loader
change is needed.

## What was deleted

- `couchpotato/lib/caper/` — entire directory (`__init__.py`, `constraint.py`,
  `group.py`, `helpers.py`, `logr_shim.py`, `matcher.py`, `objects.py`,
  `parsers/{__init__,anime,base,scene,usenet}.py`, `result.py`, `step.py` —
  14 files).
- `couchpotato/core/media/_base/matcher/` — entire directory (`__init__.py`,
  `base.py`, `main.py` — 3 files).

`couchpotato/lib/__init__.py` (the `sys.path` shim that lets vendored
libraries under `couchpotato/lib/` import as top-level packages, e.g.
`rtorrent`) was left untouched — it contains no caper-specific code and other
vendored libraries (`subliminal`, `rtorrent`, `xmpp`, `gntp`, `bencode`,
`oauth2`, `axl`, `CodernityDB`) still need it.

`docs/reference/LIBRARY_MIGRATION.md` updated: moved `libs/caper/` from
"Libraries Kept Vendored" to "Removed Vendored Libraries" with the rationale
above.

## Why `guessit` suffices

`guessit` is already a direct PyPI dependency (`requirements.txt`) and is
actively used in `couchpotato/core/plugins/scanner/folder_scanner.py` for the
one real name-parsing job this codebase does (extracting title/year/quality
tags from filenames during library scans). It was not modified by this
change. Caper's parsing was never wired into that path — it only fed the
dead `matcher` plugin's TV-episode logic — so there was no functional gap to
backfill.

## Test — boot/load verification

Extended `tests/unit/test_plugin_import_sweep.py` (the existing "app loads
all plugins without a silent import failure" test, added for REG-001) with
two new tests:

- `test_matcher_and_caper_are_gone` — asserts
  `couchpotato.core.media._base.matcher` and `couchpotato.lib.caper` both
  raise `ModuleNotFoundError` on import; asserts neither `pkgutil.walk_packages`
  over `couchpotato.core` nor the sweep-import pass yields any
  `matcher`-named module.
- `test_loader_discovers_media_base_siblings_without_matcher` — runs the real
  `Loader.preload()` (directory-scan discovery, `couchpotato.environment.Env`
  mocked the same way `tests/integration/test_plugin_loading.py` does) against
  the actual repo tree and asserts: `matcher` is absent from
  `loader.modules`; every real sibling under
  `couchpotato/core/media/_base/` (`library`, `media`, `providers`, `search`,
  `searcher`) is still discovered; and no `ERROR`-level log line mentions
  `matcher` or `caper` during discovery.

  Scope note (what this does and does not cover): `Loader.preload()` only
  walks the filesystem with `pkgutil.iter_modules` — it does **not** import
  any module (that happens later in `Loader.run()` -> `loadModule()`), so it
  cannot emit an ImportError or ERROR log for a dangling reference to the
  deleted code. This test therefore only proves the `matcher/` directory
  vanished from discovery cleanly and its siblings still appear — it does
  **not** catch a surviving sibling that still `import`s `matcher`/`caper`.
  The blanket "no core module silently imports the deleted code" guarantee is
  provided by the pre-existing `test_every_core_module_imports_cleanly`
  (REG-001) in the same file, which `importlib.import_module`s every module
  under `couchpotato.core` and `pytest.fail`s on any failure — that is the
  test that actually ties to the REG-001 bug class (`Loader.loadModule()`
  used to swallow `ImportError` at DEBUG).

While writing the second test, found and fixed a latent bug in the test
file's own `REPO_ROOT` constant: for a file under `tests/unit/`, it was
computed with one `dirname()` call too few (`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
resolves to `.../tests`, not the repo root). This was harmless for the
existing tests, which only use it to extend `sys.path` (the real repo root
is already provided by `tests/conftest.py`), but broke `Loader.preload()`,
which needs the actual on-disk path. Fixed by deriving the root from the
`couchpotato` package's own file location inside the new test rather than
reusing the module-level constant.

## Verification

```
$ .venv/bin/python -m pytest tests/unit/ -q
789 passed, 1 warning in ~12s

$ .venv/bin/ruff check .
All checks passed!
```

No `requirements.txt` change (caper was vendored, not a PyPI dependency;
`guessit` was already present and is unaffected). No E2E updates needed — no
UI/template surface changed.

## Files

- `couchpotato/lib/caper/` (deleted, 14 files)
- `couchpotato/core/media/_base/matcher/` (deleted, 3 files)
- `docs/reference/LIBRARY_MIGRATION.md` (moved caper's entry to "Removed")
- `tests/unit/test_plugin_import_sweep.py` (2 new tests)
