"""Shared ownership assertions for AST-based structural regression tests."""

import ast


def require_direct_class_method(tree, class_name, method_name):
    """Return one method directly owned by one named top-level class."""
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    assert len(classes) == 1, (
        f'expected exactly one top-level {class_name} class, found {len(classes)}'
    )

    methods = [
        node
        for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    ]
    assert len(methods) == 1, (
        f'expected exactly one {class_name}.{method_name} method, found {len(methods)}'
    )
    return methods[0]
