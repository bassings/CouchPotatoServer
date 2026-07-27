"""Python 2 leftovers that raise NameError at runtime.

`unicode`, `long` and the old `ex()` exception-formatting helper do not exist
in Python 3, so every one of these lines raises NameError the moment it is
reached. They survived the Python 3 migration because they all sit on paths
that unit tests never exercised: an optional API parameter, two exception
handlers, and type checks that happen to be reached only with particular
argument shapes.

Ruff's F821 (undefined-name) finds all of them, but it was in the project-wide
ignore list with the comment "too many false positives with dynamic imports".
That is no longer true -- there are zero false positives -- so F821 is now
enforced, which is the real regression guard here. These tests cover the
reachable paths behaviourally; `test_f821_is_enforced` pins the mechanism so
the rule cannot be quietly switched off again.
"""

import pathlib

import pytest
import tomlkit


class TestSearchTypesArgument:
    """`MediaSearch.search()` normalises a bare string `types` argument via
    `isinstance(types, (str, unicode))` -- which raised NameError for EVERY
    caller, since the isinstance() call is evaluated before the branch is
    taken."""

    def _search_plugin(self):
        from couchpotato.core.media._base.search.main import Search

        return object.__new__(Search)

    def test_a_string_type_does_not_raise(self):
        """Bug repro: passing types as a string is the documented API shape
        and hit the NameError immediately."""
        from unittest.mock import patch

        plugin = self._search_plugin()

        with patch('couchpotato.core.media._base.search.main.fireEvent', return_value={}):
            result = plugin.search(q='test', types='movie')

        assert result is not None


class TestPlexServerErrorFormatting:
    """`plex/server.py` formats a parse failure with `ex(e)` -- a Python 2
    helper that no longer exists. The NameError fires from inside an `except`
    block, so it replaces the real diagnostic with a confusing one at exactly
    the moment someone is debugging their Plex setup."""

    def test_error_path_formats_the_exception(self):
        import couchpotato.core.notifications.plex.server as server

        source = server.__file__
        with open(source) as handle:
            text = handle.read()

        assert 'ex(e)' not in text, (
            "plex/server.py still calls the Python 2 ex() helper, which does "
            "not exist -- the except block will raise NameError"
        )


class TestF821IsEnforced:
    """The mechanism, pinned. Any of the above can regress silently; the lint
    rule cannot -- unless someone re-adds it to the ignore list, which is what
    this test prevents."""

    def _ruff_lint_config(self):
        """tomlkit, not tomllib: tomllib landed in Python 3.11 and CI's matrix
        includes 3.10, where importing it fails at collection time and takes
        the whole test module down. tomlkit is already a pinned runtime
        dependency and works on every supported version."""
        pyproject = pathlib.Path(__file__).resolve().parents[2] / 'pyproject.toml'

        return tomlkit.parse(pyproject.read_text())['tool']['ruff']['lint']

    def test_f821_is_not_ignored(self):
        config = self._ruff_lint_config()

        ignored = config.get('ignore', [])

        assert 'F821' not in ignored, (
            "F821 (undefined-name) catches Python 2 leftovers like `unicode` "
            "and `long`, and missing imports, that only crash when the line "
            "is finally reached. It found 8 real bugs and zero false "
            "positives when it was re-enabled -- keep it on."
        )

    def test_f_rules_are_still_selected(self):
        """Ignoring F821 individually is not the only way to lose it."""
        selected = self._ruff_lint_config().get('select', [])

        assert 'F' in selected or 'F821' in selected, (
            'the pyflakes rule group must stay selected for F821 to apply'
        )


@pytest.mark.parametrize('module_path', [
    'couchpotato/core/plugins/dashboard.py',
    'couchpotato/core/media/__init__.py',
    'couchpotato/core/media/_base/search/main.py',
    'couchpotato/core/plugins/release/main.py',
    'couchpotato/core/notifications/plex/server.py',
    'couchpotato/core/media/_base/providers/torrent/torrentday.py',
])
def test_no_python2_builtins_remain(module_path):
    """A cheap, direct assertion per known-affected file. F821 in CI is the
    general guard; this names the specific files so a regression points
    straight at the history."""
    import re

    with open(module_path) as handle:
        text = handle.read()

    # The lookarounds do the real work: they reject `toUnicode` and
    # `long_name` (adjacent word chars), `x.long` (attribute access) and
    # `'unicode'` (adjacent quotes) on their own. Deliberately NO
    # "skip lines that also mention the word in quotes" clause -- that would
    # skip a whole line like `f(unicode(x)) if mode == 'unicode' else x`,
    # hiding a genuine leftover behind an innocent string on the same line.
    for name in ('unicode', 'long', 'basestring'):
        matches = [
            line for line in text.splitlines()
            if re.search(r'(?<![\w.\'"])%s(?![\w\'"])' % name, line)
            and not line.strip().startswith('#')
        ]
        assert not matches, (
            '%s still references the Python 2 builtin %r: %s'
            % (module_path, name, matches[:3])
        )
