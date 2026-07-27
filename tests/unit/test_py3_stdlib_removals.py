"""Modules and APIs removed from the Python 3 standard library.

`imp` was deprecated since 3.4 and **removed in 3.12**. `plugins/browser.py`
used `imp.find_module` to probe for pywin32 — inside an `os.name == 'nt'`
guard, so Linux and the Docker image never reached it, but a native Windows
install on any modern Python would raise ModuleNotFoundError at import time.
The plugin loader swallows ImportError at DEBUG, so the file browser would
simply vanish from the UI with no error anywhere the user would look.

That silent-disable is why a guarded import is not "safe": `couchpotato/core/
loader.py` logs a failed plugin import at DEBUG and moves on, so the only
symptom is a missing feature.

Scope note: this module covers removed stdlib *modules*. Removed *builtins*
(`unicode`, `long`, `basestring`) are covered separately by ruff's F821, which
is enforced in the blocking lint, plus tests/unit/test_py2_leftovers.py.
"""

import pathlib
import re

import pytest

# Anchored to this file rather than the CWD -- see test_event_wiring.py.
SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[2] / 'couchpotato'

# Removed in the Python versions this project supports (3.10-3.14).
REMOVED_MODULES = {
    'imp': '3.12 — use importlib',
    'distutils': '3.12 — use packaging/setuptools',
    'asynchat': '3.12',
    'asyncore': '3.12',
    'smtpd': '3.12 — use aiosmtpd',
    'binhex': '3.11',
    'formatter': '3.10',
    'parser': '3.10',
    'symbol': '3.10',
}


def _python_files():
    files = [p for p in SOURCE_ROOT.rglob('*.py') if 'lib/' not in str(p)]
    assert files, 'found no source files under %s' % SOURCE_ROOT
    return files


def _import_pattern(module_name):
    """Match every import form for a module, including submodules.

    `import imp.util` and `from distutils.core import setup` fail exactly the
    same way as the bare module, so matching only the top-level name would
    miss them. The `\\b` after the optional dotted tail keeps `imp` from
    matching `importlib`.
    """
    return re.compile(
        r'^\s*(?:import\s+%s(?:\.\w+)*\b|from\s+%s(?:\.\w+)*\s+import)'
        % (module_name, module_name),
        re.M,
    )


@pytest.mark.parametrize('module_name', sorted(REMOVED_MODULES))
def test_removed_stdlib_module_is_not_imported(module_name):
    """These raise ModuleNotFoundError on a supported interpreter. A guarded
    import (behind `if os.name == 'nt'`) is not safe either — it just moves the
    failure to the platform nobody tests on."""
    pattern = _import_pattern(module_name)

    offenders = [
        str(path) for path in _python_files()
        if pattern.search(path.read_text(errors='replace'))
    ]

    assert not offenders, (
        '%s was removed in Python %s but is imported by: %s'
        % (module_name, REMOVED_MODULES[module_name], offenders)
    )


@pytest.mark.parametrize('line,should_match', [
    ('import imp', True),
    ('    import imp', True),
    ('import imp.util', True),
    ('from imp import find_module', True),
    ('from imp.util import thing', True),
    ('import importlib', False),          # not `imp`, despite the prefix
    ('import importlib.util', False),
    ('from importlib import util', False),
    ('# import imp', False),              # a comment about it is fine
    ('imp = 3', False),                   # a variable named imp is fine
], ids=lambda v: str(v)[:34])
def test_removed_module_pattern_discriminates(line, should_match):
    """The detector must catch submodule imports without firing on
    similarly-named modules -- `importlib` starts with `imp`.

    Uses the same _import_pattern() the real test does, so this cannot drift
    into validating a frozen copy of the logic.
    """
    assert bool(_import_pattern('imp').search(line)) is should_match


class TestFileBrowserWindowsProbe:
    """The replacement has to keep the original behaviour: raise a helpful
    ImportError naming pywin32 when it is missing, rather than crashing with
    something opaque."""

    def test_uses_importlib_to_probe_for_pywin32(self):
        """Checked against CODE lines only — the module documents what it
        replaced, and a naive text search would match its own comment."""
        text = (SOURCE_ROOT / 'core' / 'plugins' / 'browser.py').read_text()
        code = '\n'.join(
            line for line in text.splitlines()
            if not line.strip().startswith('#')
        )

        assert 'importlib' in code
        assert 'imp.find_module' not in code

    def test_still_explains_how_to_install_pywin32(self):
        text = (SOURCE_ROOT / 'core' / 'plugins' / 'browser.py').read_text()

        assert 'pywin32' in text, (
            'the missing-dependency ImportError must still name the package'
        )

    def test_module_imports_on_this_platform(self):
        """Non-Windows: the guarded block is skipped entirely and the plugin
        must import cleanly (this is the path production actually takes)."""
        import couchpotato.core.plugins.browser as browser

        assert browser.autoload == 'FileBrowser'
