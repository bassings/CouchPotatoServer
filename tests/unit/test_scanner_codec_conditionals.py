"""Structural regression coverage for scanner metadata conditionals."""

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MEDIA_PARSER = REPO_ROOT / 'couchpotato/core/plugins/scanner/media_parser.py'


def test_media_parser_has_no_nested_conditional_expressions():
    """Keep the S3358 class out of scanner metadata parsing."""
    assert MEDIA_PARSER.is_file(), f'missing scanner media parser: {MEDIA_PARSER}'
    tree = ast.parse(MEDIA_PARSER.read_text(encoding='utf-8'), filename=str(MEDIA_PARSER))
    get_meta = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'getMeta'
    ]
    assert len(get_meta) == 1, f'expected exactly one getMeta method, found {len(get_meta)}'

    nested = [
        child
        for expression in ast.walk(tree)
        if isinstance(expression, ast.IfExp)
        for child in ast.walk(expression)
        if child is not expression and isinstance(child, ast.IfExp)
    ]
    assert not nested, (
        'media_parser.py has nested conditional expressions at lines '
        f'{sorted({node.lineno for node in nested})}; use explicit branches'
    )
