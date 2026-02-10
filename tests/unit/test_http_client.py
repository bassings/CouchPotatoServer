"""Tests for couchpotato.core.http_client.HttpClient"""
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from couchpotato.core.http_client import (
    HttpClient, DISABLE_DURATION, MAX_FAILURES_BEFORE_DISABLE,
    create_session, DEFAULT_RETRY_TOTAL, DEFAULT_POOL_CONNECTIONS, DEFAULT_POOL_MAXSIZE,
)


@pytest.fixture
def mock_env():
    """Patch Env for http_client tests."""
    mock_session = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.content = b'OK'
    mock_session.request.return_value = response
    # Make requests.codes.ok work
    response.status_code = requests.codes.ok

    with patch('couchpotato.core.http_client.Env') as env:
        env.get.return_value = mock_session
        env.setting.return_value = None  # no proxy by default
        yield env, mock_session, response


class TestHttpClient:

    def test_basic_get(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        result = client.request('http://example.com/test')
        assert result == b'OK'
        session.request.assert_called_once()
        args, kwargs = session.request.call_args
        assert args[0] == 'get'

    def test_post_with_data(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        result = client.request('http://example.com/test', data={'key': 'val'})
        assert result == b'OK'
        args, kwargs = session.request.call_args
        assert args[0] == 'post'

    def test_stream_returns_response(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        result = client.request('http://example.com/test', stream=True)
        assert result == response

    def test_failure_tracking(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        client._record_failure('example.com')
        assert client.failed_request['example.com'] == 1
        client._record_failure('example.com')
        assert client.failed_request['example.com'] == 2

    def test_host_disabled_after_threshold(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        with patch('couchpotato.core.http_client.isLocalIP', return_value=False):
            for _ in range(MAX_FAILURES_BEFORE_DISABLE + 1):
                client._record_failure('remote.com')
        assert 'remote.com' in client.failed_disabled

    def test_host_not_disabled_for_local(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        with patch('couchpotato.core.http_client.isLocalIP', return_value=True):
            for _ in range(MAX_FAILURES_BEFORE_DISABLE + 1):
                client._record_failure('127.0.0.1')
        assert '127.0.0.1' not in client.failed_disabled

    def test_429_immediately_disables(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        client._record_failure('api.example.com', status_code=429)
        assert client.failed_disabled.get('api.example.com', 0) > 0

    def test_disabled_host_returns_empty(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        client.failed_disabled['example.com'] = time.time()
        result = client.request('http://example.com/test', show_error=True)
        assert result == ''
        session.request.assert_not_called()

    def test_disabled_host_raises_when_no_show_error(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        client.failed_disabled['example.com'] = time.time()
        with pytest.raises(Exception, match='Disabled calls'):
            client.request('http://example.com/test', show_error=False)

    def test_disabled_host_re_enabled_after_timeout(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        client.failed_disabled['example.com'] = time.time() - DISABLE_DURATION - 1
        client.failed_request['example.com'] = 10
        result = client.request('http://example.com/test')
        assert result == b'OK'
        assert 'example.com' not in client.failed_disabled

    def test_proxy_config_with_server(self, mock_env):
        env, session, response = mock_env
        env.setting.side_effect = lambda key: {
            'use_proxy': True, 'proxy_server': 'proxy.local:8080',
            'proxy_username': 'user', 'proxy_password': 'pass',
        }.get(key)
        client = HttpClient()
        proxies = client._get_proxy_config()
        assert 'http' in proxies
        assert 'user:pass@proxy.local:8080' in proxies['http']

    def test_default_headers_set(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        client.request('http://example.com/path')
        _, kwargs = session.request.call_args
        headers = kwargs['headers']
        assert 'User-Agent' in headers
        assert headers['Accept-encoding'] == 'gzip'

    def test_rate_limiting_no_delay_when_zero(self, mock_env):
        """With time_between_calls=0, wait should be a no-op."""
        env, session, response = mock_env
        client = HttpClient(time_between_calls=0)
        # Should not block
        client._wait_for_rate_limit('example.com', 'http://example.com')

    def test_shutdown_flag(self, mock_env):
        env, session, response = mock_env
        client = HttpClient()
        assert not client._shutting_down
        client.shutdown()
        assert client._shutting_down

    def test_concurrent_record_failure_no_corruption(self, mock_env):
        """Concurrent _record_failure calls should not corrupt shared dicts."""
        env, session, response = mock_env
        client = HttpClient()
        errors = []

        def record_many(host_suffix):
            try:
                for i in range(100):
                    client._record_failure(f'host-{host_suffix}.com')
            except Exception as e:
                errors.append(e)

        with patch('couchpotato.core.http_client.isLocalIP', return_value=False):
            threads = [threading.Thread(target=record_many, args=(i,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert not errors
        # Each host should have exactly 100 failures recorded
        for i in range(10):
            assert client.failed_request[f'host-{i}.com'] == 100

    def test_concurrent_check_disabled_no_crash(self, mock_env):
        """Concurrent _check_disabled calls should not raise."""
        env, session, response = mock_env
        client = HttpClient()
        errors = []

        # Pre-populate some disabled hosts
        for i in range(5):
            client.failed_disabled[f'host-{i}.com'] = time.time()
        for i in range(5, 10):
            client.failed_disabled[f'host-{i}.com'] = time.time() - DISABLE_DURATION - 1

        def check_many():
            try:
                for i in range(10):
                    client._check_disabled(f'host-{i}.com')
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=check_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


class TestCreateSession:
    """Tests for create_session with HTTPAdapter, retry, and connection pooling."""

    def test_session_has_adapters_mounted(self):
        session = create_session()
        http_adapter = session.get_adapter('http://example.com')
        https_adapter = session.get_adapter('https://example.com')
        from requests.adapters import HTTPAdapter
        assert isinstance(http_adapter, HTTPAdapter)
        assert isinstance(https_adapter, HTTPAdapter)

    def test_retry_config(self):
        session = create_session(retry_total=5, retry_backoff=1.0)
        adapter = session.get_adapter('https://example.com')
        assert adapter.max_retries.total == 5
        assert adapter.max_retries.backoff_factor == 1.0
        assert 502 in adapter.max_retries.status_forcelist

    def test_pool_sizing(self):
        session = create_session(pool_connections=20, pool_maxsize=30)
        adapter = session.get_adapter('https://example.com')
        assert adapter._pool_connections == 20
        assert adapter._pool_maxsize == 30

    def test_default_values(self):
        session = create_session()
        adapter = session.get_adapter('https://example.com')
        assert adapter.max_retries.total == DEFAULT_RETRY_TOTAL
        assert adapter._pool_connections == DEFAULT_POOL_CONNECTIONS
        assert adapter._pool_maxsize == DEFAULT_POOL_MAXSIZE

    def test_max_redirects(self):
        session = create_session()
        assert session.max_redirects == 5


class TestRateLimitEventWait:
    """Tests for event-based rate limiting (no busy-wait)."""

    def test_rate_event_exists(self):
        client = HttpClient(time_between_calls=1)
        assert hasattr(client, '_rate_event')
        assert isinstance(client._rate_event, threading.Event)

    def test_no_busy_wait_in_source(self):
        import inspect
        source = inspect.getsource(HttpClient._wait_for_rate_limit)
        assert 'time.sleep(0.1)' not in source
        assert '_rate_event' in source

    def test_rate_limit_sequential(self, mock_env):
        env, session, response = mock_env
        client = HttpClient(time_between_calls=0.05)
        client.request('http://example.com/a')
        client.request('http://example.com/b')
        assert session.request.call_count == 2

    def test_rate_limit_concurrent(self, mock_env):
        env, session, response = mock_env
        client = HttpClient(time_between_calls=0.05)
        results = []

        def do_req(path):
            client.request(f'http://example.com/{path}')
            results.append(path)

        threads = [threading.Thread(target=do_req, args=(f'p{i}',)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert len(results) == 3

    def test_shutdown_breaks_wait(self):
        client = HttpClient(time_between_calls=100)
        client.last_use_queue['host'] = ['other_url']
        client.last_use['host'] = time.time()

        def wait_then_shutdown():
            time.sleep(0.1)
            client.shutdown()

        t = threading.Thread(target=wait_then_shutdown)
        t.start()
        client._wait_for_rate_limit('host', 'my_url')
        t.join(timeout=5)

    def test_except_clause_no_typeerror(self):
        """Verify except clause doesn't catch non-BaseException classes (regression).

        Previously, urllib3.Timeout (a non-exception utility class) was in the
        except tuple, causing TypeError on Python 3.10+.
        """
        import ast, inspect, textwrap
        import couchpotato.core.http_client as mod
        source = textwrap.dedent(inspect.getsource(mod.HttpClient.request))
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type:
                # Collect all exception names in except clauses
                names = []
                if isinstance(node.type, ast.Tuple):
                    for elt in node.type.elts:
                        if isinstance(elt, ast.Name):
                            names.append(elt.id)
                elif isinstance(node.type, ast.Name):
                    names.append(node.type.id)
                # urllib3.Timeout is NOT an exception class — must not appear
                assert 'Timeout' not in names, \
                    'except clause catches urllib3.Timeout which is not a BaseException subclass'
