"""Structural regression coverage for movie-add category conditionals."""

import ast
from pathlib import Path

from tests.unit.ast_contracts import require_direct_class_method


REPO_ROOT = Path(__file__).resolve().parents[2]
MOVIE_BASE = REPO_ROOT / 'couchpotato/core/media/movie/_base/main.py'


def test_movie_base_has_no_nested_conditional_expressions():
    """Keep the S3358 class out of the movie-add module."""
    assert MOVIE_BASE.is_file(), f'missing movie base module: {MOVIE_BASE}'
    tree = ast.parse(MOVIE_BASE.read_text(encoding='utf-8'), filename=str(MOVIE_BASE))
    require_direct_class_method(tree, 'MovieBase', 'add')

    nested = [
        child
        for expression in ast.walk(tree)
        if isinstance(expression, ast.IfExp)
        for child in ast.walk(expression)
        if child is not expression and isinstance(child, ast.IfExp)
    ]
    assert not nested, (
        'main.py has nested conditional expressions at lines '
        f'{sorted({node.lineno for node in nested})}; use explicit branches'
    )
