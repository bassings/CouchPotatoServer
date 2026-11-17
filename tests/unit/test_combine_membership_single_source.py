"""SEC-004 P6, AC-ARCH-1 and AC-ARCH-2: one source for "is this a combine column".

The groups come from the declarations the providers register, and one method
answers whether a name belongs to one. The per-column refusal asks it; nothing
else in the server keeps a second list of combine sections or tests membership
a second way. A static check cannot prove a negative about a future file, so it
pins what exists: no hard-coded section name in the files that decide, and one
caller of the membership method.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / 'couchpotato'
DECIDING_FILES = ('core/settings.py', '__init__.py', 'api.py')
MEMBERSHIP_METHODS = {'combine_column', 'is_combine_option'}
COMBINE_SECTIONS = ('newznab', 'torrentpotato', 'imdb', 'itunes', 'letterboxd')


def docstring_nodes(tree):
    """The Constant nodes that are docstrings: prose, not code that decides."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


@pytest.mark.parametrize('relative', DECIDING_FILES)
def test_no_deciding_file_hard_codes_a_combine_section_name(relative):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    prose = docstring_nodes(tree)

    literals = [(node.lineno, node.value) for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in prose and node.value in COMBINE_SECTIONS]

    assert literals == [], '%s names a combine section in code: %r' % (relative, literals)


def membership_calls():
    """(file, line, method) for every call of a membership method under couchpotato/."""
    calls = []
    for path in sorted(ROOT.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in MEMBERSHIP_METHODS):
                calls.append((str(path.relative_to(ROOT)), node.lineno, node.func.attr))
    return calls


def test_the_per_column_refusal_is_the_only_caller_of_the_membership_method():
    calls = membership_calls()

    # `is_combine_option` is a thin wrapper over `combine_column`, so its one call
    # is inside the wrapper itself; the refusal's call is the only other.
    assert sorted(method for _, _, method in calls) == ['combine_column', 'combine_column'], calls
    assert {path for path, _, _ in calls} == {'core/settings.py'}


def test_the_refusal_asks_the_same_method_the_membership_tests_exercise():
    source = (ROOT / 'core/settings.py').read_text(encoding='utf-8')
    refusal = source[source.index('def _refuse_per_column'):source.index('def saveView')]

    assert 'self.combine_column(' in refusal
    assert 'combine_groups' not in refusal, 'the refusal builds its own membership test'
