"""REG-001: sweep-import every module under couchpotato.core.

PR #148 removed `from couchpotato.core.event import fireEvent` from
`couchpotato/__init__.py`. Nine plugin modules imported it via the package
root (`from couchpotato import fireEvent`), and `Loader.loadModule()` (see
`couchpotato/core/loader.py`) swallows `ImportError` at DEBUG level, so those
plugins vanished silently instead of failing loudly anywhere CI would notice.

This test walks every module reachable under `couchpotato.core` and imports
it directly (bypassing the Loader's error-swallowing), so a broken import
shows up as a hard test failure rather than a quiet DEBUG log line.
"""
import importlib
import logging
import os
import pkgutil
import sys
import traceback

import pytest

# Mirror CouchPotato.py's sys.path setup (libs/ holds vendored deps such as
# CodernityDB) so `import couchpotato` and everything under it resolves the
# same way it does at runtime. tests/conftest.py already does this for the
# whole suite, but keep this local and explicit in case the test is ever run
# in isolation (e.g. `pytest tests/unit/test_plugin_import_sweep.py`).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (REPO_ROOT, os.path.join(REPO_ROOT, 'libs')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import couchpotato.core  # noqa: E402


def _sweep_import_failures():
    """Import every module under couchpotato.core, returning {name: traceback}."""
    failures = {}

    def onerror(name):
        # Raised while walk_packages itself tries to import a *package* to
        # recurse into it (e.g. a broken __init__.py in a subpackage).
        failures[name] = traceback.format_exc()

    for _finder, name, _ispkg in pkgutil.walk_packages(
        couchpotato.core.__path__, prefix='couchpotato.core.', onerror=onerror
    ):
        if name in failures:
            continue
        try:
            importlib.import_module(name)
        except Exception:
            failures[name] = traceback.format_exc()

    return failures


def test_every_core_module_imports_cleanly():
    """No module under couchpotato.core should fail to import.

    Regression guard for REG-001: PR #148 silently dropped nine plugins
    (imdb, bluray, tmdb_charts, popularmovies, yifypopular, trakt automation,
    filmweb, reddit, rottentomatoes) because they imported `fireEvent` via
    `from couchpotato import fireEvent`, which broke when the re-export was
    removed from `couchpotato/__init__.py`, and the Loader only logs
    ImportError at DEBUG.
    """
    failures = _sweep_import_failures()

    if failures:
        details = '\n'.join(
            f'--- {name} ---\n{tb}' for name, tb in sorted(failures.items())
        )
        pytest.fail(
            f'{len(failures)} module(s) under couchpotato.core failed to import:\n{details}'
        )


def test_loader_logs_import_error_at_error_level(caplog):
    """A plugin module that fails to import must be logged loudly.

    Before REG-001, `Loader.loadModule()` caught ImportError/SyntaxError and
    logged it at DEBUG (couchpotato/core/loader.py), which is exactly why the
    nine broken plugins never showed up anywhere: DEBUG isn't even enabled by
    default in production. loadModule() must still swallow the error (one bad
    plugin shouldn't abort the rest) but it must log at ERROR with the
    traceback so it's actually visible.
    """
    from couchpotato.core.loader import Loader

    loader = Loader()

    with caplog.at_level(logging.DEBUG):
        result = loader.loadModule('couchpotato_reg001_test_nonexistent_module')

    # Still returns None so the caller (Loader.run) can skip this one plugin
    # and keep loading everything else.
    assert result is None

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, (
        'Expected an ERROR-level log record for the failed import, got: '
        f'{[(r.levelname, r.message) for r in caplog.records]}'
    )
    assert any('couchpotato_reg001_test_nonexistent_module' in r.message for r in error_records)


