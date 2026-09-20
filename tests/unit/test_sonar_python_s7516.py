"""Structural regression guard for Sonar python:S7516."""

import ast
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[2]
    / "couchpotato/core/plugins/scanner/folder_scanner.py"
)


def _redundant_sorted_set_calls(source):
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == 'set'
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Call)
        and isinstance(node.args[0].func, ast.Name)
        and node.args[0].func.id == 'sorted'
    ]


def test_guard_recognizes_the_redundant_composition():
    calls = _redundant_sorted_set_calls('result = set(sorted(values, reverse=True))')

    assert len(calls) == 1


def test_folder_scanner_has_no_sort_discarded_by_set_construction():
    calls = _redundant_sorted_set_calls(SOURCE.read_text())

    assert calls == []
