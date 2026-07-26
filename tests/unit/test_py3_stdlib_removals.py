"""Modules and APIs removed from the Python 3 standard library.

`imp` was deprecated since 3.4 and **removed in 3.12**. `plugins/browser.py`
used `imp.find_module` to probe for pywin32 — inside an `os.name == 'nt'`
guard, so Linux and the Docker image never reached it, but a native Windows
install on any modern Python would raise ModuleNotFoundError at import time.
The plugin loader swallows ImportError at DEBUG, so the file browser would
simply vanish from the UI with no error anywhere the user would look.

See MEMORY.md `loader-silent-import-swallow` for why that failure mode is
particularly nasty in this codebase.
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


@pytest.mark.parametrize('module_name', sorted(REMOVED_MODULES))
def test_removed_stdlib_module_is_not_imported(module_name):
    """These raise ModuleNotFoundError on a supported interpreter. A guarded
    import (behind `if os.name == 'nt'`) is not safe either — it just moves the
    failure to the platform nobody tests on."""
    pattern = re.compile(
        r'^\s*(?:import\s+%s\b|from\s+%s[\s.]+import)' % (module_name, module_name),
        re.M,
    )

    offenders = [
        str(path) for path in _python_files()
        if pattern.search(path.read_text(errors='replace'))
    ]

    assert not offenders, (
        '%s was removed in Python %s but is imported by: %s'
        % (module_name, REMOVED_MODULES[module_name], offenders)
    )


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
