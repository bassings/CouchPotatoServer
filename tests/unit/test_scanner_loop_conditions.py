"""Structural regression tests for scanner shutdown loop predicates."""

import ast
from pathlib import Path


SCANNER_PATH = (
    Path(__file__).parents[2]
    / "couchpotato"
    / "core"
    / "plugins"
    / "scanner"
    / "folder_scanner.py"
)


def _popitem_owner(node):
    for descendant in ast.walk(node):
        if not isinstance(descendant, ast.Call):
            continue
        function = descendant.func
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "popitem"
            and isinstance(function.value, ast.Name)
        ):
            return function.value.id
    return None


def _is_shutdown_guard(node):
    operand = node.operand if isinstance(node, ast.UnaryOp) else None
    function = operand.func if isinstance(operand, ast.Call) else None
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.Not)
        and isinstance(operand, ast.Call)
        and not operand.args
        and not operand.keywords
        and isinstance(function, ast.Attribute)
        and function.attr == "shuttingDown"
        and isinstance(function.value, ast.Name)
        and function.value.id == "self"
    )


def test_dictionary_draining_loops_use_direct_shutdown_guards():
    tree = ast.parse(SCANNER_PATH.read_text(encoding="utf-8"))
    loops = {
        owner: node
        for node in ast.walk(tree)
        if isinstance(node, ast.While)
        if (owner := _popitem_owner(node)) in {"movie_files", "valid_files"}
    }

    assert set(loops) == {"movie_files", "valid_files"}
    invalid = [owner for owner, loop in loops.items() if not _is_shutdown_guard(loop.test)]
    assert invalid == [], f"loops without a direct shutdown guard: {invalid}"
