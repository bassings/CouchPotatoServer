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


# Forwarding wrappers: they pass a caller's option name through, so the name is not
# a literal, and they are not themselves a write of any one column. Allow-listed by
# file and function, never by name alone, so the same shape anywhere else is a hit.
FORWARDING_WRAPPERS = {
    # `Plugin.conf`: `Env.setting(attr, section=section or <this plugin>, value=value, ...)`.
    ('couchpotato/core/plugins/base.py', 'conf'),
    # Not a forwarder, but equally not a combine column: it switches the provider's
    # own enabler option (`self.enabled_option`, an `enabler` type) off after a login
    # failure, and no combine group contains an enabler.
    ('couchpotato/core/media/_base/providers/base.py', 'disableAccount'),
}


def _writes_a_value(method, call):
    """Does this `conf` / `setting` call pass a value?

    Real signatures: `Plugin.conf(self, attr, value=None, default=None, section=None)`
    takes the value second, and `Env.setting(attr, section='core', value=None, ...)`
    takes it third. A positional value is as much a write as `value=`.
    """
    if _keyword(call, 'value') is not None:
        return True
    return len(call.args) >= (2 if method == 'conf' else 3)


def _setting_section(call):
    explicit = _keyword(call, 'section')
    if explicit is not None:
        return _literal(explicit)
    return _literal(call.args[1]) if len(call.args) > 1 else 'core'


def _enclosing_functions(tree):
    owner = {}
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(function):  # inner functions overwrite outer ones
                owner[id(node)] = function.name
    return owner


def column_writes(source):
    """``[(line, [sections], option, function)]`` for every write of a column.

    `option` is None when the name is not a literal. A section of None is one that
    cannot be resolved.
    """
    tree = ast.parse(source)
    declared = _declared_sections(tree)
    owner = _enclosing_functions(tree)
    writes = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
            continue
        method = call.func.attr
        function = owner.get(id(call))
        if method in ('conf', 'setting') and _writes_a_value(method, call):
            option = _literal(call.args[0]) if call.args else _literal(_keyword(call, 'attr'))
            if method == 'setting':
                sections = [_setting_section(call)]
            else:
                explicit = _keyword(call, 'section')
                sections = [_literal(explicit)] if explicit is not None else sorted(declared) or [None]
            writes.append((call.lineno, sections, option, function))
        elif method == 'set' and len(call.args) >= 3 and _literal(call.args[0]) and _literal(call.args[1]):
            writes.append((call.lineno, [_literal(call.args[0])], _literal(call.args[1]), function))
    return writes


def combine_hits(source, groups, path='scratch.py'):
    """The writes in ``source`` that land in a combine column.

    An unresolvable section (None) counts against every group, because a write
    that cannot be placed cannot be shown to be outside one. A write whose option
    name is not a literal hits every group its section owns, unless it is an
    allow-listed forwarding wrapper.
    """
    hits = []
    for line, sections, option, function in column_writes(source):
        if option is None and (path, function) in FORWARDING_WRAPPERS:
            continue
        for section in sections:
            owners = [s for s in groups if section is None or s == section]
            if option is None and owners:
                hits.append((line, section, '<non-literal>'))
            elif option is not None and any(option.lower() in {c.lower() for c in groups[s]} for s in owners):
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

        assert column_writes(source) == [(4, ['rtorrent'], 'host', 'f')], 'the write was seen'
        assert combine_hits(source, groups) == []

    def test_a_core_setting_named_like_a_combine_column_is_not_a_hit(self, groups):
        """`Env.setting('api_key', value=...)` is core's own key (runner.py)."""
        assert combine_hits("Env.setting('api_key', value=key)\n", groups) == []

    def test_a_read_is_not_a_write(self, groups):
        source = ("config = [{'name': 'torrentpotato', 'groups': []}]\n"
                  "x = self.conf('host')\ny = self.conf('host', default='d')\n"
                  "z = Env.setting('pass_key', 'torrentpotato')\n"
                  "w = Env.setting('pass_key', section='torrentpotato', default='d')\n")

        assert column_writes(source) == []


class TestTheTree:

    def test_rtorrent_writes_a_host_and_that_is_not_a_hit(self, groups):
        """The must-not-match case: a real line that a name-only grep would flag."""
        source = (ROOT / 'core' / 'downloaders' / 'rtorrent_.py').read_text()

        writes = column_writes(source)

        assert any(section == ['rtorrent'] and option == 'host' for _, section, option, _ in writes), (
            'the scan no longer sees rtorrent_.py writing its own host')
        assert combine_hits(source, groups) == []

    def test_no_file_under_couchpotato_writes_a_combine_column(self, groups):
        found = []
        for path in sorted(ROOT.rglob('*.py')):
            relative = path.relative_to(ROOT.parent).as_posix()
            for line, section, option in combine_hits(path.read_text(), groups, relative):
                found.append('%s:%d writes %s.%s' % (relative, line, section, option))

        assert found == []


PROVIDER = ROOT / 'core' / 'media' / '_base' / 'providers' / 'torrent' / 'torrentpotato.py'


class TestTheShapesTheFirstScanMissed:
    """Each shape is appended to a copy of the REAL provider source, so the scan is
    shown to see it in a file whose section owns a combine group."""

    def scratch(self, line):
        return PROVIDER.read_text() + '\n\nclass Scratch:\n    def f(self):\n        %s\n' % line

    def appended_hits(self, groups, line, path='scratch.py'):
        source = self.scratch(line)
        appended = len(source.splitlines())
        return [hit for hit in combine_hits(source, groups, path) if hit[0] == appended]

    def test_the_real_provider_source_has_no_hit_of_its_own(self, groups):
        assert combine_hits(PROVIDER.read_text(), groups) == []

    def test_a_positional_value_to_conf_is_a_write(self, groups):
        assert self.appended_hits(groups, "self.conf('host', 'x')") == [
            (len(self.scratch("self.conf('host', 'x')").splitlines()), 'torrentpotato', 'host')]

    def test_a_positional_section_and_value_to_env_setting_is_a_write(self, groups):
        assert len(self.appended_hits(groups, "Env.setting('pass_key', 'torrentpotato', 'x')")) == 1

    def test_a_write_in_a_comprehension_with_a_non_literal_name_is_a_hit(self, groups):
        line = "[self.conf(c, value='x') for c in ('host', 'pass_key')]"

        hits = self.appended_hits(groups, line)

        assert [hit[1:] for hit in hits] == [('torrentpotato', '<non-literal>')]

    def test_the_forwarding_wrapper_is_allowed_only_at_its_own_path_and_function(self, groups):
        source = "class A:\n    def conf(self, attr, value=None):\n        return Env.setting(attr, section=section or name, value=value)\n"

        assert combine_hits(source, groups, 'couchpotato/core/plugins/base.py') == []
        assert combine_hits(source, groups, 'couchpotato/core/plugins/other.py') != []

    def test_a_non_literal_name_in_a_section_with_no_combine_group_is_not_a_hit(self, groups):
        source = ("config = [{'name': 'tmdb_charts', 'groups': []}]\n"
                  "class A:\n    def conf(self, attr, value=None):\n"
                  "        return super().conf(attr, value=value, section='tmdb_charts')\n")

        assert combine_hits(source, groups) == []
