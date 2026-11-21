"""SEC-005 P2, AC-SEC-11, AC-SEC-14, AC-QA-22: one reader of the saved Jackett key, and the claims that went with the old gap.

The saved `jackett_api_key` is read in exactly one function, which also does the
binding check. This test reads every Python file under ``couchpotato/`` as a
syntax tree, so quoting, ``self.conf``, ``Env.setting(..., section=...)``,
``settings.get`` and the generic ``_savedJackettSetting(name)`` with a variable
name are all one finding. Reading text alone would miss every one of those.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'couchpotato'
PROVIDER = SOURCE / 'core/media/_base/providers/torrent/torrentpotato.py'
OPTION = 'jackett_api_key'
READER = '_jackettCredentials'
GENERIC_READER = '_savedJackettSetting'


def python_files(base=SOURCE):
    return sorted(path for path in base.rglob('*.py') if '__pycache__' not in path.parts)


def parent_map(tree):
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def enclosing_function(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return None


def is_declaration_or_docs(node, parents):
    """A dict key (the API docs) or the `'name': 'jackett_api_key'` of the option's own declaration."""
    parent = parents.get(node)
    if not isinstance(parent, ast.Dict):
        return False
    if node in parent.keys:
        return True
    index = parent.values.index(node)
    key = parent.keys[index]
    return isinstance(key, ast.Constant) and key.value == 'name'


def is_fixed_name(node):
    """A string literal, or an UPPER_CASE module constant (whose own definition is found as a literal)."""
    return isinstance(node, ast.Constant) or (isinstance(node, ast.Name) and node.id.isupper())


def reads(source_text):
    """(function, line, how) for every way the tree names the option other than declaring it."""
    tree = ast.parse(source_text)
    parents = parent_map(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip().lower() == OPTION:
            if not is_declaration_or_docs(node, parents):
                found.append((enclosing_function(node, parents), node.lineno, 'name'))
        if isinstance(node, ast.Call):
            func = node.func
            callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', None)
            if callee == GENERIC_READER and node.args and not is_fixed_name(node.args[0]):
                found.append((enclosing_function(node, parents), node.lineno, 'variable name'))
    return found


def all_reads():
    return [(path, *hit) for path in python_files() for hit in reads(path.read_text(encoding='utf-8'))]


def test_the_saved_key_is_read_in_exactly_one_function_in_one_place():
    hits = all_reads()

    assert [(path.relative_to(ROOT).as_posix(), function, how) for path, function, _, how in hits] == [
        (PROVIDER.relative_to(ROOT).as_posix(), READER, 'name')]


def test_the_one_reader_also_does_the_binding_check():
    tree = ast.parse(PROVIDER.read_text(encoding='utf-8'))
    reader = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == READER)
    called = {call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')
              for call in ast.walk(reader) if isinstance(call, ast.Call)}

    assert 'normalise_jackett_address' in called
    assert '_refusal_reason' in called


@pytest.mark.parametrize('route', ['jackettTest', 'jackettSync'])
def test_both_routes_reach_the_reader_before_they_fetch_anything(route):
    tree = ast.parse(PROVIDER.read_text(encoding='utf-8'))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == route)
    calls = sorted(((call.lineno, call.func.attr) for call in ast.walk(function)
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)))
    names = [name for _, name in calls]

    assert READER in names
    assert 'getJackettIndexers' in names
    assert names.index(READER) < names.index('getJackettIndexers')


@pytest.mark.parametrize('second_read', [
    "def other(self):\n    return self.conf('jackett_api_key')\n",
    'def other(self):\n    return self.conf("jackett_api_key")\n',
    "def other():\n    return Env.setting('jackett_api_key', section='torrentpotato')\n",
    "def other(self, name):\n    return self._savedJackettSetting(name)\n",
    "def other(self):\n    return Env.get('settings').get('Jackett_Api_Key ', 'torrentpotato')\n",
    "KEY_NAME = 'jackett_api_key'\n",
])
def test_the_checker_sees_a_second_read_by_any_route(second_read):
    assert reads(second_read), 'the check cannot see this read, so it would let a second reader in'


def test_the_declaration_and_the_api_docs_are_not_reads():
    declaration = "config = [{'groups': [{'options': [{'name': 'jackett_api_key'}]}]}]\n"
    docs = "docs = {'params': {'jackett_api_key': {'desc': 'x'}}}\n"

    assert reads(declaration) == []
    assert reads(docs) == []


def test_AC_SEC_14_the_docstring_says_the_key_is_only_sent_to_the_address_it_was_bound_to():
    tree = ast.parse(PROVIDER.read_text(encoding='utf-8'))
    reader = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == READER)
    docstring = ' '.join(ast.get_docstring(reader).split())

    assert 'only sent to the address it was bound to' in docstring
    for path in python_files():
        assert 'does not bind the saved key' not in path.read_text(encoding='utf-8'), path


def test_AC_QA_22_the_scope_tests_docstring_no_longer_pins_the_old_gap():
    scope = (ROOT / 'tests/unit/test_jackett_saved_key_scope.py').read_text(encoding='utf-8')
    module_docstring = ' '.join(ast.get_docstring(ast.parse(scope)).split())
    removed = 'sends the saved key' + ' to the new URL'

    assert 'refused when the saved address differs from the one the key was saved for' in module_docstring
    for path in sorted((ROOT / 'tests').rglob('*.py')):
        assert removed not in path.read_text(encoding='utf-8'), path
    assert 'can still change' not in module_docstring
