"""Task 17: API authentication tests.

Complements test_security.py with focused auth scenario testing.
"""
import os
import json
import time
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from couchpotato.api import addApiView, api, api_locks, api_nonblock, api_docs, api_docs_missing
from couchpotato.environment import Env


API_KEY = 'testkey123abc'


@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """Set up minimal Env for testing."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    Env.set('web_base', '/')
    Env.set('api_base', f'/api/{API_KEY}/')
    Env.set('static_path', '/static/')
    Env.set('app_dir', os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    Env.set('dev', False)

    settings_data = {
        'username': '',
        'password': '',
        'api_key': API_KEY,
        'dark_theme': False,
        'rate_limit_max': 0,
        'rate_limit_window': 60,
        'cors_origins': '',
    }

    original_setting = Env.setting

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            settings_data[key] = kwargs['value']
            return
        if key in settings_data:
            return settings_data[key]
        return kwargs.get('default', '')

    with patch.object(Env, 'setting', side_effect=mock_setting):
        # Register a test handler
        addApiView('test.echo', lambda **kw: {'success': True, 'params': kw})
        addApiView('test.data', lambda **kw: {'success': True, 'data': 'hello'})
        yield settings_data

    # Restore
    api.clear()
    api.update(old_api)
    api_locks.clear()
    api_locks.update(old_locks)
    api_nonblock.clear()
    api_nonblock.update(old_nonblock)
    api_docs.clear()
    api_docs.update(old_docs)
    api_docs_missing.clear()
    api_docs_missing.extend(old_missing)


@pytest.fixture
def client(setup_env):
    from couchpotato import create_app
    with patch.object(Env, 'setting') as mock_s:
        mock_s.side_effect = lambda key=None, *a, **kw: setup_env.get(key, kw.get('default', ''))
        app = create_app(api_key=API_KEY, web_base='/')
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def rate_limited_client(setup_env):
    setup_env['rate_limit_max'] = 5
    setup_env['rate_limit_window'] = 60
    from couchpotato import create_app
    with patch.object(Env, 'setting') as mock_s:
        mock_s.side_effect = lambda key=None, *a, **kw: setup_env.get(key, kw.get('default', ''))
        app = create_app(api_key=API_KEY, web_base='/')
    return TestClient(app, raise_server_exceptions=False)


class TestAPIKeyInURL:
    """Valid API key embedded in URL path."""

    def test_valid_key_in_url(self, client):
        r = client.get(f'/api/{API_KEY}/test.echo')
        assert r.status_code == 200
        data = r.json()
        assert data['success'] is True

    def test_valid_key_url_with_params(self, client):
        r = client.get(f'/api/{API_KEY}/test.echo?foo=bar')
        assert r.status_code == 200

    def test_valid_key_url_post(self, client):
        r = client.post(f'/api/{API_KEY}/test.data')
        assert r.status_code == 200


class TestAPIKeyInHeader:
    """Valid API key via X-Api-Key header."""

    def test_valid_header_key(self, client):
        r = client.get('/api/test.echo', headers={'X-Api-Key': API_KEY})
        assert r.status_code == 200
        assert r.json()['success'] is True

    def test_valid_header_key_post(self, client):
        r = client.post('/api/test.data', headers={'X-Api-Key': API_KEY})
        assert r.status_code == 200


class TestInvalidKey:
    """Invalid API key returns 401."""

    def test_invalid_key_in_url(self, client):
        r = client.get('/api/wrongkey/test.echo')
        assert r.status_code == 401

    def test_invalid_key_in_header(self, client):
        r = client.get('/api/test.echo', headers={'X-Api-Key': 'wrongkey'})
        assert r.status_code == 401

    def test_empty_key_in_header(self, client):
        r = client.get('/api/test.echo', headers={'X-Api-Key': ''})
        assert r.status_code == 401


class TestMissingKey:
    """Missing API key returns 401."""

    def test_no_key_at_all(self, client):
        r = client.get('/api/test.echo')
        assert r.status_code == 401

    def test_no_key_post(self, client):
        r = client.post('/api/test.echo')
        assert r.status_code == 401


class TestHeaderPreferredOverURL:
    """When both header and URL key are present, header takes priority."""

    def test_header_correct_url_wrong(self, client):
        """Valid header + wrong URL key → should succeed (header wins)."""
        r = client.get('/api/wrongkey/test.echo', headers={'X-Api-Key': API_KEY})
        assert r.status_code == 200

    def test_header_wrong_url_correct(self, client):
        """Wrong header + valid URL key → should fail (header wins)."""
        r = client.get(f'/api/{API_KEY}/test.echo', headers={'X-Api-Key': 'wrongkey'})
        assert r.status_code == 401

    def test_both_correct(self, client):
        """Both valid → should succeed."""
        r = client.get(f'/api/{API_KEY}/test.echo', headers={'X-Api-Key': API_KEY})
        assert r.status_code == 200


class TestRateLimiting:
    """Rate limiting kicks in after threshold."""

    def test_under_limit_succeeds(self, rate_limited_client):
        for _ in range(5):
            r = rate_limited_client.get(f'/api/{API_KEY}/test.echo')
            assert r.status_code == 200

    def test_over_limit_returns_429(self, rate_limited_client):
        # Use up the limit
        for _ in range(5):
            rate_limited_client.get(f'/api/{API_KEY}/test.echo')
        # Next request should be rate limited
        r = rate_limited_client.get(f'/api/{API_KEY}/test.echo')
        assert r.status_code == 429
        assert 'rate limit' in r.json().get('error', '').lower()

    def test_rate_limit_per_ip(self, rate_limited_client):
        """Rate limiting should be per-IP."""
        # All TestClient requests come from same IP, so after 5 they're limited
        for _ in range(5):
            rate_limited_client.get(f'/api/{API_KEY}/test.echo')
        r = rate_limited_client.get(f'/api/{API_KEY}/test.echo')
        assert r.status_code == 429


class TestEdgeCases:
    """Edge cases for API auth."""

    def test_api_key_as_route_only(self, client):
        """Just the API key with no route after it."""
        r = client.get(f'/api/{API_KEY}')
        # Should not 401 — the key is valid
        assert r.status_code != 401

    def test_case_sensitive_key(self, client):
        """API key comparison should be case-sensitive."""
        r = client.get(f'/api/{API_KEY.upper()}/test.echo')
        # Our key has lowercase, so upper should fail
        if API_KEY != API_KEY.upper():
            assert r.status_code == 401

    def test_key_with_extra_slashes(self, client):
        """Extra slashes in URL should not bypass auth."""
        r = client.get('/api//test.echo')
        assert r.status_code in (401, 404, 422)
