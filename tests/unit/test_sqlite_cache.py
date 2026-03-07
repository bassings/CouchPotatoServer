"""Tests for the SQLiteCache replacement for diskcache."""

import os
import tempfile
import time

import pytest

from couchpotato.core.cache import SQLiteCache


@pytest.fixture
def cache_dir(tmp_path):
    return str(tmp_path / 'cache')


@pytest.fixture
def cache(cache_dir):
    c = SQLiteCache(cache_dir)
    yield c
    c.close()


class TestSQLiteCacheBasics:
    def test_get_missing_key_returns_none(self, cache):
        assert cache.get('nonexistent') is None

    def test_get_missing_key_returns_default(self, cache):
        assert cache.get('nonexistent', 'fallback') == 'fallback'

    def test_set_and_get_string(self, cache):
        cache.set('key1', 'hello')
        assert cache.get('key1') == 'hello'

    def test_set_and_get_dict(self, cache):
        data = {'name': 'test', 'count': 42, 'nested': [1, 2, 3]}
        cache.set('key2', data)
        assert cache.get('key2') == data

    def test_set_and_get_list(self, cache):
        cache.set('key3', [1, 'two', 3.0])
        assert cache.get('key3') == [1, 'two', 3.0]

    def test_set_and_get_number(self, cache):
        cache.set('int', 42)
        cache.set('float', 3.14)
        assert cache.get('int') == 42
        assert cache.get('float') == 3.14

    def test_set_and_get_bool(self, cache):
        cache.set('flag', True)
        assert cache.get('flag') is True

    def test_set_and_get_none_value(self, cache):
        cache.set('null', None)
        assert cache.get('null') is None
        # Distinguishing None-value from missing requires default
        assert cache.get('null', 'MISSING') is None

    def test_overwrite_value(self, cache):
        cache.set('key', 'first')
        cache.set('key', 'second')
        assert cache.get('key') == 'second'


class TestSQLiteCacheExpiry:
    def test_expired_entry_returns_none(self, cache):
        cache.set('temp', 'value', expire=0.1)
        time.sleep(0.15)
        assert cache.get('temp') is None

    def test_non_expired_entry_returns_value(self, cache):
        cache.set('temp', 'value', expire=10)
        assert cache.get('temp') == 'value'

    def test_no_expiry_persists(self, cache):
        cache.set('permanent', 'value')
        # No sleep needed — no expiry means it stays forever
        assert cache.get('permanent') == 'value'


class TestSQLiteCacheOperations:
    def test_delete(self, cache):
        cache.set('key', 'value')
        cache.delete('key')
        assert cache.get('key') is None

    def test_delete_nonexistent_is_safe(self, cache):
        cache.delete('nonexistent')  # should not raise

    def test_clear(self, cache):
        cache.set('a', 1)
        cache.set('b', 2)
        cache.clear()
        assert cache.get('a') is None
        assert cache.get('b') is None

    def test_close_and_reopen(self, cache_dir):
        c1 = SQLiteCache(cache_dir)
        c1.set('persist', 'value')
        c1.close()

        c2 = SQLiteCache(cache_dir)
        assert c2.get('persist') == 'value'
        c2.close()


class TestSQLiteCacheEviction:
    def test_eviction_cleans_expired(self, cache_dir):
        cache = SQLiteCache(cache_dir, eviction_interval=0)  # evict every call
        cache.set('old', 'stale', expire=0.1)
        cache.set('fresh', 'good', expire=60)
        time.sleep(0.15)
        # Trigger eviction via a get
        cache.get('anything')
        # Old entry should be gone from DB too
        assert cache.get('old') is None
        assert cache.get('fresh') == 'good'
        cache.close()


class TestSQLiteCacheEdgeCases:
    def test_non_serialisable_value_skipped(self, cache):
        # Sets with a non-JSON-serialisable object should not raise
        cache.set('bad', object())
        assert cache.get('bad') is None

    def test_creates_directory(self, tmp_path):
        nested = str(tmp_path / 'a' / 'b' / 'c')
        c = SQLiteCache(nested)
        c.set('key', 'value')
        assert c.get('key') == 'value'
        c.close()

    def test_empty_string_key(self, cache):
        cache.set('', 'empty_key')
        assert cache.get('') == 'empty_key'

    def test_large_value(self, cache):
        big = 'x' * 100_000
        cache.set('big', big)
        assert cache.get('big') == big
