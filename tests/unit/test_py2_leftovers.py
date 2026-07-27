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

import ast
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

        with patch('couchpotato.core.media._base.search.main.fireEvent', return_value={}) as fire:
            result = plugin.search(q='test', types='movie')

        # `assert result is not None` would pass even if the string were
        # iterated character by character -- assert the normalisation instead:
        # exactly one lookup, for the whole word.
        fired = [c.args[0] for c in fire.call_args_list]
        assert fired == ['movie.search'], (
            "a string `types` must be normalised to one entry, not iterated "
            "per character; fired: %s" % fired
        )
        assert result['movie'] == {}


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
    """A direct assertion per known-affected file. F821 in CI is the general
    guard; this names the specific files so a regression points straight at
    the history.

    Uses the AST rather than a regex. Two earlier regex attempts both failed
    in opposite directions: a loose pattern matched ordinary prose ("wait as
    long as needed" in a docstring), and tightening it to require trailing
    punctuation then MISSED real leftovers like `text_type = unicode` and a
    bare name as the last element of a wrapped tuple. Name nodes have neither
    problem -- comments and string literals are not names, and a name is a
    name wherever it appears.

    Only Load context counts: reading `unicode` is the bug. A local variable
    that happens to be called `file` or `buffer` is not.
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    tree = ast.parse((root / module_path).read_text())

    offenders = sorted({
        '%s (line %d)' % (node.id, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in ('unicode', 'long', 'basestring', 'xrange', 'raw_input')
    })

    assert not offenders, (
        '%s still reads Python 2 builtins: %s' % (module_path, offenders)
    )


@pytest.mark.parametrize('source,should_flag', [
    ('isinstance(x, (str, unicode))', True),
    ('y = unicode(v)', True),
    ('text_type = unicode', True),                    # missed by the tight regex
    ('T = (\n    str,\n    unicode\n)', True),       # bare name in a wrapped tuple
    ('def f():\n    """wait as long as needed"""', False),   # prose in a docstring
    ('s = "a long time"', False),                     # prose in a string
    ('# unicode was removed', False),                 # prose in a comment
    ('text = toUnicode(v)', False),                   # different identifier
    ('a = long_name', False),
    ('b = obj.long', False),                          # attribute, not a name
    ('for file in files:\n    pass', False),           # Store context
], ids=lambda v: str(v)[:38])
def test_builtin_detector_discriminates(source, should_flag):
    """Pins both failure directions the earlier regexes fell into."""
    tree = ast.parse(source)

    flagged = any(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in ('unicode', 'long', 'basestring', 'xrange', 'raw_input')
        for node in ast.walk(tree)
    )

    assert flagged is should_flag
