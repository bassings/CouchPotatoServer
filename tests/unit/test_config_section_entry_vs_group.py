"""T53's real fix is not the Trakt notifier -- it is making sure the same
mistake cannot come back unnoticed anywhere else in this tree.

`couchpotato/core/loader.py::loadSettings` registers every plugin's `config`
block under its top-level ENTRY name (`section['name']`); it never registers
anything under a group's `name`. `couchpotato/core/notifications/trakt.py`
used to pass `'trakt_automation'` -- the automation module's GROUP name -- to
`Env.setting()`, so it always read a section nothing had ever written to.
That defect shape is not specific to Trakt: it is available at every call
site anywhere in this tree that hands `Env.setting()`/`.conf()` a section as
a hand-typed string literal, because nothing ties that string to the
`config` declarations it is supposed to name.

This sweeps the WHOLE `couchpotato/` tree structurally rather than relying
on the hand sweep that found T53 in the first place: it collects every
entry/group name declared by every module-level `config = [...]`, collects
every section literal handed to `Env.setting()`/`.conf()`/`super().conf()`,
and asserts every literal is an entry name.

Deliberately NOT built on `ast.literal_eval`. Four files in this tree
interpolate a runtime value somewhere inside their `config` dict --
`getDownloadDir()`, `uuid4().hex`, `random.randint(...)`, a shared
`rename_options` list -- which makes `literal_eval` raise on the WHOLE
assignment and would silently drop that file's entry name from the sweep:
`blackhole` (`downloaders/blackhole.py`), `core` (`_base/_core.py`),
`moviesearcher` (`media/movie/searcher.py`) and `renamer`
(`plugins/renamer/api.py`, the ONLY place `renamer` is declared -- there is
no fallback declaration elsewhere in the tree). A sweep that cannot see
those four is worse than no sweep: it looks complete and is not, which is
exactly the shape `trakt_automation` exploited to begin with. So the
extractor walks the AST structurally and reads only the `'name'` key's own
value node, never the surrounding dict, which survives interpolation
anywhere else in that dict.
"""
import ast
import os

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COUCHPOTATO_ROOT = os.path.join(REPO_ROOT, 'couchpotato')

# Call sites this sweep is not expected to flag, because it cannot tell they
# are wrong from the AST alone. Empty on purpose -- see
# `TestNoExemptionIsDeadWeight` below for why an empty set is the better
# outcome here, not a shortcut.
EXEMPT = frozenset()


