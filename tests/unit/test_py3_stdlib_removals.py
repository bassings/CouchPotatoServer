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

    def test_module_imports_on_this_platform(self):
        """Non-Windows: the guarded block is skipped entirely and the plugin
        must import cleanly (this is the path production actually takes)."""
        import couchpotato.core.plugins.browser as browser

        assert browser.autoload == 'FileBrowser'
