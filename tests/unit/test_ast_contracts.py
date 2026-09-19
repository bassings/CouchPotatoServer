"""Tests for structural-test AST ownership assertions."""

import ast

import pytest

from tests.unit.ast_contracts import require_direct_class_method


def test_require_direct_class_method_returns_the_owned_method():
    tree = ast.parse('class Example:\n    def target(self):\n        return True\n')

    method = require_direct_class_method(tree, 'Example', 'target')

    assert method.name == 'target'


@pytest.mark.parametrize(
    'source',
    [
        'class Renamed:\n    def target(self):\n        return True\n',
        'class Example:\n    pass\n\nclass Other:\n    def target(self):\n        return True\n',
    ],
)
def test_require_direct_class_method_rejects_wrong_ownership(source):
    tree = ast.parse(source)

    with pytest.raises(AssertionError, match='Example'):
        require_direct_class_method(tree, 'Example', 'target')
