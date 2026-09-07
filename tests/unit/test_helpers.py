"""Tests for CouchPotato utility/helper functions.

Tests encoding helpers (toUnicode, toSafeString, simplifyString)
and variable helpers (tryInt, tryFloat, getImdb, etc.).
"""
import os

import pytest

from couchpotato.core.helpers.encoding import toUnicode, toSafeString, simplifyString
from couchpotato.core.helpers.variable import removePyc, tryInt, getImdb, isLocalIP

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


class TestRemovePyc:
    """removePyc() runs at CouchPotato.py import time, before anything else
    -- an unhandled exception here crashes the whole process before a
    single log line is written.

    T1.7 (E2E per-worker isolation) starts multiple CouchPotato.py
    processes concurrently against the SAME checkout: every worker's
    process walks and cleans the identical couchpotato/**/__pycache__
    tree. Measured directly: with `--workers=3`, a second process's
    os.listdir() on a __pycache__ directory a FIRST process had just
    emptied and os.rmdir()'d raised an unhandled FileNotFoundError,
    killing that worker's server before it ever bound a port -- with
    tests/e2e/fixtures.ts's readiness check correctly turning that into
    "the application under test exited", but a genuinely avoidable one.

    removePyc's own os.remove() call two lines above is already wrapped in
    try/except Exception (line-for-line the same defensive shape this test
    pins for os.listdir/os.rmdir) -- this is completing a pattern already
    established in the function, not introducing a new one.
    """

    def test_tolerates_a_directory_vanishing_between_walk_and_listdir(self, tmp_path, monkeypatch):
        # Simulate the race directly: os.walk() has already yielded this
        # directory's name, but a concurrent process deletes it before
        # THIS call reaches os.listdir(). Everything else in the tree is
        # real, so only the raced directory is faked.
        pkg_dir = tmp_path / 'pkg'
        pkg_dir.mkdir()
        cache_dir = pkg_dir / '__pycache__'
        cache_dir.mkdir()
        (cache_dir / 'mod.cpython-314.pyc').write_text('stale bytecode')
        (pkg_dir / 'mod.py').write_text('# real source')

        real_listdir = os.listdir

        def racy_listdir(path):
            if os.path.abspath(path) == os.path.abspath(str(cache_dir)):
                raise FileNotFoundError(2, 'No such file or directory', str(cache_dir))
            return real_listdir(path)

        monkeypatch.setattr(os, 'listdir', racy_listdir)

        # Must not raise -- this is the exact crash observed under
        # concurrent workers.
        removePyc(str(tmp_path), show_logs=False)

    def test_tolerates_a_directory_vanishing_before_rmdir(self, tmp_path, monkeypatch):
        # A narrower window of the same race: os.listdir() succeeds (sees
        # an empty dir) but a concurrent process removes the directory
        # before THIS call's own os.rmdir() runs.
        pkg_dir = tmp_path / 'pkg'
        pkg_dir.mkdir()
        cache_dir = pkg_dir / '__pycache__'
        cache_dir.mkdir()

        real_rmdir = os.rmdir

        def racy_rmdir(path):
            if os.path.abspath(path) == os.path.abspath(str(cache_dir)):
                raise FileNotFoundError(2, 'No such file or directory', str(cache_dir))
            return real_rmdir(path)

        monkeypatch.setattr(os, 'rmdir', racy_rmdir)

        removePyc(str(tmp_path), show_logs=False)

    def test_still_removes_excess_pyc_in_the_non_racy_case(self, tmp_path):
        # The guard must not make removePyc a no-op -- its actual job
        # (delete a .pyc with no matching .py) still has to happen when
        # nothing races it.
        #
        # The now-empty __pycache__ dir is NOT pruned on this same call:
        # os.walk() is top-down, so a directory's emptiness is checked
        # while visiting its PARENT, before the walk has descended into it
        # and deleted its .pyc files -- pre-existing behaviour, unrelated
        # to this guard, confirmed separately below (it takes a second
        # call, i.e. the next process restart, to prune it).
        pkg_dir = tmp_path / 'pkg'
        pkg_dir.mkdir()
        cache_dir = pkg_dir / '__pycache__'
        cache_dir.mkdir()
        stale_pyc = cache_dir / 'orphan.cpython-314.pyc'
        stale_pyc.write_text('stale bytecode, no matching orphan.py')

        removePyc(str(tmp_path), show_logs=False)

        assert not stale_pyc.exists()

    def test_prunes_an_empty_pycache_dir_left_over_from_a_prior_call(self, tmp_path):
        # Completes the case above: a __pycache__ left empty by an EARLIER
        # removePyc call (or process exit) is pruned on the next one.
        pkg_dir = tmp_path / 'pkg'
        pkg_dir.mkdir()
        cache_dir = pkg_dir / '__pycache__'
        cache_dir.mkdir()

        removePyc(str(tmp_path), show_logs=False)

        assert not cache_dir.exists()


