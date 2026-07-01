"""Tests for UI-PORT-03 (add-by-URL in the new UI).

Covers:
  - GET {new_base}partial/add-via-url?url=... resolving a movie via the
    userscript.add_via_url API view (Userscript.getViaUrl) and rendering the
    movie-card partial.
  - The error/no-match state when getViaUrl can't resolve a movie.
  - GET /add/?url=... rendering the auto-resolve htmx wiring + bookmarklet.

Mirrors the app-client fixture pattern from tests/unit/test_fastapi_web.py.
"""
import os

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import api, api_locks
from couchpotato.environment import Env


@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """Set up minimal Env for testing (mirrors test_fastapi_web.py's setup_env)."""
    old_api = dict(api)
    old_locks = dict(api_locks)

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


@pytest.fixture
def app(setup_env):
    from couchpotato import create_app
    return create_app('testkey123', '/')


@pytest.fixture
def client(app):
    return TestClient(app)


def _register_add_via_url(result):
    """Register a fake userscript.add_via_url handler returning `result`."""
    import threading

    def handler(url=None, **kwargs):
        return result

    old_handler = api.get('userscript.add_via_url')
    api['userscript.add_via_url'] = handler
    api_locks['userscript.add_via_url'] = threading.Lock()
    return old_handler


RESOLVED_MOVIE = {
    'imdb': 'tt2381249',
    'titles': ['Mission: Impossible - Rogue Nation'],
    'year': 2015,
    'images': {'poster': ['https://example.com/poster.jpg']},
    'directors': ['Christopher McQuarrie'],
}


class TestPartialAddViaUrl:
    """GET /partial/add-via-url?url=..."""

    def test_resolves_movie_and_renders_movie_card(self, client):
        """A successful getViaUrl-shaped result renders the resolved movie card."""
        _register_add_via_url({'url': 'https://www.imdb.com/title/tt2381249/', 'movie': RESOLVED_MOVIE})

        resp = client.get('/partial/add-via-url?url=https://www.imdb.com/title/tt2381249/')

        assert resp.status_code == 200
        assert 'Mission: Impossible - Rogue Nation' in resp.text
        assert 'tt2381249' in resp.text
        # Reuses the movie-card markup (Add button + profile select), not the
        # generic "No results found" empty state.
        assert 'No results found' not in resp.text
        assert 'partial/profiles' in resp.text

    def test_no_match_renders_error_state(self, client):
        """getViaUrl's failure shape ({'movie': None, 'error': ...}) renders a clear error state."""
        _register_add_via_url({
            'url': 'https://example.com/not-a-movie',
            'movie': None,
            'error': 'Failed getting movie info',
        })

        resp = client.get('/partial/add-via-url?url=https://example.com/not-a-movie')

        assert resp.status_code == 200
        assert "Couldn't find a movie at that URL" in resp.text
        assert 'Failed getting movie info' in resp.text
        assert 'example.com/not-a-movie' in resp.text

    def test_falsy_non_dict_movie_without_explicit_error_still_renders_error_state(self, client):
        """Defensive: even if 'error' were ever missing, a non-dict movie must not crash / must show the error state."""
        _register_add_via_url({'url': 'https://example.com/x', 'movie': False})

        resp = client.get('/partial/add-via-url?url=https://example.com/x')

        assert resp.status_code == 200
        assert "Couldn't find a movie at that URL" in resp.text

    def test_missing_url_param_renders_error_state(self, client):
        """No url query param at all should not attempt a lookup and should show the empty/error state."""
        resp = client.get('/partial/add-via-url')

        assert resp.status_code == 200
        assert "Couldn't find a movie at that URL" in resp.text

    def test_handler_exception_renders_error_state_not_500(self, client):
        """callApiHandler swallowing/raising unexpectedly must not surface as a 500."""
        import threading

        def boom(url=None, **kwargs):
            raise RuntimeError('provider exploded')

        api['userscript.add_via_url'] = boom
        api_locks['userscript.add_via_url'] = threading.Lock()

        resp = client.get('/partial/add-via-url?url=https://example.com/x')

        assert resp.status_code == 200
        assert "Couldn't find a movie at that URL" in resp.text


class TestAddPageUrlParam:
    """GET /add/?url=..."""

    def test_add_page_without_url_has_no_auto_resolve_wiring(self, client):
        resp = client.get('/add/')

        assert resp.status_code == 200
        assert 'add-via-url-results' not in resp.text
        assert 'partial/add-via-url' not in resp.text

    def test_add_page_with_url_returns_200_and_includes_auto_resolve_wiring(self, client):
        resp = client.get('/add/?url=https://www.imdb.com/title/tt2381249/')

        assert resp.status_code == 200
        assert 'id="add-via-url-results"' in resp.text
        assert 'hx-trigger="load"' in resp.text
        assert 'partial/add-via-url?url=' in resp.text
        # The original URL (percent-encoded) must round-trip into the hx-get target.
        assert 'tt2381249' in resp.text

    def test_add_page_still_has_working_title_search_box(self, client):
        """Existing title-search box must keep working when url is present or absent."""
        resp = client.get('/add/?url=https://www.imdb.com/title/tt2381249/')

        assert resp.status_code == 200
        assert 'id="movie-search"' in resp.text
        assert 'partial/search' in resp.text

    def test_add_page_exposes_bookmarklet(self, client):
        resp = client.get('/add/')

        assert resp.status_code == 200
        assert 'javascript:(function(){window.location.href=' in resp.text
        assert "encodeURIComponent(location.href)" in resp.text
        # Bookmarklet must target the real absolute base — it runs from an
        # arbitrary third-party page. The value is embedded via | tojson (a
        # double-quoted, HTML-escaped JS string literal), so the host appears as
        # &#34;http://testserver/&#34; + 'add/?url=', not a raw single-quoted splice.
        assert 'testserver' in resp.text
        assert "+'add/?url='" in resp.text
        # The old, injectable single-quoted splice must be gone.
        assert "'http://testserver/add/?url='" not in resp.text

    def test_absolute_base_sanitizes_hostile_host_header(self):
        """A malicious Host header must not survive into the bookmarklet's JS
        (reflected-injection defense-in-depth alongside the template's | tojson)."""
        from couchpotato.ui import _absolute_base

        class _Req:
            base_url = "http://evil'};alert(document.domain);//"

        out = _absolute_base(_Req())
        for bad in ("'", ';', '}', '(', ')', ' ', 'alert('):
            assert bad not in out, f'sanitized base still contains {bad!r}: {out!r}'
        assert out.startswith('http://')

    def test_absolute_base_forces_http_scheme(self):
        from couchpotato.ui import _absolute_base

        class _Req:
            base_url = 'javascript://evil/'

        assert _absolute_base(_Req()).startswith('http://')

    def test_bookmarklet_does_not_break_out_of_js_string(self, client):
        """Even end-to-end, a hostile Host header can't inject executable JS into
        the bookmarklet: the rendered value is JSON- and HTML-escaped."""
        resp = client.get('/add/', headers={'host': "evil'};alert(1)//"})
        assert resp.status_code == 200
        # No unescaped breakout sequence in the response.
        assert "'};alert(1)" not in resp.text
        assert 'alert(1)' not in resp.text
