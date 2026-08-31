"""Tests for the FastAPI web application (Task 2.5.7).

Tests API endpoints, authentication, static files, SSE/long-poll,
and template rendering via FastAPI's TestClient.
"""
import os
import re
import sys
import json
import pytest
# Aliased: test methods below assign a local `html = resp.text`, which
# would shadow a bare `import html` for the rest of that method.
import html as html_entities
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from pathlib import Path

from couchpotato import get_current_user
from couchpotato.api import addApiView, addNonBlockApiView, api, api_locks, api_nonblock, api_docs, api_docs_missing, callApiHandler
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_helper import authenticate, stored_session_secret  # noqa: E402


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
def session_secret():
    """A signing secret in the property store for the duration of a test."""
    with stored_session_secret() as secret:
        yield secret


@pytest.fixture
def session_store(tmp_path):
    """A real property store for the routes that WRITE the signing secret.

    `stored_session_secret` doubles `Env.prop`, which is enough to READ a
    secret, and every other test in this file only reads. Logout rotates, so it
    needs somewhere to write -- and without this it picks up whatever another
    module last left in `Env.get('db')`, which was a bare string.
    """
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    db = SQLiteAdapter()
    db.create(str(tmp_path / 'session-store'))
    previous = Env.get('db')
    Env.set('db', db)
    try:
        yield db
    finally:
        Env.set('db', previous)
        db.close()