class TestIsLocalIP:
    """isLocalIP() used to embed a JAVASCRIPT regex literal (the wrapping
    '/../' delimiters) directly in a Python re.search() call. In Python
    those slashes are literal characters, not delimiters, so two of the
    seven alternatives could never match: one needed a literal '/' before
    '^' (start of string) and one needed a literal '/' after '$' (end of
    string). The practical effect was that IPv6 loopback ('::1') was never
    recognised by the regex -- only the standalone http_client.py caller
    matters here (couchpotato/core/http_client.py:131, which exempts local
    hosts from being permanently disabled after repeated failures), so an
    IPv6-only local service got disabled where the same service on
    127.0.0.1 would not.

    These tests pin the full table, including the cases that already
    passed, so the fix cannot regress them.
    """

    # -- IPv4 loopback and private ranges (already worked before the fix) --

    def test_ipv4_loopback_is_local(self):
        assert isLocalIP('127.0.0.1') is True

    def test_ipv4_class_c_private_is_local(self):
        assert isLocalIP('192.168.1.10') is True

    def test_ipv4_class_a_private_is_local(self):
        assert isLocalIP('10.0.0.5') is True

    def test_hostname_localhost_is_local(self):
        assert isLocalIP('localhost') is True

    # -- 172.16.0.0/12: the real private range is 172.16.x through 172.31.x --

    def test_172_16_lower_bound_is_local(self):
        assert isLocalIP('172.16.0.1') is True

    def test_172_20_mid_range_is_local(self):
        assert isLocalIP('172.20.5.5') is True

    def test_172_31_upper_bound_is_local(self):
        assert isLocalIP('172.31.255.255') is True

    def test_172_15_just_below_range_is_not_local(self):
        assert isLocalIP('172.15.0.1') is False

    def test_172_32_just_above_range_is_not_local(self):
        assert isLocalIP('172.32.0.1') is False

    # -- public addresses stay public --

    def test_public_ip_google_dns_is_not_local(self):
        assert isLocalIP('8.8.8.8') is False

    def test_arbitrary_public_ip_is_not_local(self):
        assert isLocalIP('1.2.3.4') is False

    # -- IPv6 loopback: THE BUG. Was False before the fix. --

    def test_ipv6_loopback_shorthand_is_local(self):
        assert isLocalIP('::1') is True

    def test_ipv6_loopback_full_form_is_local(self):
        # '0:0:0:0:0:0:0:1' is the same address as '::1' written without
        # zero-compression. Supported deliberately: a client library is as
        # likely to hand us one form as the other, and refusing the
        # uncompressed form would just re-introduce the same class of bug
        # for a differently-formatted address. Deliberately NOT attempting
        # general IPv6 canonicalisation (case folding, partial compression
        # like '0:0:0:0:0:0:0:01', mixed forms) -- that is a much bigger
        # surface for false positives than this helper's job justifies.
        assert isLocalIP('0:0:0:0:0:0:0:1') is True

    # -- anchoring: must not match the pattern mid-string --

    def test_public_ip_followed_by_private_looking_text_is_not_local(self):
        # A careless (unanchored) alternation could match '10.0.0.1'
        # wherever it appears in the string, not just at the start.
        assert isLocalIP('8.8.8.8 via 10.0.0.1') is False

    def test_hostname_containing_loopback_looking_text_is_not_local(self):
        # '127.0.0.1' appears in this string but not at the start, and the
        # whole thing is a hostname, not a loopback address.
        assert isLocalIP('not-127.0.0.1.example.com') is False
