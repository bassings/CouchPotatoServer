"""Tests for Phase 3 security hardening (Tasks 11-14).

Task 11: X-Api-Key header auth
Task 12: Database document input validation
Task 13: API rate limiting
Task 14: Tenacity import cleanup (verification only)
"""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from couchpotato.api import addApiView, api, api_locks, api_nonblock, api_docs, api_docs_missing
from couchpotato.environment import Env


# --- Fixtures ---

@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """Set up minimal Env for testing."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    Env.set('web_base', '/')
    Env.set('api_base', '/api/testkey123/')
    Env.set('static_path', '/static/')
    Env.set('app_dir', os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    Env.set('dev', False)

    settings_data = {
        'username': '',
        'password': '',
        'api_key': 'testkey123',
        'dark_theme': False,
        'rate_limit_max': 0,  # Disabled by default for most tests
        'rate_limit_window': 60,
    }

    original_setting = Env.setting

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            settings_data[key] = kwargs['value']
            return
        if key in settings_data:
            return settings_data[key]
        return kwargs.get('default', '')

    Env.setting = staticmethod(mock_setting)

    yield settings_data

    Env.setting = original_setting
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
def app(setup_env):
    from couchpotato import create_app
    return create_app('testkey123', '/')


@pytest.fixture
def client(app):
    return TestClient(app)


# =============================================================================
# Task 11: X-Api-Key Header Auth
# =============================================================================

class TestXApiKeyAuth:
    """Test X-Api-Key header-based authentication."""

    def test_header_auth_works(self, client):
        """X-Api-Key header authenticates API requests."""
        addApiView('test.hello', lambda: {'success': True, 'msg': 'hello'})
        resp = client.get('/api/test.hello', headers={'X-Api-Key': 'testkey123'})
        assert resp.status_code == 200
        assert resp.json()['success'] is True

    def test_url_auth_still_works(self, client):
        """URL-embedded API key still works (backward compat)."""
        addApiView('test.urlauth', lambda: {'success': True})
        resp = client.get('/api/testkey123/test.urlauth')
        assert resp.status_code == 200
        assert resp.json()['success'] is True

    def test_missing_key_returns_401(self, client):
        """Missing API key returns 401."""
        addApiView('test.nokey', lambda: {'success': True})
        resp = client.get('/api/test.nokey')
        assert resp.status_code == 401

    def test_wrong_header_key_returns_401(self, client):
        """Wrong X-Api-Key returns 401."""
        addApiView('test.wrongkey', lambda: {'success': True})
        resp = client.get('/api/test.wrongkey', headers={'X-Api-Key': 'wrongkey'})
        assert resp.status_code == 401

    def test_wrong_url_key_returns_401(self, client):
        """Wrong URL-embedded key returns 401."""
        addApiView('test.wrongurl', lambda: {'success': True})
        resp = client.get('/api/wrongkey/test.wrongurl')
        assert resp.status_code == 401

    def test_header_preferred_over_url(self, client):
        """When both header and URL key provided, header is preferred."""
        addApiView('test.both', lambda: {'success': True})
        # Correct header + URL key in path - header auth takes priority
        resp = client.get('/api/testkey123/test.both', headers={'X-Api-Key': 'testkey123'})
        assert resp.status_code == 200
        assert resp.json()['success'] is True

    def test_header_correct_url_wrong_prefers_header(self, client):
        """Correct header key succeeds even with wrong URL pattern."""
        addApiView('test.headerwin', lambda: {'success': True})
        resp = client.get('/api/test.headerwin', headers={'X-Api-Key': 'testkey123'})
        assert resp.status_code == 200
        assert resp.json()['success'] is True

    def test_header_wrong_url_correct_returns_401(self, client):
        """Wrong header key returns 401 even if URL key would be correct."""
        addApiView('test.headerfail', lambda: {'success': True})
        resp = client.get('/api/testkey123/test.headerfail', headers={'X-Api-Key': 'wrongkey'})
        assert resp.status_code == 401

    def test_post_with_header_auth(self, client):
        """POST requests work with header auth."""
        addApiView('test.postheader', lambda: {'success': True})
        resp = client.post('/api/test.postheader', headers={'X-Api-Key': 'testkey123'})
        assert resp.status_code == 200
        assert resp.json()['success'] is True


# =============================================================================
# Task 12: Database Document Input Validation
# =============================================================================

class TestDatabaseValidation:
    """Test input validation for database document endpoints."""

    def test_validate_document_id_valid(self):
        from couchpotato.core.database import Database
        assert Database._validate_document_id('abc123') is None
        assert Database._validate_document_id('some-doc-id') is None

    def test_validate_document_id_empty(self):
        from couchpotato.core.database import Database
        assert Database._validate_document_id('') is not None
        assert Database._validate_document_id(None) is not None
        assert Database._validate_document_id('   ') is not None

    def test_validate_document_id_too_long(self):
        from couchpotato.core.database import Database
        assert Database._validate_document_id('x' * 257) is not None

    def test_validate_document_id_malicious(self):
        from couchpotato.core.database import Database
        assert Database._validate_document_id('../etc/passwd') is not None
        assert Database._validate_document_id('test;rm -rf') is not None
        assert Database._validate_document_id('test|cat') is not None
        assert Database._validate_document_id('test`cmd`') is not None
        assert Database._validate_document_id('test$VAR') is not None

    def test_validate_document_payload_valid(self):
        from couchpotato.core.database import Database
        doc, err = Database._validate_document_payload(json.dumps({'_id': 'test123', 'data': 'hello'}))
        assert err is None
        assert doc['_id'] == 'test123'

    def test_validate_document_payload_missing_id(self):
        from couchpotato.core.database import Database
        _, err = Database._validate_document_payload(json.dumps({'data': 'hello'}))
        assert err is not None
        assert '_id' in err

    def test_validate_document_payload_invalid_json(self):
        from couchpotato.core.database import Database
        _, err = Database._validate_document_payload('not json')
        assert err is not None

    def test_validate_document_payload_not_object(self):
        from couchpotato.core.database import Database
        _, err = Database._validate_document_payload(json.dumps([1, 2, 3]))
        assert err is not None

    def test_validate_document_payload_too_large(self):
        from couchpotato.core.database import Database
        _, err = Database._validate_document_payload('x' * 1_000_001)
        assert err is not None

    def test_validate_document_payload_empty(self):
        from couchpotato.core.database import Database
        _, err = Database._validate_document_payload('')
        assert err is not None
        _, err = Database._validate_document_payload(None)
        assert err is not None

    def test_delete_document_invalid_id(self):
        from couchpotato.core.database import Database
        db_instance = Database.__new__(Database)
        result = db_instance.deleteDocument(id='', _request=None)
        assert result['success'] is False

    def test_update_document_invalid_payload(self):
        from couchpotato.core.database import Database
        db_instance = Database.__new__(Database)
        result = db_instance.updateDocument(document='not json', _request=None)
        assert result['success'] is False

    def test_delete_document_malicious_id(self):
        from couchpotato.core.database import Database
        db_instance = Database.__new__(Database)
        result = db_instance.deleteDocument(id='../etc/passwd', _request=None)
        assert result['success'] is False
        assert 'invalid' in result['error'].lower()


# =============================================================================
# Task 13: Rate Limiting
# =============================================================================

class TestRateLimiting:
    """Test API rate limiting middleware."""

    @pytest.fixture
    def rate_limited_app(self, setup_env):
        setup_env['rate_limit_max'] = 5
        setup_env['rate_limit_window'] = 60
        from couchpotato import create_app
        return create_app('testkey123', '/')

    @pytest.fixture
    def rate_limited_client(self, rate_limited_app):
        return TestClient(rate_limited_app)

    def test_requests_under_limit_succeed(self, rate_limited_client):
        """Requests under the rate limit succeed."""
        addApiView('test.rate', lambda: {'success': True})
        for _ in range(5):
            resp = rate_limited_client.get('/api/testkey123/test.rate')
            assert resp.status_code == 200

    def test_requests_over_limit_rejected(self, rate_limited_client):
        """Requests exceeding rate limit get 429."""
        addApiView('test.rate2', lambda: {'success': True})
        for _ in range(5):
            rate_limited_client.get('/api/testkey123/test.rate2')
        resp = rate_limited_client.get('/api/testkey123/test.rate2')
        assert resp.status_code == 429
        assert 'rate limit' in resp.json()['error'].lower()

    def test_rate_limit_disabled_when_zero(self, client):
        """Rate limiting is disabled when max_requests is 0."""
        addApiView('test.nolimit', lambda: {'success': True})
        for _ in range(100):
            resp = client.get('/api/testkey123/test.nolimit')
            assert resp.status_code == 200

    def test_rate_limit_middleware_class(self):
        """RateLimitMiddleware works as standalone."""
        from couchpotato.core.rate_limit import RateLimitMiddleware
        from starlette.testclient import TestClient as StarletteTestClient
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        def homepage(request):
            return PlainTextResponse("ok")

        starlette_app = Starlette(routes=[Route("/", homepage)])
        starlette_app.add_middleware(RateLimitMiddleware, max_requests=3, window_seconds=60)
        test_client = StarletteTestClient(starlette_app)

        for _ in range(3):
            assert test_client.get("/").status_code == 200
        assert test_client.get("/").status_code == 429


# =============================================================================
# Task 14: Tenacity Import Verification
# =============================================================================

class TestTenacityUsage:
    """Verify tenacity is properly used where imported."""

    def test_tenacity_removed_from_http_client(self):
        """tenacity imports were removed from http_client.py (unused)."""
        import couchpotato.core.http_client as mod
        source = open(mod.__file__).read()
        assert 'from tenacity import' not in source
        assert 'import tenacity' not in source

    def test_no_tenacity_imports_anywhere(self):
        """No Python files import tenacity (it was unused)."""
        import subprocess
        result = subprocess.run(
            ['find', '.', '-name', '*.py', '-not', '-path', './.venv/*',
             '-not', '-path', './__pycache__/*'],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        )
        files = result.stdout.strip().split('\n')
        for f in files:
            if not f:
                continue
            full = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), f)
            try:
                content = open(full).read()
            except (OSError, UnicodeDecodeError):
                continue
            if ('import tenacity' in content or 'from tenacity' in content) and 'test_security' not in f:
                pytest.fail(f'Unexpected tenacity import in {f}')