@pytest.fixture
def authed_client(app, setup_env, session_secret):
    """Create an authenticated test client.

    The cookie is a signed session token minted by the one test helper
    (AC-ARCH-14), not the api_key -- handing the browser the api_key was the
    defect PR 2b removes.
    """
    setup_env['username'] = 'admin'
    setup_env['password'] = 'secret'
    client = TestClient(app)
    authenticate(client, session_secret)
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

    def test_api_handler_post_form_params(self, client):
        """POST form bodies are passed to API handlers without query-string secrets."""
        addApiView('test.post_params', lambda **kw: {'success': True, 'params': kw})
        resp = client.post(
            '/api/testkey123/test.post_params',
            data={'section': 'core', 'name': 'password', 'value': 'secret'},
        )
        assert resp.status_code == 200
        assert resp.json()['params'] == {
            'section': 'core',
            'name': 'password',
            'value': 'secret',
        }

    def test_api_handler_invalid_json_body_returns_400(self, client):
        """Malformed JSON bodies return a controlled client error."""
        addApiView('test.json_body', lambda **kw: {'success': True, 'params': kw})
        resp = client.post(
            '/api/testkey123/test.json_body',
            content='not-json',
            headers={'Content-Type': 'application/json'},
        )

        assert resp.status_code == 400
        assert resp.json() == {'success': False, 'error': 'Invalid JSON body'}

    def test_api_handler_empty_json_body_reaches_handler(self, client):
        """Empty JSON POST bodies are treated as no body for compatibility."""
        addApiView('test.empty_json_body', lambda **kw: {'success': True, 'params': kw})
        resp = client.post(
            '/api/testkey123/test.empty_json_body',
            content='',
            headers={'Content-Type': 'application/json'},
        )

        assert resp.status_code == 200
        assert resp.json() == {'success': True, 'params': {}}

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

    def test_auth_rejects_forged_user_cookie(self, app, setup_env):
        """The user cookie must match the configured API key."""
        setup_env['username'] = 'admin'
        setup_env['password'] = 'secret'
        client = TestClient(app)
        client.cookies.set('user', 'not-the-api-key')

        resp = client.get('/', follow_redirects=False)

        assert resp.status_code in (302, 307)
        assert 'login' in resp.headers.get('location', '')

    def test_auth_rejects_non_ascii_user_cookie(self, app, setup_env):
        """Malformed user cookies are rejected without raising."""
        setup_env['username'] = 'admin'
        setup_env['password'] = 'secret'

        user = get_current_user(SimpleNamespace(cookies={'user': 'é'}))

        assert user is None

    def test_auth_accepts_a_signed_session_cookie(self, app, setup_env, session_secret):
        """A cookie carrying a signature we issued is accepted."""
        setup_env['username'] = 'admin'
        setup_env['password'] = 'secret'
        client = TestClient(app)
        authenticate(client, session_secret)

        resp = client.get('/', follow_redirects=False)

        assert resp.status_code == 200

    def test_auth_rejects_the_api_key_as_a_user_cookie(self, app, setup_env, session_secret):
        """The cookie used to BE the api_key. It is refused from the first
        request after upgrade (D5): no compatibility window, because a
        fallback would mean the api_key still authenticates the browser."""
        setup_env['username'] = 'admin'
        setup_env['password'] = 'secret'
        client = TestClient(app)
        client.cookies.set('user', 'testkey123')

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

    def test_login_with_correct_credentials(self, app, setup_env, session_secret):
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

    def test_logout_clears_cookie(self, authed_client, session_store):
        """Logout clears the auth cookie and redirects to login.

        POST, not GET: logout now rotates the shared signing secret, which ends
        every session on every device, so answering a GET would make any
        cross-site `<img src="/logout/">` a remote sign-out-everywhere button.
        303 rather than 302 because this is the response to a POST. The
        revocation itself is covered in tests/unit/test_session_revocation.py.
        """
        resp = authed_client.post('/logout/', follow_redirects=False)
        assert resp.status_code == 303
        assert 'login' in resp.headers.get('location', '')

    def test_logout_does_not_answer_a_get(self, authed_client):
        assert authed_client.get('/logout/', follow_redirects=False).status_code == 405

    def test_getkey_with_correct_credentials(self, client, setup_env):
        """getkey endpoint returns API key with correct credentials.

        Real usage: password stored as md5 hash in config, client sends md5 hash.
        """
        from couchpotato.core.helpers.variable import md5
        setup_env['username'] = 'admin'
        setup_env['password'] = md5('pass123')  # stored as MD5, as the app does
        resp = client.get(f'/getkey/?u={md5("admin")}&p={md5("pass123")}')
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['api_key'] == 'testkey123'

    def test_getkey_with_wrong_credentials(self, client, setup_env):
        """getkey endpoint fails with wrong credentials."""
        from couchpotato.core.helpers.variable import md5
        setup_env['username'] = 'admin'
        setup_env['password'] = md5('pass123')  # stored as MD5
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
        """/old/couchpotato.appcache redirects to / (legacy stack retired)."""
        resp = client.get('/old/couchpotato.appcache', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers.get('location') == '/'


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
        """/old/docs redirects to / (legacy stack retired; docs moved to new UI)."""
        resp = client.get('/old/docs', follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers.get('location') == '/'

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

    def test_partial_movies_without_with_releases_does_not_filter_at_all(self, client):
        """Omitting with_releases must query EVERY active movie, not the no-release set.

        wanted.html fetches this partial once with no `with_releases`, and the
        All/Wanted/Available chips then filter client-side on each card's
        data-has-releases attribute. So the initial fetch has to carry both
        kinds or a chip has nothing to reveal.

        This parameter defaulted to False, which asked for the no-release set
        only. That was invisible while has_releases was inert; once T1.9 fixed
        the filter (release/main.py:754) the Available chip showed zero movies
        permanently. Verified against a live server at the time: the default
        returned 1 card while with_releases=true returned 2.

        Asserting has_releases is ABSENT, not that it equals some value: the
        defect was passing the key at all.
        """
        captured_kwargs = {}

        def capture_handler(**kwargs):
            captured_kwargs.update(kwargs)
            return {'movies': []}

        old_handler = api.get('media.list')
        api['media.list'] = capture_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=active')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        assert resp.status_code == 200
        assert captured_kwargs.get('status') == 'active'
        assert 'has_releases' not in captured_kwargs, (
            'the page-level fetch must not constrain has_releases, or the '
            'Available chip has no movies to reveal'
        )

    def test_partial_movies_active_downloaded_makes_exactly_one_unconstrained_call(self, client):
        """FEAT-010 AC-QA-2: a single request for the widened Wanted status set must
        reach `media.list` exactly once, with status='active,downloaded' verbatim and
        no `has_releases` key -- the same "one unconstrained fetch, chips filter
        client-side" contract test_partial_movies_without_with_releases_does_not_filter_at_all
        pins for the old status=active call.

        Call COUNT is asserted (== 1), not just the kwargs of the last call, so a
        two-fetch implementation (one per status, merged server-side) is caught even
        though it would produce the same final kwargs dict on its last call.
        """
        call_count = 0
        captured_kwargs = {}

        def capture_handler(**kwargs):
            nonlocal call_count
            call_count += 1
            captured_kwargs.update(kwargs)
            return {'movies': []}

        old_handler = api.get('media.list')
        api['media.list'] = capture_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=active,downloaded')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        assert resp.status_code == 200
        assert call_count == 1
        assert captured_kwargs.get('status') == 'active,downloaded'
        assert 'has_releases' not in captured_kwargs

    def test_partial_movies_with_releases_false_still_filters_to_wanted(self, client):
        """The explicit false case must keep working: only movies with no release.

        Pins the other direction of the fix above, so making the omitted case
        unfiltered cannot silently make the explicit case unfiltered too.
        """
        captured_kwargs = {}

        def capture_handler(**kwargs):
            captured_kwargs.update(kwargs)
            return {'movies': []}

        old_handler = api.get('media.list')
        api['media.list'] = capture_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=active&with_releases=false')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        assert resp.status_code == 200
        assert captured_kwargs.get('has_releases') is False

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

    def test_wanted_grid_loads_active_and_downloaded_movies_library_stays_done(self, client):
        """Wanted asks for active,downloaded (FEAT-010 AC-QA-1); Library still asks for
        exactly done. Both directions are pinned in the one test so neither page can
        inherit the other's status set.

        This retargets the old `test_wanted_grid_always_loads_active_movies`, which
        asserted the pre-FEAT-010 literal `status=active` and passed before this
        change. A `downloaded` film (the review-gate state) never reached that
        status set, so it was never listed anywhere -- the bug this feature fixes.
        """
        wanted_resp = client.get('/wanted')
        assert wanted_resp.status_code == 200
        assert wanted_resp.text.count('hx-get="/partial/movies?status=active,downloaded"') == 1
        assert 'hx-get="/partial/movies?status=active"' not in wanted_resp.text
        assert 'with_releases=true' not in wanted_resp.text

        library_resp = client.get('/library')
        assert library_resp.status_code == 200
        assert library_resp.text.count('hx-get="/partial/movies?status=done"') == 1
        assert 'hx-get="/partial/movies?status=active' not in library_resp.text

    def test_wanted_page_shows_four_chips_in_order_with_review_last(self, client):
        """FEAT-010 AC-DESIGN-1: the Wanted page renders exactly four filter chips,
        in order All, Wanted, Available, Review. The Review chip must reuse the
        existing chip markup verbatim (same class string, same selected/unselected
        binding pattern) rather than introduce a new component or colour token, and
        it renders even with zero films awaiting review so its position never moves.
        """
        resp = client.get('/wanted')
        assert resp.status_code == 200
        html = resp.text

        assert "setFilter('')" in html
        assert "setFilter('wanted')" in html
        assert "setFilter('available')" in html
        assert "setFilter('downloaded')" in html, (
            "the Review chip must call setFilter('downloaded'), the status the "
            "review-gate movies actually carry"
        )

        # Order: All, then Wanted, then Available, then Review.
        pos_all = html.index("setFilter('')")
        pos_wanted = html.index("setFilter('wanted')")
        pos_available = html.index("setFilter('available')")
        pos_review = html.index("setFilter('downloaded')")
        assert pos_all < pos_wanted < pos_available < pos_review

        # The Review chip reuses the existing chip markup verbatim: same
        # filterStatus === '<value>' selected-state binding pattern as the
        # other three chips, not a new component or colour token.
        assert (
            ':class="filterStatus === \'downloaded\' ? \'bg-cp-accent/10 text-cp-accent\' '
            ': \'bg-white/[0.03] text-cp-muted hover:text-cp-text\'"'
        ) in html, "the Review chip's selected-state binding must match the other chips' pattern exactly"

        # Same shared chip class string on all four -- no new class pattern.
        assert html.count('px-2.5 py-1 rounded-md transition-colors') >= 4, (
            "the Review chip must reuse the shared chip class string, not a new one"
        )
        assert '>Review<' in html

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

    def test_movie_card_labels_downloaded_status_as_review_gate(self, client):
        """A movie in the 'downloaded' review-gate status (workflow phase 1)
        must render a distinct 'downloaded / review' badge on the card grid,
        not fall through to the generic done/wanted branches."""
        def media_list_handler(**kwargs):
            return {
                'movies': [
                    {'_id': 'm1', 'status': 'downloaded', 'info': {'titles': ['Awaiting Review']}, 'releases': []},
                ]
            }

        old_handler = api.get('media.list')
        api['media.list'] = media_list_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=downloaded')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        assert resp.status_code == 200
        assert 'downloaded / review' in resp.text
        assert 'data-status="downloaded"' in resp.text

    def test_movie_card_shows_both_review_controls_when_downloaded(self, client):
        """FEAT-010 AC-QA-4: a card for a movie whose status is 'downloaded'
        carries data-status="downloaded", the existing 'downloaded / review'
        badge, and BOTH the Mark Done and Mark Failed controls, each
        addressable by a stable data-testid rather than by visible text (a
        text-based assertion can't tell the review "Mark Done" apart from the
        generic "Mark as Done" button, and can be satisfied by markup that
        looks right but wires up nothing)."""
        def media_list_handler(**kwargs):
            return {
                'movies': [
                    {'_id': 'm1', 'status': 'downloaded', 'info': {'titles': ['Awaiting Review']}, 'releases': []},
                ]
            }

        old_handler = api.get('media.list')
        api['media.list'] = media_list_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=downloaded')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        assert resp.status_code == 200
        assert 'data-status="downloaded"' in resp.text
        assert 'downloaded / review' in resp.text
        assert 'data-testid="review-mark-done"' in resp.text, (
            'the card Mark Done control must carry a stable data-testid'
        )
        assert 'data-testid="review-mark-failed"' in resp.text, (
            'the card Mark Failed control must carry a stable data-testid'
        )

    def test_movie_card_hides_review_controls_for_non_downloaded_statuses(self, client):
        """FEAT-010 AC-QA-5: the gate is proven in both directions. Neither
        card-level review control renders for a movie whose status is
        'active', 'done', 'snatched', or an unrecognised value ('suspended').
        A mutation that renders the controls unconditionally (e.g. dropping
        the {% if status == 'downloaded' %} guard) must fail at least one of
        these four cases; a single-status check could pass by accident."""
        for status in ('active', 'done', 'snatched', 'suspended'):
            def media_list_handler(**kwargs):
                return {
                    'movies': [
                        {'_id': 'm1', 'status': status, 'info': {'titles': ['Some Movie']}, 'releases': []},
                    ]
                }

            old_handler = api.get('media.list')
            api['media.list'] = media_list_handler
            api_locks['media.list'] = __import__('threading').Lock()

            try:
                resp = client.get('/partial/movies?status={}'.format(status))
            finally:
                if old_handler:
                    api['media.list'] = old_handler
                else:
                    api.pop('media.list', None)

            assert resp.status_code == 200
            assert 'data-testid="review-mark-done"' not in resp.text, (
                'status={!r} must not render the card Mark Done control'.format(status)
            )
            assert 'data-testid="review-mark-failed"' not in resp.text, (
                'status={!r} must not render the card Mark Failed control'.format(status)
            )

    def test_movie_card_review_controls_use_correct_tokens_gap_and_order(self, client):
        """FEAT-010 AC-DESIGN-8: the two card controls cannot be confused for
        one another, and the destructive one is not the easy target. Mark
        Failed uses the danger token already used for the same action on the
        detail page (bg-cp-danger/10 text-cp-danger, movie_detail.html:283)
        and Mark Done the success token; they sit in a row using the same
        gap-2 spacing the detail page's own action row uses
        (movie_detail.html:140); and Mark Done is first in DOM order, so the
        destructive control is never the first thing reached by Tab."""
        def media_list_handler(**kwargs):
            return {
                'movies': [
                    {'_id': 'm1', 'status': 'downloaded', 'info': {'titles': ['Awaiting Review']}, 'releases': []},
                ]
            }

        old_handler = api.get('media.list')
        api['media.list'] = media_list_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=downloaded')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        html = resp.text
        assert 'data-testid="review-mark-done"' in html
        assert 'data-testid="review-mark-failed"' in html

        pos_done = html.index('data-testid="review-mark-done"')
        pos_failed = html.index('data-testid="review-mark-failed"')
        assert pos_done < pos_failed, (
            'Mark Done must be first in DOM order so the destructive Mark '
            'Failed control is never the first thing reached by Tab'
        )

        # Look at a small window around each testid for its containing
        # <button ...> tag's class attribute, rather than the whole document,
        # so a coincidental substring match elsewhere in the page can't pass
        # this by accident.
        done_window = html[max(0, pos_done - 400):pos_done + 100]
        failed_window = html[max(0, pos_failed - 400):pos_failed + 100]

        assert 'bg-cp-success/10' in done_window and 'text-cp-success' in done_window, (
            'Mark Done must use the success token'
        )
        assert 'bg-cp-danger/10' in failed_window and 'text-cp-danger' in failed_window, (
            'Mark Failed must use the danger token, matching movie_detail.html:283'
        )
        assert 'bg-cp-danger' not in done_window, (
            'Mark Done must not also carry the danger token'
        )
        assert 'bg-cp-success' not in failed_window, (
            'Mark Failed must not also carry the success token'
        )

        # The two controls are separated by at least the standard control
        # gap: the row containing both reuses the gap-2 spacing the detail
        # page's own action row uses (movie_detail.html:140), rather than a
        # bespoke or absent gap.
        between = html[pos_done:pos_failed]
        assert 'gap-2' in between or 'gap-2' in done_window, (
            'the two controls must sit in a row using the standard gap-2 '
            'control spacing, not a bespoke or absent gap'
        )

    def test_movie_card_mark_failed_is_guarded_by_the_same_confirm_as_detail_page(self, client):
        """FEAT-010 AC-QA-12 (text half) and AC-SIMP-4: the card's Mark
        Failed control opens a confirmation whose text is character-identical
        to the one the detail page already uses
        (movie_detail.html:283, 'Mark this download as failed and search for
        another copy? This discards the current copy.'), the diff of
        movie_cards.html contains no reference to media.delete, and the
        mark_failed call is lexically inside that confirm( branch -- so
        there is no code path that reaches the request without the dialogue.
        AC-SIMP-4 itself is proven load-bearing at review by deleting the
        confirm( wrapper and watching this card's AC-QA-12 e2e coverage
        (tests/e2e/filters.spec.ts) go red."""
        detail_confirm_text = (
            'Mark this download as failed and search for another copy? '
            'This discards the current copy.'
        )
        assert detail_confirm_text in Path(
            'couchpotato/ui/templates/partials/movie_detail.html'
        ).read_text(encoding='utf-8'), (
            'fixture text has drifted from movie_detail.html -- update the '
            'literal above to match, do not weaken this test'
        )

        def media_list_handler(**kwargs):
            return {
                'movies': [
                    {'_id': 'm1', 'status': 'downloaded', 'info': {'titles': ['Awaiting Review']}, 'releases': []},
                ]
            }

        old_handler = api.get('media.list')
        api['media.list'] = media_list_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=downloaded')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        html = resp.text
        assert 'media.delete' not in html, (
            'movie_cards.html must not gain a reference to media.delete'
        )

        confirm_call = "confirm('{}')".format(detail_confirm_text)
        assert confirm_call in html, (
            'the card Mark Failed confirmation text must be character-identical '
            'to the detail page\'s'
        )

        # Lexically inside a confirm( branch, checked STRUCTURALLY.
        #
        # This replaced a positional check that compared the index of the
        # FIRST confirm( in the document against the index of each
        # mark_failed, which is a stand-in rather than the property: it
        # proves ordering in a string, not nesting in an expression.
        # Demonstrated, not theorised -- moving a decoy confirm( onto the
        # Mark Done control (earlier in the DOM) and stripping the real one
        # from Mark Failed left the old assertion GREEN while the card fired
        # mark_failed with no dialogue at all. That is exactly this repo's
        # recurring `guards-that-check-a-stand-in` defect.
        #
        # What is asserted now: mark_failed appears ONLY inside the Mark
        # Failed control's own @click, and inside that expression it sits in
        # the BODY of the `if (...)` whose condition contains the confirm(
        # call, not merely somewhere after the word "confirm".
        assert 'mark_failed' in html

        # Find the control's tag by scanning with quote awareness rather than
        # to the first '>', because the handler contains arrow functions and
        # a naive `(.*?)>` truncates the attribute it is trying to read.
        testid = html.index('data-testid="review-mark-failed"')
        tag_start = html.rindex('<button', 0, testid)
        quote, tag_end = None, None
        for i in range(tag_start, len(html)):
            char = html[i]
            if quote:
                if char == quote:
                    quote = None
            elif char in '"\'':
                quote = char
            elif char == '>':
                tag_end = i
                break
        assert tag_end is not None, 'unterminated Mark Failed control tag'
        tag = html[tag_start:tag_end]

        click = re.search(r'@click="(.*?)"', tag, re.S)
        assert click, 'the Mark Failed control must carry an @click handler'
        expression = click.group(1)

        # Nothing anywhere else in the card markup may reach the route.
        start = html.index(expression)
        for match in re.finditer('mark_failed', html):
            assert start <= match.start() < start + len(expression), (
                'mark_failed appears outside the Mark Failed control\'s own '
                '@click, so some other path can reach the route unguarded'
            )

        # Walk the `if (` condition to its matching close paren, so the
        # boundary is the real end of the condition rather than the first
        # `)` encountered, which confirm('...') itself would supply.
        assert expression.lstrip().startswith('if'), (
            'the handler must open with the if( guard'
        )
        opened = expression.index('(')
        depth, condition_end = 0, None
        for i in range(opened, len(expression)):
            if expression[i] == '(':
                depth += 1
            elif expression[i] == ')':
                depth -= 1
                if depth == 0:
                    condition_end = i
                    break
        assert condition_end is not None, 'unbalanced parens in the @click guard'

        condition = expression[opened:condition_end]
        assert confirm_call in condition, (
            'the confirm( call must be part of the if CONDITION, so dismissing '
            'it short-circuits before the request'
        )
        for match in re.finditer('mark_failed', expression):
            assert match.start() > condition_end, (
                'mark_failed must sit in the BODY of the confirm-guarded if, '
                'not in its condition'
            )

    def test_movie_card_refresh_aria_label_does_not_break_out_of_its_js_string_for_a_hostile_title(self, client):
        """FEAT-010 AC-SEC-1 (H2, branch review 2026-08-31): no film title
        reaches an Alpine or JS expression by string interpolation.
        Rendering the real partials/movie_cards.html partial (via
        /partial/movies, the same route the grid actually hits) for a movie
        titled "Ocean's Eleven'+(window.pwn=1)+'", every attribute whose
        name begins with @, : or x- must, after HTML-entity decoding, not
        contain the injection fragment "+(window.pwn=1)+". The refresh
        button's `:aria-label="refreshing ? 'Refreshing metadata for
        {{ title }}' : ...'"` interpolates the raw title straight into a
        quoted JS string literal, so the apostrophe in the fixture title
        closes that literal early and the rest of the payload runs as Alpine
        expression syntax.

        This is a security AND an accessibility defect together: even an
        ordinary title with an apostrophe ("Ocean's Eleven", "Schindler's
        List") breaks the same expression and leaves the icon-only refresh
        control with no accessible name at all (WCAG 4.1.2), with no
        attacker involved.
        """
        hostile_title = "Ocean's Eleven'+(window.pwn=1)+'"
        injection_fragment = '+(window.pwn=1)+'

        def media_list_handler(**kwargs):
            return {
                'movies': [
                    {'_id': 'm1', 'status': 'active', 'info': {'titles': [hostile_title]}, 'releases': []},
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
        rendered = resp.text

        # Sanity: the hostile title actually reached the render, otherwise
        # every assertion below would pass vacuously.
        assert 'Ocean' in rendered, 'the hostile title fixture did not reach the template'

        # Same methodology the branch review used: scan every attribute
        # whose name begins with @, : or x- (Alpine directives and bound
        # attributes), HTML-entity-decode its value the way a real browser
        # does before Alpine ever evaluates it, and look for the payload.
        attr_pattern = re.compile(r'\s((?:@|:|x-)[\w:.\-]*)="([^"]*)"')
        offending = [
            (name, html_entities.unescape(raw_value))
            for name, raw_value in attr_pattern.findall(rendered)
            if injection_fragment in html_entities.unescape(raw_value)
        ]

        assert offending == [], (
            'a film title must never be able to break out of a quoted JS/Alpine '
            'string literal; offending attributes (decoded): {!r}. Fix: stop '
            'interpolating the title into the expression -- emit it as a plain '
            'autoescaped data-* attribute (or via the |tojson filter) and read '
            'it back at runtime instead.'.format(offending)
        )

    def test_movie_card_review_controls_accessible_name_has_visible_text_as_a_prefix(self, client):
        """WCAG 2.2 SC 2.5.3 Label in Name (H11, branch review 2026-08-31):
        for a control with visible text, the accessible name must have that
        visible text as a PREFIX, not merely contain it somewhere -- a
        speech-input user (Voice Control, Dragon) activates a control by
        speaking its visible label, which the accessibility tree must be
        able to match at the start of the name. Both card review controls
        currently render `aria-label="Mark {{ title }} as done"` /
        "...as failed", so "Mark Done" is not a contiguous prefix of "Mark
        The Thing as done" once a real title sits between the two words.

        The axe-core rule that would catch this
        (label-content-name-mismatch) is EXPERIMENTAL and excluded from
        this project's tag set (wcag2a/2aa/21a/21aa/22aa), so this
        assertion is the only guard in the repo for this specific SC on
        these two controls -- axe returning zero violations here is not
        evidence the page conforms.
        """
        def media_list_handler(**kwargs):
            return {
                'movies': [
                    {'_id': 'm1', 'status': 'downloaded', 'info': {'titles': ["Schindler's List"]}, 'releases': []},
                ]
            }

        old_handler = api.get('media.list')
        api['media.list'] = media_list_handler
        api_locks['media.list'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movies?status=downloaded')
        finally:
            if old_handler:
                api['media.list'] = old_handler
            else:
                api.pop('media.list', None)

        assert resp.status_code == 200
        rendered = resp.text

        # T7d item 7 (round two on H11): this used to HARDCODE the expected
        # prefix ('Mark Done', 'Mark Failed') instead of reading what the
        # template actually renders as the button's visible text. A
        # hardcoded expectation cannot detect the exact SC 2.5.3 violation
        # it exists to catch: change the rendered `<span>` text (e.g. to
        # "Complete") while leaving `aria-label` alone, and this test kept
        # passing because it was comparing the OLD label against itself,
        # never against what a sighted user actually sees on screen. The
        # visible text must be extracted from the same response the
        # accessible name is extracted from.
        for testid in ('review-mark-done', 'review-mark-failed'):
            testid_pos = rendered.index('data-testid="{}"'.format(testid))
            tag_start = rendered.rindex('<button', 0, testid_pos)
            tag_end = rendered.index('>', testid_pos)
            tag = rendered[tag_start:tag_end]

            match = re.search(r'aria-label="([^"]*)"', tag)
            assert match, '{} must carry an aria-label'.format(testid)
            accessible_name = html_entities.unescape(match.group(1))

            # The visible label sits in the first <span>...</span> after
            # the button's closing '>', e.g. <span x-show="!markingDone">
            # Mark Done</span> -- read it from the render rather than
            # asserting a literal the template might no longer produce.
            span_match = re.search(
                r'<span[^>]*>([^<]*)</span>', rendered[tag_end:],
            )
            assert span_match, (
                '{} has no visible <span> text immediately after its '
                'opening tag to compare the accessible name against'
                .format(testid)
            )
            visible_text = html_entities.unescape(span_match.group(1)).strip()
            assert visible_text, (
                '{} rendered an empty visible label -- nothing to compare '
                'the accessible name against'.format(testid)
            )

            assert accessible_name.startswith(visible_text), (
                'WCAG 2.5.3 Label in Name: the accessible name for {!r} must '
                'start with its own RENDERED visible text {!r} so a Voice '
                'Control/Dragon user can activate it by speaking what they '
                'see -- got accessible name {!r}, which does not have the '
                'rendered visible text as a prefix.'.format(
                    testid, visible_text, accessible_name,
                )
            )

    def test_movie_detail_labels_downloaded_status_as_review_gate(self, client):
        """Same review-gate label on the movie detail partial."""
        def media_get_handler(**kwargs):
            return {'media': {'_id': 'm1', 'status': 'downloaded', 'info': {'titles': ['Awaiting Review']}, 'releases': []}}

        old_handler = api.get('media.get')
        api['media.get'] = media_get_handler
        api_locks['media.get'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movie/m1')
        finally:
            if old_handler:
                api['media.get'] = old_handler
            else:
                api.pop('media.get', None)

        assert resp.status_code == 200
        assert 'downloaded / review' in resp.text

    def test_movie_detail_hides_operator_replace_trigger_and_modal_at_default_setting(
        self, client,
    ):
        """T8a. FEAT-011's 'Replace with this file' trigger and the modal it
        opens must not render while `operator_replace_enabled` sits at its
        shipped default (off) -- the owner's explicit decision after the
        underlying destructive path reintroduced the same film-destroying
        defect three times.

        The movie here carries a completed release WITH a movie file (the
        exact condition `partials/movie_detail.html`'s own
        `ns.has_operator_replace_target` gate already looks for) and a
        status of 'downloaded' (the FEAT-010 review-gate condition), so
        BOTH the operator-replace markup and the review-gate controls would
        render today if nothing suppressed the former -- this is not a
        movie with "nothing to show", it is a movie with everything to show
        and only one half of it permitted to.

        Both assertions live in the same test (per T8a's instruction) so a
        template change that blanks the whole page, rather than gating the
        one feature, cannot pass by accident: it would fail here on the
        review-gate controls going missing too.
        """
        def media_get_handler(**kwargs):
            return {
                'media': {
                    '_id': 'm1',
                    'status': 'downloaded',
                    'info': {'titles': ['Replace Me']},
                    'releases': [
                        {
                            'status': 'downloaded',
                            'quality': '720p',
                            'files': {'movie': ['/library/Replace Me.mkv']},
                        },
                    ],
                },
            }

        old_handler = api.get('media.get')
        api['media.get'] = media_get_handler
        api_locks['media.get'] = __import__('threading').Lock()

        try:
            resp = client.get('/partial/movie/m1')
        finally:
            if old_handler:
                api['media.get'] = old_handler
            else:
                api.pop('media.get', None)

        assert resp.status_code == 200

        assert 'data-testid="operator-replace-trigger"' not in resp.text, (
            'the operator-replace trigger rendered with '
            'operator_replace_enabled at its default (off)'
        )
        assert 'data-testid="operator-replace-modal"' not in resp.text, (
            'the operator-replace modal rendered with '
            'operator_replace_enabled at its default (off)'
        )
        assert 'Replace with this file' not in resp.text, (
            'the operator-replace trigger/modal text rendered with '
            'operator_replace_enabled at its default (off)'
        )

        assert 'data-testid="review-mark-done"' in resp.text, (
            'FEAT-010 review-gate Mark Done control must still render -- '
            'gating FEAT-011 must not touch FEAT-010'
        )
        assert 'data-testid="review-mark-failed"' in resp.text, (
            'FEAT-010 review-gate Mark Failed control must still render -- '
            'gating FEAT-011 must not touch FEAT-010'
        )


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

    def test_new_ui_static_assets_respect_custom_base(self):
        """New UI assets load under url_base for reverse-proxy installs."""
        from couchpotato import create_app
        Env.set('web_base', '/cp/')
        static_dir = os.path.join(Env.get('app_dir'), 'couchpotato', 'static')
        app = create_app('key123', '/cp/', static_dir=static_dir)
        client = TestClient(app)

        resp = client.get('/cp/')

        assert resp.status_code == 200
        assert 'src="/cp/static/scripts/vendor/new-ui/htmx-2.0.4.min.js"' in resp.text
        assert "navigator.serviceWorker.register('/cp/static/sw.js')" in resp.text
        assert 'src="/static/scripts/vendor/new-ui/' not in resp.text

        sw_resp = client.get('/cp/static/sw.js')
        assert sw_resp.status_code == 200
        assert "SCOPE_PATH.endsWith('/static/')" in sw_resp.text
        assert "url.pathname.startsWith(withBase('static/'))" in sw_resp.text


class TestPartialErrorHandling:
    """The Suggestions partials must signal backend failure with a non-2xx so
    the client loader shows its error / Try-again state, while a genuinely
    empty (but successful) result still renders normally with 200.

    The handlers do `from couchpotato.api import callApiHandler` at call time,
    so patching the module attribute (via sys.modules) reaches them.
    """

    @staticmethod
    def _patch_api(monkeypatch, impl):
        monkeypatch.setattr(sys.modules['couchpotato.api'], 'callApiHandler', impl)

    # --- Realistic failure: callApiHandler converts handler exceptions into a
    #     {'success': False, ...} RETURN (it never re-raises), so this — not a
    #     thrown exception — is the production failure path the loader must see.
    def test_partial_charts_returns_500_on_error_result(self, client, monkeypatch):
        self._patch_api(monkeypatch, lambda *a, **k: {'success': False, 'error': 'Failed returning results'})
        resp = client.get('/partial/charts')
        assert resp.status_code == 500
        assert 'Failed to load charts' in resp.text

    def test_partial_suggestions_returns_500_on_error_result(self, client, monkeypatch):
        self._patch_api(monkeypatch, lambda *a, **k: {'success': False, 'error': 'Failed returning results'})
        resp = client.get('/partial/suggestions')
        assert resp.status_code == 500
        assert 'Failed to load suggestions' in resp.text

    # --- A non-dict result (programming error) is also a failure, not "empty".
    #     Tested for both endpoints since they share the isinstance guard, and
    #     with both None AND a list: a bare None can't tell isinstance(_, dict)
    #     apart from isinstance(_, list) (both False for None), so the list
    #     fixture pins the "only a dict is a valid result" contract explicitly.
    def test_partial_charts_returns_500_on_non_dict_result(self, client, monkeypatch):
        self._patch_api(monkeypatch, lambda *a, **k: None)
        assert client.get('/partial/charts').status_code == 500

    def test_partial_suggestions_returns_500_on_non_dict_result(self, client, monkeypatch):
        self._patch_api(monkeypatch, lambda *a, **k: None)
        assert client.get('/partial/suggestions').status_code == 500

    def test_partial_charts_returns_500_on_list_result(self, client, monkeypatch):
        self._patch_api(monkeypatch, lambda *a, **k: ['not', 'a', 'dict'])
        assert client.get('/partial/charts').status_code == 500

    def test_partial_suggestions_returns_500_on_list_result(self, client, monkeypatch):
        self._patch_api(monkeypatch, lambda *a, **k: ['not', 'a', 'dict'])
        assert client.get('/partial/suggestions').status_code == 500

    # --- Backstop: a handler that genuinely raises before callApiHandler can
    #     wrap it (e.g. import/dispatch failure) still becomes a 500.
    def test_partial_charts_returns_500_on_raised_exception(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError('charts backend down')

        self._patch_api(monkeypatch, boom)
        assert client.get('/partial/charts').status_code == 500

    def test_partial_suggestions_returns_500_on_raised_exception(self, client, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError('suggestions backend down')

        self._patch_api(monkeypatch, boom)
        assert client.get('/partial/suggestions').status_code == 500

    # --- A genuinely empty (but successful) result renders normally with 200;
    #     the success fixtures include success=True to mirror real responses.
    def test_partial_charts_returns_200_on_empty_success(self, client, monkeypatch):
        self._patch_api(monkeypatch, lambda *a, **k: {'success': True, 'charts': []})
        assert client.get('/partial/charts').status_code == 200

    def test_partial_suggestions_returns_200_on_empty_success(self, client, monkeypatch):
        self._patch_api(monkeypatch, lambda *a, **k: {'success': True, 'movies': []})
        assert client.get('/partial/suggestions').status_code == 200
