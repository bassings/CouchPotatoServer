"""SEC-004 P2, AC-DATA-10: no Python call site writes a combine column except the group writer.

The scan is section-aware. A name-only search for ``host`` would flag a
legitimate writer, ``rtorrent_.py``'s ``self.conf('host', value=...)``, which
writes an option called ``host`` in a section that has no ``combine`` group. A
hit counts only when the file's section owns a combine group that contains the
option name.

How a write is resolved:

* ``Env.setting(name, section=..., value=...)``: the section is the ``section``
  argument, or ``core`` when there is none.
* ``<anything>.conf(name, value=...)``: the plugin's own section, taken from the
  ``config`` declaration in the same file. A file that declares none (a subclass
  in another module) cannot be resolved and so counts against every group.
* ``<anything>.set(section, name, value)`` with a literal section and name.

A call whose option name is not a literal (the ``conf`` forwarding wrappers) is
not a write of a named column and is not judged.
"""
import ast
from pathlib import Path

import pytest

from tests.helpers.combine_groups import group_settings

ROOT = Path(__file__).resolve().parents[2] / 'couchpotato'


def _literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _declared_sections(tree):
    """Section names a module declares in its top-level ``config`` list."""
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'config' for t in node.targets):
            # Only the list's own entries: their nested options carry `name` keys too.
            for item in getattr(node.value, 'elts', []):
                if isinstance(item, ast.Dict):
                    for key, value in zip(item.keys, item.values):
                        if _literal(key) == 'name' and _literal(value):
                            names.add(_literal(value))
    return names


def _keyword(call, name):
    return next((k.value for k in call.keywords if k.arg == name), None)


def column_writes(source):
    """``[(line, [sections], option)]`` for every write of a literal option name."""
    tree = ast.parse(source)
    declared = _declared_sections(tree)
    writes = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
            continue
        method = call.func.attr
        if method in ('conf', 'setting') and _keyword(call, 'value') is not None:
            option = _literal(call.args[0]) if call.args else _literal(_keyword(call, 'attr'))
            if option is None:
                continue
            if method == 'setting':
                section = _literal(_keyword(call, 'section')) if _keyword(call, 'section') else (
                    _literal(call.args[1]) if len(call.args) > 1 else 'core')
                sections = [section] if section else [None]
            else:
                explicit = _keyword(call, 'section')
                sections = [_literal(explicit)] if explicit is not None else sorted(declared) or [None]
            writes.append((call.lineno, sections, option))
        elif method == 'set' and len(call.args) >= 3 and _literal(call.args[0]) and _literal(call.args[1]):
            writes.append((call.lineno, [_literal(call.args[0])], _literal(call.args[1])))
    return writes


def combine_hits(source, groups):
    """The writes in ``source`` that land in a combine column.

    An unresolvable section (None) counts against every group, because a write
    that cannot be placed cannot be shown to be outside one.
    """
    hits = []
    for line, sections, option in column_writes(source):
        for section in sections:
            owners = [s for s in groups if section is None or s == section]
            if any(option.lower() in {c.lower() for c in groups[s]} for s in owners):
                hits.append((line, section, option))
    return hits


@pytest.fixture
def groups(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as settings:
        yield settings.combine_groups()


class TestTheScanItself:
    """The guard is only worth having if it can see the shapes it exists for."""

    def test_a_conf_write_of_a_combine_column_in_the_owning_section_is_a_hit(self, groups):
        source = ("config = [{'name': 'torrentpotato', 'groups': []}]\n"
                  "class A:\n    def f(self):\n        self.conf('host', value='x')\n")

        assert combine_hits(source, groups) == [(4, 'torrentpotato', 'host')]

    def test_an_env_setting_write_with_an_explicit_section_is_a_hit(self, groups):
        source = "Env.setting('pass_key', section='torrentpotato', value='x')\n"

        assert combine_hits(source, groups) == [(1, 'torrentpotato', 'pass_key')]

    def test_a_write_through_the_parser_with_literal_names_is_a_hit(self, groups):
        source = "settings.set('newznab', 'API_KEY', 'x')\n"

        assert combine_hits(source, groups) == [(1, 'newznab', 'API_KEY')]

    def test_a_file_that_declares_no_section_counts_against_every_group(self, groups):
        source = "class A:\n    def f(self):\n        self.conf('seed_time', value='1')\n"

        assert combine_hits(source, groups) == [(3, None, 'seed_time')]

    def test_the_same_option_name_in_a_section_with_no_combine_group_is_not_a_hit(self, groups):
        source = ("config = [{'name': 'rtorrent', 'groups': []}]\n"
                  "class A:\n    def f(self):\n        self.conf('host', value='x')\n")

        assert column_writes(source) == [(4, ['rtorrent'], 'host')], 'the write was seen'
        assert combine_hits(source, groups) == []

    def test_a_core_setting_named_like_a_combine_column_is_not_a_hit(self, groups):
        """`Env.setting('api_key', value=...)` is core's own key (runner.py)."""
        assert combine_hits("Env.setting('api_key', value=key)\n", groups) == []

    def test_a_non_literal_option_name_is_not_judged(self, groups):
        assert column_writes("self.conf(name, value=value)\n") == []


class TestTheTree:

    def test_rtorrent_writes_a_host_and_that_is_not_a_hit(self, groups):
        """The must-not-match case: a real line that a name-only grep would flag."""
        source = (ROOT / 'core' / 'downloaders' / 'rtorrent_.py').read_text()

        writes = column_writes(source)

        assert any(section == ['rtorrent'] and option == 'host' for _, section, option in writes), (
            'the scan no longer sees rtorrent_.py writing its own host')
        assert combine_hits(source, groups) == []

    def test_no_file_under_couchpotato_writes_a_combine_column(self, groups):
        found = []
        for path in sorted(ROOT.rglob('*.py')):
            for line, section, option in combine_hits(path.read_text(), groups):
                found.append('%s:%d writes %s.%s' % (path.relative_to(ROOT.parent), line, section, option))

        assert found == []
