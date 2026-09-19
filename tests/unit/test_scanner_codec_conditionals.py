"""Structural regression coverage for scanner metadata conditionals."""

import ast
from pathlib import Path

from tests.unit.ast_contracts import require_direct_class_method


REPO_ROOT = Path(__file__).resolve().parents[2]
MEDIA_PARSER = REPO_ROOT / 'couchpotato/core/plugins/scanner/media_parser.py'


def test_media_parser_has_no_nested_conditional_expressions():
    """Keep the S3358 class out of scanner metadata parsing."""
    assert MEDIA_PARSER.is_file(), f'missing scanner media parser: {MEDIA_PARSER}'
    tree = ast.parse(MEDIA_PARSER.read_text(encoding='utf-8'), filename=str(MEDIA_PARSER))
    require_direct_class_method(tree, 'MediaParserMixin', 'getMeta')

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
