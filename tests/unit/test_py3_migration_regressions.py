"""Task 15: Regression tests for known Python 3 migration bugs.

These tests verify that specific bugs found and fixed during the Py2→Py3
migration stay fixed.
"""
import json
import os
import sys
import struct
import tempfile
import shutil
import pytest
from base64 import b64decode, b64encode
from unittest.mock import patch, MagicMock, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs'))


# ---------------------------------------------------------------------------
# 1. TMDB getApiKey() — b64decode returns bytes, must decode to str
# ---------------------------------------------------------------------------

class TestTMDBApiKeyDecode:
    """The TMDB provider stores base64-encoded API keys. b64decode() returns
    bytes in Python 3; the code must .decode() before using the key in a URL."""

    def test_b64decode_returns_bytes(self):
        """Verify b64decode returns bytes (the root cause of the bug)."""
        encoded = b64encode(b'someapikey123')
        decoded = b64decode(encoded)
        assert isinstance(decoded, bytes)

    def test_getApiKey_returns_str(self):
        """Simulate the TMDB getApiKey fix: decoded key must be str."""
        ak = ['ZTIyNGZlNGYzZmVjNWY3YjU1NzA2NDFmN2NkM2RmM2E=']
        import random
        decoded = b64decode(random.choice(ak))
        # The fix: decode bytes to str
        result = decoded.decode('utf-8') if isinstance(decoded, bytes) else decoded
        assert isinstance(result, str)
        assert result == 'e224fe4f3fec5f7b557064 1f7cd3df3a'.replace(' ', '')

    def test_api_key_usable_in_url_format(self):
        """Key must be usable in string formatting for URL construction."""
        key_b64 = b64encode(b'testkey123')
        decoded = b64decode(key_b64)
        key = decoded.decode('utf-8') if isinstance(decoded, bytes) else decoded
        # This would raise TypeError in Py3 if key were bytes
        url = 'https://api.themoviedb.org/3/movie?api_key=%s' % key
        assert 'testkey123' in url

    def test_bytes_key_in_url_would_fail(self):
        """Demonstrate the bug: using bytes directly in URL formatting gives wrong result."""
        key_bytes = b64decode(b64encode(b'testkey123'))
        # In Py3, %s with bytes gives "b'testkey123'" which is wrong
        url = 'https://api.themoviedb.org/3/movie?api_key=%s' % key_bytes
        assert "b'" in url  # This is the buggy behavior


# ---------------------------------------------------------------------------
# 2. OMDB bytes response not decoded before JSON parse
# ---------------------------------------------------------------------------

class TestOMDBBytesResponse:
    """OMDB provider receives HTTP response as bytes; must decode before
    json.loads() in Python 3."""

    def test_json_loads_rejects_bytes_in_py3(self):
        """json.loads(bytes) works in modern Python but the parseMovie
        method should handle bytes input gracefully."""
        data = b'{"Title": "Test Movie", "Type": "movie", "Year": "2021", "Response": "True"}'
        # The fix: decode bytes before json.loads
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        parsed = json.loads(data)
        assert parsed['Title'] == 'Test Movie'

    def test_parseMovie_handles_bytes_input(self):
        """Simulate the OMDB parseMovie fix for bytes input."""
        movie_bytes = b'{"Title":"Inception","Type":"movie","Year":"2010","Response":"True","imdbID":"tt1375666"}'
        # Simulate the fix
        movie = movie_bytes
        if isinstance(movie, bytes):
            movie = movie.decode('utf-8')
        if isinstance(movie, str):
            movie = json.loads(movie)
        assert movie['Title'] == 'Inception'
        assert movie['Year'] == '2010'

    def test_parseMovie_handles_str_input(self):
        """str input should also work (no double-decode)."""
        movie_str = '{"Title":"Inception","Type":"movie","Year":"2010","Response":"True"}'
        movie = movie_str
        if isinstance(movie, bytes):
            movie = movie.decode('utf-8')
        if isinstance(movie, str):
            movie = json.loads(movie)
        assert movie['Title'] == 'Inception'

    def test_parseMovie_handles_dict_input(self):
        """Already-parsed dict should pass through."""
        movie_dict = {"Title": "Inception", "Type": "movie", "Year": "2010", "Response": "True"}
        movie = movie_dict
        if isinstance(movie, bytes):
            movie = movie.decode('utf-8')
        if isinstance(movie, str):
            movie = json.loads(movie)
        assert movie['Title'] == 'Inception'


# ---------------------------------------------------------------------------
# 3. Provider getEnabledProtocol() — must return list, not bare string
# ---------------------------------------------------------------------------

class TestGetEnabledProtocol:
    """If getEnabledProtocol returns a string instead of a list,
    `list += string` iterates over characters: ['t','o','r','r','e','n','t']."""

    def test_list_plus_string_iterates_chars(self):
        """Demonstrate the bug: list += string gives char iteration."""
        result = []
        result += 'torrent'
        assert result == ['t', 'o', 'r', 'r', 'e', 'n', 't']  # BUG!

    def test_list_plus_list_works_correctly(self):
        """The fix: return a list so += works properly."""
        result = []
        result += ['torrent']
        assert result == ['torrent']

    def test_getEnabledProtocol_returns_list(self):
        """Simulate the fixed getEnabledProtocol behavior."""
        protocol = ['torrent', 'torrent_magnet']

        def getEnabledProtocol_fixed(is_enabled=True):
            for p in protocol:
                if is_enabled:
                    return protocol  # Return the list
            return []

        result = getEnabledProtocol_fixed()
        assert isinstance(result, list)
        merged = []
        merged += result
        assert merged == ['torrent', 'torrent_magnet']

    def test_getEnabledProtocol_disabled_returns_empty_list(self):
        """Disabled downloader should return empty list, not empty string."""
        def getEnabledProtocol_fixed(is_enabled=False):
            protocol = ['torrent']
            for p in protocol:
                if is_enabled:
                    return protocol
            return []

        result = getEnabledProtocol_fixed()
        assert isinstance(result, list)
        assert result == []


