"""Regression guard for readable release-table sort conditionals."""

import ast
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / 'couchpotato'
    / 'ui'
    / 'releases_view.py'
)


def test_release_view_has_no_nested_conditional_expressions():
    assert MODULE_PATH.is_file(), f'release view module was not found: {MODULE_PATH}'
    tree = ast.parse(MODULE_PATH.read_text(encoding='utf-8'))
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == 'sort_columns'
    ]
    assert len(functions) == 1, 'expected exactly one sort_columns function'

    nested_lines = [
        child.lineno
        for conditional in ast.walk(tree)
        if isinstance(conditional, ast.IfExp)
        for child in ast.walk(conditional)
        if child is not conditional and isinstance(child, ast.IfExp)
    ]
    assert nested_lines == [], (
        f'releases_view.py has nested conditional expressions at lines: {nested_lines}'
    )
