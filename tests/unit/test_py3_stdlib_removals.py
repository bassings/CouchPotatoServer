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

import ast
import pathlib
from unittest.mock import MagicMock, patch

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


def _imported_modules(tree):
    """Every top-level module name imported by a parsed file.

    AST rather than regex, for the same reason test_event_wiring.py gives:
    a line-based pattern matches its own documentation, and `^\\s*` with
    re.M matches any physical line — including one inside a triple-quoted
    docstring that merely shows an import. Import nodes cannot be confused
    with prose.

    Submodules collapse to their root: `import imp.util` and
    `from distutils.core import setup` fail exactly like the bare module.
    """
    found = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` has module=None; relative imports are local.
            if node.module and not node.level:
                found.add(node.module.split('.')[0])

    return found


@pytest.mark.parametrize('module_name', sorted(REMOVED_MODULES))
def test_removed_stdlib_module_is_not_imported(module_name):
    """These raise ModuleNotFoundError on a supported interpreter. A guarded
    import (behind `if os.name == 'nt'`) is not safe either — it just moves the
    failure to the platform nobody tests on."""
    offenders = [
        str(path) for path in _python_files()
        if module_name in _imported_modules(ast.parse(path.read_text(errors='replace')))
    ]

    assert not offenders, (
        '%s was removed in Python %s but is imported by: %s'
        % (module_name, REMOVED_MODULES[module_name], offenders)
    )


@pytest.mark.parametrize('source,expected', [
    ('import imp', {'imp'}),
    ('def f():\n    import imp', {'imp'}),        # function-scope import
    ('if os.name == "nt":\n    import imp', {'imp'}),  # the guarded form
    ('import imp.util', {'imp'}),
    ('from imp import find_module', {'imp'}),
    ('from imp.util import thing', {'imp'}),
    ('from distutils.core import setup', {'distutils'}),
    ('import importlib', {'importlib'}),
    ('import importlib.util', {'importlib'}),
    ('from importlib import util', {'importlib'}),
    ('# import imp', set()),
    ('imp = 3', set()),
    ('"""Example:\n\n    import imp\n"""', set()),   # prose in a docstring
    ('from . import sibling', set()),                  # relative, not stdlib
], ids=lambda v: str(v)[:38])
def test_import_detection_discriminates(source, expected):
    """Catches every import form without firing on similarly-named modules
    (`importlib` starts with `imp`), commented-out imports, a variable of the
    same name, or an import shown inside a docstring."""
    assert _imported_modules(ast.parse(source)) == expected


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

    @pytest.fixture(autouse=True)
    def _restore_browser_module(self):
        """Snapshot and restore the module namespace around every test here.

        Reloading under a faked `os.name` leaves bindings the real platform
        never creates (`win32file`, `found`) permanently in the module. A
        plain reload afterwards does NOT clear them -- on posix the guarded
        block is skipped, so nothing reassigns them. Restoring the snapshot
        does, and as a fixture it runs even when a test fails partway.
        """
        import couchpotato.core.plugins.browser as browser

        snapshot = dict(vars(browser))
        try:
            yield browser
        finally:
            vars(browser).clear()
            vars(browser).update(snapshot)

    def _reimport_as_windows(self, find_spec_result, fake_win32file=None):
        """Re-execute browser.py with os.name faked to 'nt'.

        The pywin32 probe only runs at import time under that guard, so on
        Linux/macOS CI it is never executed — text-matching the source was the
        only coverage. Reloading the module with the guard satisfied actually
        runs the branch.
        """
        import importlib
        import sys

        import couchpotato.core.plugins.browser as browser

        modules = {'win32file': fake_win32file} if fake_win32file else {}

        with patch('os.name', 'nt'), \
                patch('importlib.util.find_spec', return_value=find_spec_result), \
                patch.dict(sys.modules, modules):
            return importlib.reload(browser)

    def test_missing_pywin32_raises_a_helpful_import_error(self):
        """The behaviour the original imp.find_module probe provided: a
        specific, actionable error rather than an opaque failure."""
        with pytest.raises(ImportError) as excinfo:
            self._reimport_as_windows(find_spec_result=None)

        assert 'pywin32' in str(excinfo.value)

    def test_present_pywin32_imports_cleanly(self):
        """The success branch: a spec is found, so the module goes on to
        import win32file and finish loading."""
        module = self._reimport_as_windows(
            find_spec_result=MagicMock(),
            fake_win32file=MagicMock(),
        )

        assert module.autoload == 'FileBrowser'

    def test_module_imports_on_this_platform(self):
        """Non-Windows: the guarded block is skipped entirely and the plugin
        must import cleanly (this is the path production actually takes)."""
        import couchpotato.core.plugins.browser as browser

        assert browser.autoload == 'FileBrowser'

    def test_no_windows_only_bindings_leak_into_the_module(self):
        """Pins the fixture: after a faked-Windows reload, the attributes that
        only exist on that path must not survive into the shared module."""
        self._reimport_as_windows(
            find_spec_result=MagicMock(), fake_win32file=MagicMock(),
        )


def test_browser_module_is_unpolluted_after_the_windows_tests():
    """Module-scope check, ordered after the class above: the faked-Windows
    reloads must not have left MagicMock bindings behind for the rest of the
    session."""
    import couchpotato.core.plugins.browser as browser

    for leaked in ('win32file', 'found'):
        assert not hasattr(browser, leaked), (
            'browser.%s leaked out of the faked-Windows reload' % leaked
        )
