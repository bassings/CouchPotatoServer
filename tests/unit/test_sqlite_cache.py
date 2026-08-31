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


class TestSQLiteCacheBytes:
    """T67: HTTPClient.request returns bytes (its own docstring says so),
    and getJsonData / getRSSData hand that response body to the cache
    unchanged. A bytes value must round trip, because a value stored as
    bytes and read back as anything else silently corrupts every cached
    HTTP response body.
    """

    def test_set_and_get_bytes(self, cache):
        raw = b'{"ok": true}'
        cache.set('http-body', raw)
        assert cache.get('http-body') == raw

    def test_bytes_round_trip_preserves_type(self, cache):
        cache.set('key', b'hello world')
        result = cache.get('key')
        assert isinstance(result, bytes), (
            'cache.get returned %r, not bytes -- a caller that expects the '
            'exact type urlopen returned will misbehave' % type(result)
        )

    def test_non_utf8_bytes_round_trip_exactly(self, cache):
        # HTTP response bodies are not guaranteed to be UTF-8 text. A lossy
        # decode-to-store would silently corrupt a cached response, which is
        # worse than not caching it at all -- 0xff 0xfe is not valid UTF-8,
        # so this fails loudly if the fix assumes utf-8 rather than
        # preserving the exact bytes.
        raw = b'\xff\xfe\x00\x01binary\x02\xfd\x80garbage'
        cache.set('http-body-binary', raw)
        assert cache.get('http-body-binary') == raw

    def test_empty_bytes_round_trip(self, cache):
        cache.set('empty-body', b'')
        assert cache.get('empty-body') == b''


class TestSQLiteCacheReportsUnstorableValues:
    """T67 part two: the silent skip is the real defect and outlives
    whatever encoding fix bytes gets. A value the cache genuinely cannot
    store (no JSON representation, and not bytes) must be reported at a
    level somebody actually sees, not log.debug -- otherwise the next
    unserialisable type repeats this exact incident.
    """

    def test_unstorable_object_is_reported_above_debug(self, cache, caplog):
        class Unrepresentable:
            """No JSON representation, and not bytes."""

        with caplog.at_level('WARNING'):
            cache.set('bad-key', Unrepresentable())

        # still not stored -- the guard is about visibility, not persistence
        assert cache.get('bad-key') is None

        reported = [r for r in caplog.records if r.name == 'couchpotato.core.cache']
        assert reported, (
            'cache.set silently dropped a value it could not store -- '
            'nothing was logged at WARNING or above'
        )
        assert 'bad-key' in caplog.text, (
            'the report does not name the key, so nobody can act on it'
        )

    def test_unstorable_set_value_is_reported_above_debug(self, cache, caplog):
        # a python set has no JSON representation
        with caplog.at_level('WARNING'):
            cache.set('bad-set', {1, 2, 3})

        assert cache.get('bad-set') is None

        reported = [r for r in caplog.records if r.name == 'couchpotato.core.cache']
        assert reported, (
            'cache.set silently dropped a set value -- nothing was logged '
            'at WARNING or above'
        )

    def test_unstorable_value_does_not_raise(self, cache):
        # The cache must not turn a caching failure into a request failure --
        # setCache is called from inside a fetch that already has the data
        # in hand; raising here would discard a successful fetch just
        # because that fetch's result could not be cached.
        class Unrepresentable:
            pass

        cache.set('bad-key-2', Unrepresentable())  # must not raise


class TestSQLiteCacheFilePermissions:
    """M2 (branch review 2026-08-31): fixing T67's dead cache turned it into
    a LIVE on-disk store. What actually reaches `cache.set` is HTTP response
    bodies -- Torznab/Jackett responses routinely embed the indexer's own
    API key in a `<link>` element -- and the review measured the created
    file at mode 0644, world-readable, on a box that runs unattended.

    Nothing here asserts about retention or eviction timing (the review's
    other two suggested changes) -- only the part that is unambiguously
    wrong regardless of what the cache is allowed to hold: a file that can
    contain another service's credentials must not be readable by every
    other account on the machine.
    """

    def test_the_cache_directory_is_created_private(self, cache_dir, cache):
        mode = os.stat(cache_dir).st_mode & 0o777
        assert mode == 0o700, (
            'the cache directory %r was created with mode %o -- it must be '
            '0700 (owner-only) because cache.db can hold indexer API keys '
            'embedded in cached provider response bodies (M2, branch '
            'review 2026-08-31)' % (cache_dir, mode)
        )

    def test_every_file_in_the_cache_directory_is_created_private(
        self, cache_dir, cache,
    ):
        """T7d item 5, round two on M2. This test used to name `cache.db`
        alone and assert on it exclusively -- which passed while missing
        the actual leak the review measured. The cache runs in WAL mode
        (`cache.py:70`), so a recent write does not necessarily land in
        `cache.db` at all: it can sit in `cache.db-wal` until the next
        checkpoint, and `cache.db-shm` is the shared-memory index SQLite
        keeps beside it. Only `cache.db` was ever chmod'd, so with a plain
        022 umask `cache.db-wal` and `cache.db-shm` are created at 0644 --
        world-readable -- and it is `cache.db-wal`, not `cache.db`, that
        actually holds a just-cached credential most of the time. Naming
        one file let this test stay green while the secret sat in a
        readable sibling; it must instead cover every file the cache
        directory contains, whatever SQLite decides to name it.
        """
        old_umask = os.umask(0o022)
        try:
            cache.set(
                'k1', b'<rss><link>http://indexer/dl?apikey=SECRET</link></rss>',
            )

            entries = sorted(os.listdir(cache_dir))
            assert entries, (
                'fixture broken: the cache directory is empty after a set()'
            )

            offending = []
            for name in entries:
                path = os.path.join(cache_dir, name)
                if not os.path.isfile(path):
                    continue
                mode = os.stat(path).st_mode & 0o777
                if mode != 0o600:
                    offending.append((name, oct(mode)))

            assert not offending, (
                'the following cache directory files were left readable '
                'by group/other (0600 required, umask 022 in effect): %r '
                '-- a Torznab/Jackett response body cached here routinely '
                'embeds the indexer\'s own API key, and under WAL mode a '
                'just-written credential can sit in `cache.db-wal` rather '
                'than `cache.db` itself (M2, branch review 2026-08-31, '
                'round two)' % (offending,)
            )
        finally:
            os.umask(old_umask)

    def test_a_chmod_failure_is_logged_rather_than_silently_swallowed(
        self, cache_dir, monkeypatch, caplog,
    ):
        """The current `except OSError: pass` around every chmod call in
        `SQLiteCache.__init__` means a filesystem that ignores or refuses
        chmod (a permission-stripping network mount, a filesystem mounted
        without POSIX permission support) silently loses every one of
        these protections with nothing anywhere to say so. A guard that
        fails must say that it failed.
        """
        import logging

        def _always_fails(*args, **kwargs):
            raise OSError(1, 'Operation not permitted')

        monkeypatch.setattr(os, 'chmod', _always_fails)

        with caplog.at_level(logging.WARNING):
            cache = SQLiteCache(cache_dir)
            try:
                cache.set('k1', 'v1')
            finally:
                cache.close()

        messages = [r.getMessage() for r in caplog.records]
        assert any('chmod' in m.lower() or 'permission' in m.lower()
                   for m in messages), (
            'every chmod call that protects the cache directory and its '
            'files failed, and nothing was logged about it -- an operator '
            'on a filesystem that ignores chmod has no way to know these '
            'protections silently do not apply. Messages were: %r'
            % messages
        )
