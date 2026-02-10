"""Tests for cache stampede prevention in Plugin.getCache."""
import threading
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from couchpotato.core.plugins.base import Plugin


@pytest.fixture
def plugin_with_cache():
    """Create a Plugin instance with mocked cache and HTTP client."""
    # Reset class-level lock registry
    Plugin._cache_locks = {}

    with patch('couchpotato.core.plugins.base.addEvent'):
        plugin = Plugin.__new__(Plugin)
        plugin.registerPlugin()

    mock_cache = MagicMock()
    mock_cache.get.return_value = None  # cache miss by default

    with patch('couchpotato.core.plugins.base.Env') as mock_env:
        mock_env.get.side_effect = lambda key: {
            'cache': mock_cache,
            'dev': False,
        }.get(key)

        plugin._http_client = MagicMock()
        plugin._http_client.request.return_value = b'fetched_data'

        yield plugin, mock_cache, mock_env


class TestCacheStampedePrevention:

    def test_single_fetch_on_concurrent_access(self, plugin_with_cache):
        """Only one thread should fetch when multiple request the same uncached key."""
        plugin, mock_cache, mock_env = plugin_with_cache

        fetch_count = {'n': 0}
        fetch_lock = threading.Lock()

        original_urlopen = plugin.urlopen

        def slow_urlopen(url, **kwargs):
            with fetch_lock:
                fetch_count['n'] += 1
            time.sleep(0.1)  # Simulate slow fetch
            return b'data'

        plugin.urlopen = slow_urlopen

        # After first fetch, cache should return data
        call_count = {'n': 0}
        def smart_cache_get(key):
            with fetch_lock:
                call_count['n'] += 1
                # Return None first time (per thread), then data after set
                if call_count['n'] <= 5:  # first wave all miss
                    return None
                return b'data'

        mock_cache.get.side_effect = smart_cache_get

        results = []
        errors = []

        def get_cached(i):
            try:
                result = plugin.getCache(f'test_key', url='http://example.com/data')
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_cached, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        assert len(results) == 5
        # Only one thread should have actually fetched
        assert fetch_count['n'] == 1

    def test_cache_hit_skips_lock(self, plugin_with_cache):
        """Cache hit should return immediately without locking."""
        plugin, mock_cache, mock_env = plugin_with_cache
        mock_cache.get.return_value = b'cached_value'

        result = plugin.getCache('key1', url='http://example.com')
        assert result == b'cached_value'
        # urlopen should NOT be called
        plugin._http_client.request.assert_not_called()

    def test_lock_cleanup(self, plugin_with_cache):
        """Cache lock for a key should be cleaned up after fetch."""
        plugin, mock_cache, mock_env = plugin_with_cache

        plugin.urlopen = lambda url, **kw: b'data'

        plugin.getCache('cleanup_key', url='http://example.com')

        # Lock should be removed from registry
        from couchpotato.core.helpers.variable import md5
        key_md5 = md5('cleanup_key')
        assert key_md5 not in Plugin._cache_locks

    def test_different_keys_dont_block(self, plugin_with_cache):
        """Different cache keys should not block each other."""
        plugin, mock_cache, mock_env = plugin_with_cache

        fetch_order = []

        def urlopen(url, **kwargs):
            fetch_order.append(url)
            time.sleep(0.05)
            return b'data'

        plugin.urlopen = urlopen

        threads = [
            threading.Thread(target=lambda: plugin.getCache('key_a', url='http://a.com')),
            threading.Thread(target=lambda: plugin.getCache('key_b', url='http://b.com')),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Both should have been fetched (not blocked by each other)
        assert len(fetch_order) == 2

    def test_post_request_bypasses_cache(self, plugin_with_cache):
        """POST requests (with data) should bypass cache entirely."""
        plugin, mock_cache, mock_env = plugin_with_cache
        plugin.urlopen = lambda url, **kw: b'post_result'

        result = plugin.getCache('post_key', url='http://example.com', data={'x': 1})
        assert result == b'post_result'
        # Cache should not be checked or set
        mock_cache.get.assert_not_called()