def _iter_py_files(root):
    """Every `.py` file under `root`, deterministically ordered so a
    failure's file list does not depend on filesystem iteration order."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != '__pycache__')
        for filename in sorted(f for f in filenames if f.endswith('.py')):
            yield os.path.join(dirpath, filename)


def _dict_str_value(dict_node, key):
    """The string value bound to `key` in a `Dict` AST node's OWN keys --
    not recursively. Returns `None` if `key` is absent or its value is not a
    plain string constant (an interpolated value, for instance)."""
    for key_node, value_node in zip(dict_node.keys, dict_node.values):
        if isinstance(key_node, ast.Constant) and key_node.value == key:
            if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                return value_node.value
            return None
    return None


def _dict_value_node(dict_node, key):
    """The raw AST node bound to `key`, so a caller can check its own type
    (a `groups` value is expected to be a list literal)."""
    for key_node, value_node in zip(dict_node.keys, dict_node.values):
        if isinstance(key_node, ast.Constant) and key_node.value == key:
            return value_node
    return None


def _collect_entries_and_groups(root):
    """Structurally walk every module-level `config = [...]` under `root`.

    Returns `(entries, groups, files_with_config)`: the set of every entry
    name, the set of every group name, and the set of files that declared a
    `config`. The asserts inside this loop are deliberate -- if a file's
    `config` does not have the shape every declaration in this tree is
    known to have (a list of dicts, each with a literal string `'name'`),
    this must fail loudly rather than quietly contribute nothing to
    `entries`. A collector that skips silently on the unexpected case is
    exactly the trap `ast.literal_eval` would set here.
    """
    entries = set()
    groups = set()
    files_with_config = set()

    for path in _iter_py_files(root):
        source = open(path, encoding='utf-8').read()
        tree = ast.parse(source, filename=path)

        for node in tree.body:
            is_config_assign = (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'config' for t in node.targets)
            )
            if not is_config_assign:
                continue

            files_with_config.add(path)
            assert isinstance(node.value, ast.List), (
                f'{path}:{node.lineno}: module-level `config` is not a list '
                f'literal -- this sweep only knows how to walk a list of '
                f'dicts, and it must not silently ignore anything else'
            )

            for entry_node in node.value.elts:
                assert isinstance(entry_node, ast.Dict), (
                    f'{path}:{entry_node.lineno}: a `config` list element '
                    f'is not a dict literal'
                )
                name = _dict_str_value(entry_node, 'name')
                assert name is not None, (
                    f'{path}:{entry_node.lineno}: a `config` entry has no '
                    f'literal string `name` -- the sweep cannot register '
                    f'this entry and must not pretend it did'
                )
                entries.add(name)

                groups_node = _dict_value_node(entry_node, 'groups')
                if groups_node is None:
                    continue
                assert isinstance(groups_node, ast.List), (
                    f'{path}:{groups_node.lineno}: a `config` entry\'s '
                    f'`groups` is not a list literal'
                )
                for group_node in groups_node.elts:
                    if not isinstance(group_node, ast.Dict):
                        continue
                    gname = _dict_str_value(group_node, 'name')
                    if gname:
                        groups.add(gname)

    return entries, groups, files_with_config


def _collect_section_literal_call_sites(root):
    """Every `Env.setting(...)` / `.conf(...)` / `super().conf(...)` call
    that passes `section` as a string literal: the positional 2nd argument
    for `Env.setting` (its signature is `setting(attr, section='core', ...)`
    -- both real call sites in this tree that use `Env.setting` positionally
    do so for `section`), or the keyword `section=` for either (both forms
    are in real use here: `Env.setting('api_key', section='themoviedb')` in
    `plugins/suggestion.py`, and `self.conf('search_on_add',
    section='moviesearcher')` in `media/movie/_base/main.py`). Also checks
    `.conf`'s `section` passed positionally as its 4th argument
    (`Plugin.conf(self, attr, value=None, default=None, section=None)`) --
    unused today, kept because nothing stops a future call site doing it and
    the point of an AST sweep is not needing to notice that by hand.

    A call whose section is DERIVED rather than literal --
    `Env.setting('extra_score', section=provider.lower())`,
    `Env.setting('seed_ratio', section=self.provider.getName().lower())` --
    is deliberately NOT collected: there is nothing here to check it
    against ahead of time, and flagging it would just be noise.

    Returns a list of `(path, lineno, section)`.
    """
    sites = []

    for path in _iter_py_files(root):
        source = open(path, encoding='utf-8').read()
        tree = ast.parse(source, filename=path)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            func = node.func

            if func.attr == 'setting' and isinstance(func.value, ast.Name) and func.value.id == 'Env':
                if (len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)):
                    sites.append((path, node.lineno, node.args[1].value))
                for kw in node.keywords:
                    if kw.arg == 'section' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        sites.append((path, node.lineno, kw.value.value))

            elif func.attr == 'conf':
                for kw in node.keywords:
                    if kw.arg == 'section' and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        sites.append((path, node.lineno, kw.value.value))
                if (len(node.args) >= 4 and isinstance(node.args[3], ast.Constant)
                        and isinstance(node.args[3].value, str)):
                    sites.append((path, node.lineno, node.args[3].value))

    return sites


@pytest.fixture(scope='module')
def sweep():
    entries, groups, files_with_config = _collect_entries_and_groups(COUCHPOTATO_ROOT)
    call_sites = _collect_section_literal_call_sites(COUCHPOTATO_ROOT)
    return {
        'entries': entries,
        'groups': groups,
        'files_with_config': files_with_config,
        'call_sites': call_sites,
    }


def _rel(path):
    return os.path.relpath(path, REPO_ROOT)


class TestTheExtractorDoesNotSkipTheHardFiles:
    """The four files whose `config` cannot survive `ast.literal_eval`.
    Pinned individually so a future refactor of the extractor cannot regress
    back to `literal_eval` and quietly pass anyway -- the whole-tree baseline
    counts below would still drop by exactly these four, but a raw number
    going from 72 to 68 reads as "maybe fine", where a named entry
    disappearing does not.
    """

    KNOWN_HARD_FILES = {
        os.path.join(COUCHPOTATO_ROOT, 'core', 'downloaders', 'blackhole.py'): 'blackhole',
        os.path.join(COUCHPOTATO_ROOT, 'core', '_base', '_core.py'): 'core',
        os.path.join(COUCHPOTATO_ROOT, 'core', 'media', 'movie', 'searcher.py'): 'moviesearcher',
        os.path.join(COUCHPOTATO_ROOT, 'core', 'plugins', 'renamer', 'api.py'): 'renamer',
    }

    @pytest.mark.parametrize('path,entry_name', sorted(KNOWN_HARD_FILES.items()))
    def test_file_is_seen_and_its_entry_is_extracted(self, sweep, path, entry_name):
        assert path in sweep['files_with_config'], (
            f'{_rel(path)} was not even visited by the sweep -- check '
            f'`_iter_py_files` and the file still exists at this path'
        )
        assert entry_name in sweep['entries'], (
            f'{_rel(path)} declares entry {entry_name!r}, but it is missing '
            f'from the extracted entry names -- the structural walk regressed '
            f'to something that cannot survive this file\'s interpolated '
            f'`config` values (this is exactly what `ast.literal_eval` would '
            f'do)'
        )

    def test_renamer_has_no_fallback_declaration(self, sweep):
        """If some OTHER file ever starts declaring entry `renamer` too, the
        test above would keep passing even with a broken extractor for
        `renamer/api.py`, because the entry would still show up from
        elsewhere. Pin that `api.py` is the sole source today, so the test
        above is proven to be exercising the hard case and not accidentally
        redundant with an easy one."""
        declares_renamer = [
            f for f in sweep['files_with_config']
            if f != os.path.join(COUCHPOTATO_ROOT, 'core', 'plugins', 'renamer', 'api.py')
            and 'renamer' in _entries_declared_by(f)
        ]
        assert declares_renamer == [], (
            f'entry `renamer` is now ALSO declared by {declares_renamer!r} -- '
            f'`test_file_is_seen_and_its_entry_is_extracted` no longer proves '
            f'what its docstring claims; update this pin'
        )


def _entries_declared_by(path):
    """Every entry name a single file declares -- deliberately scoped to
    just this one file rather than reusing `_collect_entries_and_groups`
    over its directory, because a sibling file in the same directory could
    declare the same entry name and this needs a precise per-file answer."""
    source = open(path, encoding='utf-8').read()
    tree = ast.parse(source, filename=path)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'config' for t in node.targets):
            if isinstance(node.value, ast.List):
                for entry_node in node.value.elts:
                    if isinstance(entry_node, ast.Dict):
                        name = _dict_str_value(entry_node, 'name')
                        if name:
                            names.add(name)
    return names


class TestSweepFindsSomethingRealNotNothing:
    """A sweep that silently found zero entries or zero call sites would
    pass every assertion below it vacuously -- an empty guard cannot fail.
    These numbers are measured against this tree (72 entries, 19 call
    sites as of this fix) with headroom, so the baseline holds as the tree
    grows and only breaks if the extraction itself breaks."""

    def test_at_least_65_entries_found(self, sweep):
        assert len(sweep['entries']) >= 65, (
            f'only {len(sweep["entries"])} entry names extracted -- the '
            f'walk over module-level `config = [...]` is finding far less '
            f'than this tree actually declares'
        )

    def test_at_least_15_section_literal_call_sites_found(self, sweep):
        assert len(sweep['call_sites']) >= 15, (
            f'only {len(sweep["call_sites"])} section-literal call sites '
            f'found -- a guard that finds zero, or close to it, and then '
            f'passes is exactly the failure this sweep exists to prevent'
        )

    def test_known_call_sites_are_among_them(self, sweep):
        by_suffix = {
            (_rel(p).replace(os.sep, '/'), section)
            for p, _lineno, section in sweep['call_sites']
        }
        assert ('couchpotato/core/plugins/suggestion.py', 'themoviedb') in by_suffix, (
            'expected `Env.setting(\'api_key\', section=\'themoviedb\')` in '
            'plugins/suggestion.py to be collected'
        )
        assert ('couchpotato/core/plugins/dashboard.py', 'moviesearcher') in by_suffix, (
            'expected `Env.setting(\'wait_for_release\', '
            'section=\'moviesearcher\')` in plugins/dashboard.py to be '
            'collected'
        )


class TestEverySectionLiteralIsAnEntryName:
    """The actual guard. T53's shape, generalised: a section literal that
    names a GROUP rather than an ENTRY reads exactly like a working config
    read and always returns the default, because `loader.py` never
    registers anything under a group name."""

    def test_no_call_site_names_a_group_instead_of_an_entry(self, sweep):
        entries = sweep['entries']
        groups = sweep['groups']
        violations = []

        for path, lineno, section in sweep['call_sites']:
            if section in entries or section in EXEMPT:
                continue
            shape = (
                'names a GROUP, not an entry -- this is the exact T53 shape'
                if section in groups else
                'names neither a known entry nor a known group'
            )
            violations.append(f'{_rel(path)}:{lineno}: section={section!r} -- {shape}')

        assert violations == [], (
            'section literal(s) do not match any plugin entry name:\n  '
            + '\n  '.join(violations)
        )


class TestNoExemptionIsDeadWeight:
    """`EXEMPT` is empty, and that is the better outcome, not a shortcut
    taken because nothing was found. The hand sweep the orchestrator ran
    before this guard existed measured `trakt_automation` as the ONLY
    literal group-name section in the tree, and this fix removes that one
    call site rather than special-casing it -- so there is nothing left to
    exempt. If a future change adds one back and cannot fix it immediately,
    add it to `EXEMPT` and this test starts checking it the same way
    `test_settings_credential_masking.py`'s equivalent does: that the
    exempted (file, line, section) still exists, and that removing it from
    `EXEMPT` would make `test_no_call_site_names_a_group_instead_of_an_entry`
    fail -- proving the exemption is doing real work rather than sitting
    there as decoration."""

    def test_exempt_is_empty_and_that_is_deliberate(self):
        assert EXEMPT == frozenset(), (
            'EXEMPT is no longer empty -- add a case to this class that '
            'proves each entry corresponds to a real call site AND that '
            'the site would fail the guard without the exemption, the same '
            'way test_settings_credential_masking.py proves its exemptions'
        )
