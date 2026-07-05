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
