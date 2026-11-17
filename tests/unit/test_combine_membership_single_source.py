"""SEC-004 P6, AC-ARCH-1 and AC-ARCH-2: one source for "is this a combine column".

The groups come from the declarations the providers register, and one method
answers whether a name belongs to one. The per-column refusal asks it; nothing
else in the server keeps a second list of combine sections or columns, or tests
membership a second way. The section names and columns below are read from the
loaded configuration, never typed here.

What is scanned, and the rule that separates a legitimate mention from a second list:

* A single string equal to a section name is NOT a second list. `imdb` is also
  the media identifier namespace (`'imdb'` in the database and the scanner) and a
  provider names its own section in its own file. So a lone literal is checked
  only in the three files that decide membership (`core/settings.py`,
  `__init__.py`, `api.py`), where there is no reason to name one.
* A COLLECTION literal (list, tuple or set) is the second list the criterion
  forbids when it names two or more combine sections, or holds every column of
  a group. This is scanned across every production file under `couchpotato/`.
  The one exemption is the declaration itself: the value of a `combine` or
  `pairing` key, which is the single source the groups are derived from.
"""
import ast
from pathlib import Path

import pytest

from tests.helpers.combine_groups import group_settings

ROOT = Path(__file__).resolve().parents[2] / 'couchpotato'
DECIDING_FILES = ('core/settings.py', '__init__.py', 'api.py')
MEMBERSHIP_METHODS = {'combine_column', 'is_combine_option'}
DECLARATION_KEYS = ('combine', 'pairing')


@pytest.fixture
def groups(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as settings:
        yield settings.combine_groups()


def production_files():
    return sorted(path for path in ROOT.rglob('*.py') if '__pycache__' not in path.parts)


def docstring_nodes(tree):
    """The Constant nodes that are docstrings: prose, not code that decides."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def declaration_values(tree):
    """ids of the nodes that are the value of a `combine` or `pairing` key."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in DECLARATION_KEYS:
                    found.add(id(value))
    return found


def second_lists(tree, groups):
    """(line, strings) of every collection literal that repeats the groups."""
    exempt = declaration_values(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple, ast.Set)) or id(node) in exempt:
            continue
        strings = {element.value for element in node.elts
                   if isinstance(element, ast.Constant) and isinstance(element.value, str)}
        names_sections = len(strings & set(groups)) >= 2
        holds_a_group = any(strings >= set(columns) for columns in groups.values())
        if names_sections or holds_a_group:
            found.append((node.lineno, sorted(strings)))
    return found


def test_the_groups_the_scans_use_are_the_loaded_ones(groups):
    assert set(groups) >= {'newznab', 'torrentpotato'}
    assert all(len(columns) >= 2 for columns in groups.values())


@pytest.mark.parametrize('relative', DECIDING_FILES)
def test_no_deciding_file_hard_codes_a_combine_section_name(groups, relative):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    prose = docstring_nodes(tree)

    literals = [(node.lineno, node.value) for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in prose and node.value in groups]

    assert literals == [], '%s names a combine section in code: %r' % (relative, literals)


def test_no_production_file_keeps_a_second_list_of_combine_sections_or_columns(groups):
    hits = {}
    for path in production_files():
        found = second_lists(ast.parse(path.read_text(encoding='utf-8')), groups)
        if found:
            hits[str(path.relative_to(ROOT))] = found

    assert hits == {}, 'a second copy of the groups: %r' % hits


def test_the_scan_sees_a_second_list_when_one_exists(groups):
    sections = ast.parse("SECTIONS = ['newznab', 'torrentpotato']")
    columns = ast.parse("COLUMNS = %r" % list(groups['newznab']))
    declared = ast.parse("{'combine': %r}" % list(groups['newznab']))
    lone = ast.parse("x = ('newznab', 'enabled')")

    assert second_lists(sections, groups)
    assert second_lists(columns, groups)
    assert second_lists(declared, groups) == []
    assert second_lists(lone, groups) == []


def membership_calls():
    """(file, line, method) for every call of a membership method under couchpotato/."""
    calls = []
    for path in production_files():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in MEMBERSHIP_METHODS):
                calls.append((str(path.relative_to(ROOT)), node.lineno, node.func.attr))
    return calls


def test_combine_column_is_called_only_by_the_refusal_and_the_boolean_wrapper():
    calls = membership_calls()

    # `is_combine_option` wraps `combine_column`, so one call is inside the wrapper
    # and the other is the refusal's. Nothing else asks a membership question.
    assert [(path, method) for path, _, method in calls] == [
        ('core/settings.py', 'combine_column'), ('core/settings.py', 'combine_column')], calls


def test_the_refusal_asks_the_same_method_the_membership_tests_exercise():
    source = (ROOT / 'core/settings.py').read_text(encoding='utf-8')
    refusal = source[source.index('def _refuse_per_column'):source.index('def saveView')]

    assert 'self.combine_column(' in refusal
    assert 'combine_groups' not in refusal, 'the refusal builds its own membership test'
