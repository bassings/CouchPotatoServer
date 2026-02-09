"""Tests for CouchPotato utility/helper functions.

Tests encoding helpers (toUnicode, toSafeString, simplifyString)
and variable helpers (tryInt, tryFloat, getImdb, etc.).
"""
import pytest

from couchpotato.core.helpers.encoding import toUnicode, toSafeString, simplifyString
from couchpotato.core.helpers.variable import tryInt, getImdb

pytestmark = pytest.mark.unit


class TestEncodingHelpers:
    """Test string encoding/conversion utilities."""

    def test_toUnicode_with_str(self):
        assert toUnicode('hello') == 'hello'

    def test_toUnicode_with_bytes(self):
        result = toUnicode(b'hello', 'utf-8')
        assert isinstance(result, str)
        assert result == 'hello'

    def test_toUnicode_with_int(self):
        result = toUnicode(42)
        assert result == '42'

    def test_toSafeString_strips_special_chars(self):
        result = toSafeString('Hello/World:Test!')
        assert '/' not in result
        assert ':' not in result
        assert '!' not in result

    def test_toSafeString_preserves_alphanumeric(self):
        result = toSafeString('Hello World 2024')
        assert 'Hello' in result
        assert 'World' in result
        assert '2024' in result

    def test_simplifyString_lowercase_and_clean(self):
        result = simplifyString('The Lost City (2022)')
        assert result == result.lower()
        assert 'the' in result
        assert 'lost' in result
        assert 'city' in result
        assert '2022' in result

    def test_simplifyString_strips_accents(self):
        result = simplifyString('Amélie')
        assert 'amelie' in result


class TestVariableHelpers:
    """Test variable/type conversion utilities."""

    def test_tryInt_with_valid_int(self):
        assert tryInt('42') == 42

    def test_tryInt_with_float_string(self):
        assert tryInt('3.14') == 0  # not a clean int

    def test_tryInt_with_invalid_returns_default(self):
        assert tryInt('not_a_number') == 0

    def test_tryInt_with_none(self):
        assert tryInt(None) == 0

    def test_getImdb_extracts_from_url(self):
        result = getImdb('https://www.imdb.com/title/tt1234567/')
        assert result == 'tt1234567'

    def test_getImdb_extracts_bare_id(self):
        result = getImdb('tt7654321')
        assert result == 'tt7654321'

    def test_getImdb_returns_falsy_for_no_match(self):
        result = getImdb('no imdb here')
        assert not result