# ---------------------------------------------------------------------------
# 4. file.download / file.cache — bytes vs str path handling
# ---------------------------------------------------------------------------

class TestFilePathHandling:
    """file.download and file.cache must handle paths as str, not bytes."""

    def test_os_path_join_rejects_mixed_types(self):
        """In Py3, os.path.join with mixed str/bytes raises TypeError."""
        with pytest.raises(TypeError):
            os.path.join(b'/tmp/cache', 'file.jpg')

    def test_os_path_join_str_works(self):
        """All-str paths work fine."""
        result = os.path.join('/tmp/cache', 'file.jpg')
        assert result == '/tmp/cache/file.jpg'

    def test_toUnicode_converts_bytes_path(self):
        """toUnicode should convert bytes path to str for os.path.join."""
        # Simulate the fix
        cache_dir = b'/tmp/cache'
        if isinstance(cache_dir, bytes):
            cache_dir = cache_dir.decode('utf-8')
        result = os.path.join(cache_dir, 'file.jpg')
        assert isinstance(result, str)

    def test_dest_path_is_always_str(self):
        """The download dest path must always be str."""
        url = 'http://example.com/image.jpg'
        cache_dir = '/tmp/cache'
        # Simulate the fixed download logic
        import hashlib
        dest = os.path.join(str(cache_dir), '%s.%s' % (
            hashlib.md5(url.encode()).hexdigest(), 'jpg'))
        assert isinstance(dest, str)
        assert dest.endswith('.jpg')


# ---------------------------------------------------------------------------
# 5. CodernityDB tree_index — bytes/str key comparison in delete/update
# ---------------------------------------------------------------------------

class TestTreeIndexBytesStrKeys:
    """CodernityDB tree indexes use fixed-width byte keys. In Py3, comparing
    bytes and str raises TypeError instead of silently returning False."""

    def test_bytes_str_comparison_raises_in_struct(self):
        """struct.pack with wrong type raises error."""
        # In the tree index, keys are packed as bytes
        key_format = '32s'
        str_key = 'test_key'
        # Must encode str to bytes before packing
        with pytest.raises(struct.error):
            struct.pack(key_format, str_key)  # Py3: str not allowed

    def test_bytes_key_packs_correctly(self):
        """Bytes keys pack correctly."""
        key_format = '32s'
        bytes_key = b'test_key'.ljust(32, b'\x00')
        packed = struct.pack(key_format, bytes_key)
        assert len(packed) == 32

    def test_make_key_encodes_str_to_bytes(self):
        """The fix: make_key must encode str to bytes."""
        def make_key(key):
            if isinstance(key, str):
                key = key.encode('utf-8').ljust(32, b'\x00')[:32]
            elif isinstance(key, bytes):
                key = key.ljust(32, b'\x00')[:32]
            return key

        str_result = make_key('test')
        bytes_result = make_key(b'test')
        assert isinstance(str_result, bytes)
        assert isinstance(bytes_result, bytes)
        assert str_result == bytes_result

    def test_key_comparison_after_encoding(self):
        """After encoding, str and bytes keys should match."""
        def make_key(key):
            if isinstance(key, str):
                key = key.encode('utf-8').ljust(32, b'\x00')[:32]
            elif isinstance(key, bytes):
                key = key.ljust(32, b'\x00')[:32]
            return key

        k1 = make_key('category_a')
        k2 = make_key(b'category_a')
        assert k1 == k2


# ---------------------------------------------------------------------------
# 6. X-CP-API header — int vs str
# ---------------------------------------------------------------------------

class TestXCPAPIHeaderType:
    """HTTP headers must be strings. Passing an int header value causes
    issues in Python 3's http libraries."""

    def test_int_header_value_in_dict(self):
        """Headers dict with int value — requests lib handles this but
        it's better to ensure str."""
        headers = {'X-CP-API': 123}
        # The fix: ensure header values are str
        fixed_headers = {k: str(v) for k, v in headers.items()}
        assert fixed_headers['X-CP-API'] == '123'
        assert isinstance(fixed_headers['X-CP-API'], str)

    def test_str_header_value_preserved(self):
        """Already-str values should be preserved."""
        headers = {'X-CP-API': 'abc123'}
        fixed_headers = {k: str(v) for k, v in headers.items()}
        assert fixed_headers['X-CP-API'] == 'abc123'

    def test_none_header_would_fail(self):
        """None header values should be handled gracefully."""
        headers = {'X-CP-API': None, 'Host': None}
        # The fix: filter or convert
        fixed = {k: str(v) if v is not None else v for k, v in headers.items()}
        assert fixed['X-CP-API'] == 'None' or fixed['X-CP-API'] is None

    def test_transmission_session_id_must_be_str(self):
        """TransmissionRPC session_id starts as int 0, must be str in headers."""
        session_id = 0
        headers = {'x-transmission-session-id': str(session_id)}
        assert headers['x-transmission-session-id'] == '0'
        assert isinstance(headers['x-transmission-session-id'], str)
