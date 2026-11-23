"""`getParams` hands a handler the text the framework delivered, and decodes nothing.

The web framework has already percent-decoded a query string and a form body,
and a JSON body was never encoded, so a second decode changes text that is
already the caller's value (`a%41b` became `aAb`, `p%25w` became `p%w`, and a
`%FF` that is not UTF-8 became U+FFFD with the original unrecoverable).

Values are placeholders; none resembles a real credential.
"""
import pytest

from couchpotato.core.helpers.request import dictToList, getParams

#: Text that is ALREADY decoded. Every one must reach a handler unchanged.
DELIVERED = [
    'a%41b',
    'p%25w',
    '%2C',
    '%2c',
    '%252C',
    '%FF',
    '100%',
    'a+b',
    'a&b=c',
    'jack%C3%A9tt',
    'jackétt',
    'placeholder-pa%41ss',
]


@pytest.mark.parametrize('value', DELIVERED)
class TestAValueIsNotDecodedAgain:

    def test_a_flat_value(self, value):
        assert getParams({'v': value}) == {'v': value}

    def test_a_nested_bracket_key_value(self, value):
        assert getParams({'rows[0][host]': value}) == {'rows': [{'host': value}]}

    def test_a_nested_dict_value(self, value):
        assert getParams({'a[b]': value}) == {'a': {'b': value}}


class TestEverythingElseStillHappens:
    """AC-4: only the decode went; the rest of `getParams` is as it was."""

    def test_flat_true_and_false_text_still_becomes_a_boolean(self):
        assert getParams({'x': 'true', 'y': 'False'}) == {'x': True, 'y': False}

    def test_non_string_values_pass_through(self):
        assert getParams({'n': 3, 'b': True, 'l': ['a%41']}) == {'n': 3, 'b': True, 'l': ['a%41']}

    def test_nested_true_text_is_not_coerced(self):
        assert getParams({'a[b]': 'true'}) == {'a': {'b': 'true'}}

    def test_nested_keys_are_ordered_naturally_and_listed(self):
        params = {'rows[10][k]': 'ten', 'rows[2][k]': 'two', 'rows[1][k]': 'one'}
        assert getParams(params) == {'rows': [{'k': 'one'}, {'k': 'two'}, {'k': 'ten'}]}

    def test_dict_to_list_leaves_a_non_numeric_dict_alone(self):
        assert dictToList({'a': {'x': '1'}}) == {'a': {'x': '1'}}
