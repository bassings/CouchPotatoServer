"""Tests for the FastAPI web application (Task 2.5.7).

Tests API endpoints, authentication, static files, SSE/long-poll,
and template rendering via FastAPI's TestClient.
"""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from couchpotato.api import addApiView, addNonBlockApiView, api, api_locks, api_nonblock, api_docs, api_docs_missing, callApiHandler
from couchpotato.environment import Env


# --- Fixtures ---

@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """Set up minimal Env for testing."""
    # Save and restore api registries
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    # Set up Env
    Env.set('web_base', '/')
    Env.set('api_base', '/api/testkey123/')
    Env.set('static_path', '/static/')
    Env.set('app_dir', os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    Env.set('dev', False)

    # Mock settings
    settings_data = {
        'username': '',
        'password': '',
        'api_key': 'testkey123',
        'dark_theme': False,
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

    # Restore
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
    """Create a FastAPI test app."""
    from couchpotato import create_app
    return create_app('testkey123', '/')


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def authed_client(app, setup_env):
    """Create an authenticated test client."""
    setup_env['username'] = 'admin'
    setup_env['password'] = 'secret'
    client = TestClient(app)
    # Set auth cookie
    client.cookies.set('user', 'testkey123')
    return client


# --- API Endpoint Tests ---

class TestApiEndpoints:
    """Test the dynamic API registration and dispatch system."""

    def test_api_handler_returns_result(self, client):
        """Registered API handlers return their results."""
        addApiView('test.echo', lambda: {'success': True, 'msg': 'hello'})
        resp = client.get('/api/testkey123/test.echo')
        assert resp.status_code == 200
        assert resp.json() == {'success': True, 'msg': 'hello'}

    def test_api_handler_with_params(self, client):
        """API handlers receive query parameters."""
        addApiView('test.params', lambda name='world': {'hello': name})
        resp = client.get('/api/testkey123/test.params?name=FastAPI')
        assert resp.status_code == 200
        assert resp.json()['hello'] == 'FastAPI'

    def test_api_handler_not_found(self, client):
        """Missing API routes return an error."""
        resp = client.get('/api/testkey123/nonexistent.route')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False
        assert 'error' in data

    def test_api_handler_post(self, client):
        """API routes accept POST requests."""
        addApiView('test.post', lambda: {'method': 'ok'})
        resp = client.post('/api/testkey123/test.post')
        assert resp.status_code == 200
        assert resp.json()['method'] == 'ok'

    def test_api_base_redirects_to_docs(self, client):
        """Empty API route redirects to docs page."""
        resp = client.get('/api/testkey123/', follow_redirects=False)
        assert resp.status_code in (301, 302, 307)
        assert 'docs' in resp.headers.get('location', '')

    def test_api_jsonp_callback(self, client):
        """API supports JSONP callback wrapping."""
        addApiView('test.jsonp', lambda **kw: {'data': 1})
        resp = client.get('/api/testkey123/test.jsonp?callback_func=myFunc')
        assert resp.status_code == 200
        assert 'myFunc(' in resp.text
        assert resp.headers['content-type'].startswith('text/javascript')


# --- Authentication Tests ---

class TestAuthentication:
    """Test cookie-based authentication."""

    def test_no_auth_required_when_no_credentials(self, client):
        """When username/password are empty, no auth is required."""
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code == 200

    def test_auth_required_redirects_to_login(self, app, setup_env):
        """When credentials are set, unauthenticated users are redirected."""
        setup_env['username'] = 'admin'
        setup_env['password'] = 'secret'
        client = TestClient(app)
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert 'login' in resp.headers.get('location', '')

    def test_login_page_renders(self, app, setup_env):
        """Login page renders when credentials are set."""
        setup_env['username'] = 'admin'
        setup_env['password'] = 'secret'
        client = TestClient(app)
        with patch('couchpotato.core.event.fireEvent', return_value=[]):
            resp = client.get('/login/')
            assert resp.status_code == 200
            assert 'login' in resp.text.lower() or 'password' in resp.text.lower()

    def test_login_with_correct_credentials(self, app, setup_env):
        """Successful login sets a cookie and redirects."""
        from couchpotato.core.helpers.variable import md5
        setup_env['username'] = 'admin'
        setup_env['password'] = md5('secret')
        client = TestClient(app)
        resp = client.post('/login/', data={
            'username': 'admin',
            'password': 'secret',
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert 'user' in resp.cookies or 'set-cookie' in resp.headers

    def test_logout_clears_cookie(self, authed_client):
        """Logout clears the auth cookie and redirects to login."""
        resp = authed_client.get('/logout/', follow_redirects=False)
        assert resp.status_code == 302
        assert 'login' in resp.headers.get('location', '')

    def test_getkey_with_correct_credentials(self, client, setup_env):
        """getkey endpoint returns API key with correct credentials."""
        from couchpotato.core.helpers.variable import md5
        setup_env['username'] = 'admin'
        setup_env['password'] = 'pass123'
        resp = client.get(f'/getkey/?u={md5("admin")}&p=pass123')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['api_key'] == 'testkey123'

    def test_getkey_with_wrong_credentials(self, client, setup_env):
        """getkey endpoint fails with wrong credentials."""
        setup_env['username'] = 'admin'
        setup_env['password'] = 'pass123'
        resp = client.get('/getkey/?u=wrong&p=wrong')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is False


# --- Static File Tests ---

class TestStaticFiles:
    """Test static file serving."""

    def test_robots_txt(self, client):
        """robots.txt returns disallow-all."""
        resp = client.get('/robots.txt')
        assert resp.status_code == 200
        assert 'Disallow' in resp.text

    def test_manifest_returns_cache_manifest(self, client):
        """App cache manifest is served correctly."""
        resp = client.get('/old/couchpotato.appcache')
        assert resp.status_code == 200
        assert 'CACHE MANIFEST' in resp.text


# --- SSE / Long-poll Tests ---

class TestNonBlockApi:
    """Test non-blocking API registration (SSE/long-poll support)."""

    def test_add_nonblock_api_view(self):
        """addNonBlockApiView registers handler in api_nonblock."""
        def listener():
            return []

        def broadcaster():
            pass

        addNonBlockApiView('test.stream', (listener, broadcaster))
        assert 'test.stream' in api_nonblock

    def test_nonblock_handler_tuple_stored(self):
        """Non-block handlers store (listener, broadcaster) tuple."""
        listener = lambda: []
        broadcaster = lambda: None
        addNonBlockApiView('test.nb', (listener, broadcaster))
        assert api_nonblock['test.nb'] == (listener, broadcaster)


# --- API Registration Tests ---

class TestApiRegistration:
    """Test the addApiView dynamic registration system."""

    def test_add_api_view(self):
        """addApiView registers a handler."""
        handler = lambda: {'ok': True}
        addApiView('test.reg', handler)
        assert 'test.reg' in api
        assert api['test.reg'] is handler

    def test_add_api_view_with_docs(self):
        """addApiView with docs populates api_docs."""
        docs = {'desc': 'Test endpoint', 'params': {}}
        addApiView('test.documented', lambda: {}, docs=docs)
        assert 'test.documented' in api_docs

    def test_add_api_view_without_docs(self):
        """addApiView without docs adds to missing list."""
        addApiView('test.undocumented', lambda: {})
        assert 'test.undocumented' in api_docs_missing

    def test_call_api_handler(self):
        """callApiHandler dispatches to registered handler."""
        addApiView('test.call', lambda: {'called': True})
        result = callApiHandler('test.call')
        assert result == {'called': True}

    def test_call_api_handler_missing(self):
        """callApiHandler returns error for unregistered route."""
        result = callApiHandler('nonexistent.route')
        assert result['success'] is False

    def test_call_api_handler_with_kwargs(self):
        """callApiHandler passes kwargs to handler."""
        addApiView('test.kwargs', lambda name='default': {'name': name})
        result = callApiHandler('test.kwargs', name='test')
        assert result['name'] == 'test'


# --- Template Rendering Tests ---

class TestTemplateRendering:
    """Test Jinja2 template rendering."""

    def test_index_view_renders(self, client):
        """Index view renders HTML content."""
        with patch('couchpotato.core.event.fireEvent', return_value=[]):
            resp = client.get('/')
            assert resp.status_code == 200
            assert 'html' in resp.text.lower()

    def test_docs_view_renders(self, client):
        """API docs view renders."""
        with patch('couchpotato.core.event.fireEvent', return_value=[]):
            resp = client.get('/old/docs')
            assert resp.status_code == 200
            assert 'API' in resp.text

    def test_new_partial_movies_with_releases_uses_has_releases_filter(self, client):
        """with_releases=true should query backend using has_releases=True (not release_status)."""
        captured_kwargs = {}

        def capture_handler(**kwargs):
            captured_kwargs.update(kwargs)
            return {'movies': []}

        # Register mock handler for media.list
        old_handler = api.get('media.list')
        api['media.list'] = capture_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/new/partial/movies?status=active&with_releases=true')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        assert resp.status_code == 200
        assert captured_kwargs.get('type') == 'movie'
        assert captured_kwargs.get('status') == 'active'
        assert captured_kwargs.get('has_releases') is True
        assert 'release_status' not in captured_kwargs

    def test_available_route_redirects_to_wanted_filter(self, client):
        """Available route should redirect to wanted page with available filter for bookmark compatibility."""
        resp = client.get('/available', follow_redirects=False)
        assert resp.status_code in (301, 302, 307, 308)
        assert resp.headers.get('location') == '/wanted?filter=available'

    def test_wanted_page_shows_available_filter_not_done(self, client):
        """Wanted page should expose All/Wanted/Available filters and no Done filter."""
        resp = client.get('/wanted')
        assert resp.status_code == 200
        assert "setFilter('available')" in resp.text
        assert "setFilter('done')" not in resp.text

    def test_wanted_grid_always_loads_active_movies(self, client):
        """Wanted movie grid should always use status=active (no current_page available branch)."""
        resp = client.get('/wanted')
        assert resp.status_code == 200
        assert 'hx-get="/partial/movies?status=active"' in resp.text
        assert 'with_releases=true' not in resp.text

    def test_sidebar_does_not_link_available_page(self, client):
        """Sidebar nav should no longer contain Available as a top-level item."""
        resp = client.get('/wanted')
        assert resp.status_code == 200
        assert 'href="/available/"' not in resp.text
        assert 'href="/new/available/"' not in resp.text

    def test_movie_cards_include_has_releases_data_attribute(self, client):
        """Movie cards should expose data-has-releases for wanted/available client-side filtering."""
        def media_list_handler(**kwargs):
            return {
                'movies': [
                    {'_id': 'm1', 'status': 'active', 'info': {'titles': ['No Releases']}, 'releases': []},
                    {'_id': 'm2', 'status': 'active', 'info': {'titles': ['Has Releases']}, 'releases': [{'status': 'available'}]},
                ]
            }

        old_handler = api.get('media.list')
        api['media.list'] = media_list_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=active')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        assert resp.status_code == 200
        assert 'data-has-releases="false"' in resp.text
        assert 'data-has-releases="true"' in resp.text


# --- FastAPI App Creation Tests ---

class TestAppCreation:
    """Test FastAPI application factory."""

    def test_create_app_returns_fastapi(self):
        """create_app returns a FastAPI instance."""
        from couchpotato import create_app
        from fastapi import FastAPI
        app = create_app('key123', '/')
        assert isinstance(app, FastAPI)

    def test_create_app_custom_base(self):
        """create_app works with custom web base path."""
        from couchpotato import create_app
        app = create_app('key123', '/cp/')
        client = TestClient(app)
        addApiView('test.base', lambda: {'ok': True})
        resp = client.get('/cp/api/key123/test.base')
        assert resp.status_code == 200
