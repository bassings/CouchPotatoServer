"""Tests for CouchPotato utility/helper functions.

Tests encoding helpers (toUnicode, toSafeString, simplifyString)
and variable helpers (tryInt, tryFloat, getImdb, etc.).
"""
import os

import pytest

from couchpotato.core.helpers.encoding import toUnicode, toSafeString, simplifyString
from couchpotato.core.helpers.variable import removePyc, tryInt, getImdb

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
