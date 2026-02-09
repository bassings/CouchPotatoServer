"""Tests for couchpotato.core.http_client.HttpClient"""
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from couchpotato.core.http_client import HttpClient, DISABLE_DURATION, MAX_FAILURES_BEFORE_DISABLE


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