def test_matcher_and_caper_are_gone():
    """VENDORED-01: the dead TV-episode `matcher` plugin and vendored `caper`.

    `couchpotato/core/media/_base/matcher/` wrapped the vendored
    `couchpotato/lib/caper` parser and registered `matcher.parse`,
    `matcher.match`, `matcher.flatten_info`, `matcher.construct_from_raw`,
    `matcher.correct_title` and `matcher.correct_quality` events plus a
    `<type>.matcher.correct` hook via `MatcherBase`. Its own code operated on
    `show_name`/season/episode chains (TV terms) even though this fork is
    movies-only, and nothing else in the codebase ever fired any `matcher.*`
    event or subclassed `MatcherBase` — the real release-matching path is
    `searcher.correct_release` in `couchpotato/core/media/movie/searcher.py`,
    which never touches caper. Both were removed (VENDORED-01).

    Scope of this test: it guarantees the exact `matcher`/`caper` module
    PATHS are gone and do not reappear — importing either raises
    `ModuleNotFoundError`, and neither a `pkgutil.walk_packages` scan of
    `couchpotato.core` nor the import sweep surfaces any `matcher`-named
    module. It does NOT prove that no surviving sibling still *references*
    the deleted code (a stray `from ...matcher... import ...` in another
    module would fail under that other module's name, not a `matcher` name,
    so it slips past the `'matcher' in name` filter here). That blanket
    "nothing silently imports the deleted module" guarantee is provided by
    `test_every_core_module_imports_cleanly` above (the REG-001 full-import
    sweep), which `import_module`s every core module and `pytest.fail`s on
    any failure.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('couchpotato.core.media._base.matcher')

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('couchpotato.lib.caper')

    failures = _sweep_import_failures()
    matcher_related = [name for name in failures if 'matcher' in name.lower()]
    assert not matcher_related, (
        f'Unexpected matcher-related import failures: {matcher_related}'
    )

    swept_names = set(failures) | {
        name
        for _finder, name, _ispkg in pkgutil.walk_packages(
            couchpotato.core.__path__, prefix='couchpotato.core.'
        )
    }
    assert 'couchpotato.core.media._base.matcher' not in swept_names
    assert not any(name.startswith('couchpotato.core.media._base.matcher.') for name in swept_names)


def test_loader_discovers_media_base_siblings_without_matcher(caplog):
    """The Loader's directory-scan discovery must not list `matcher`, and must
    still list the real (still-present) siblings under
    `couchpotato/core/media/_base/`.

    `Loader.preload()` only walks the filesystem (`pkgutil.iter_modules`) to
    build its module registry — it does NOT import any module (that happens
    later in `Loader.run()` -> `loadModule()`). So this test verifies exactly
    two things about discovery: (a) deleting the `matcher/` directory removed
    it from the registry, and (b) the deletion did not disturb discovery of
    its siblings (`library`, `media`, `providers`, `search`, `searcher`).

    Note the deliberate limit: because preload never imports, it can neither
    emit an ImportError nor an ERROR log for a dangling reference to the
    deleted module — a stray sibling `import` of `matcher` would surface only
    later under `run()`/`loadModule()`, or in the
    `test_every_core_module_imports_cleanly` sweep above, NOT here. The
    caplog ERROR assertion below therefore only asserts that *discovery
    itself* stays quiet, not that no dangling reference exists anywhere.
    """
    from unittest.mock import patch

    import couchpotato
    from couchpotato.core.loader import Loader

    # Derive the real repo root from the `couchpotato` package location
    # rather than this module-level REPO_ROOT: that constant is computed
    # with one dirname() too few for a file living in tests/unit/ (it
    # resolves to .../tests, not the repo root), which is harmless for the
    # sys.path bootstrapping above but not for the Loader, which needs the
    # actual on-disk `couchpotato/core/media` directory to walk.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(couchpotato.__file__)))

    loader = Loader()
    with caplog.at_level(logging.DEBUG), patch('couchpotato.environment.Env') as mock_env:
        mock_env.get.return_value = '/tmp/cp_test_data_vendored01'
        loader.preload(root=repo_root)

    discovered_modules = {
        module_name
        for modules_at_priority in loader.modules.values()
        for module_name in modules_at_priority
    }

    matcher_hits = [name for name in discovered_modules if 'matcher' in name.lower()]
    assert not matcher_hits, f'Loader still discovered matcher module(s): {matcher_hits}'

    # Siblings that used to live alongside matcher/ under _base/ must still
    # be discovered fine (the directory deletion shouldn't disturb them).
    for sibling in ('library', 'media', 'providers', 'search', 'searcher'):
        expected = f'couchpotato.core.media._base.{sibling}'
        assert expected in discovered_modules, (
            f'Expected sibling module {expected!r} to still be discovered, '
            f'got: {sorted(discovered_modules)}'
        )

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    matcher_or_caper_errors = [
        r for r in error_records if 'matcher' in r.message.lower() or 'caper' in r.message.lower()
    ]
    assert not matcher_or_caper_errors, (
        f'Loader logged an error mentioning matcher/caper during discovery: {matcher_or_caper_errors}'
    )
