"""UI-PORT-02: the login page is decoupled from the legacy asset stack.

Verifies that `couchpotato/templates/login.html`:
  * renders a 200 response with the username/password inputs and a submit
    control, using the exact field names `login_post` expects
  * no longer references the legacy ClientScript-served bundle
    (`combined.min.css`, `clientscript`, MooTools, Uniform)
  * pulls in the modern Tailwind design-system head (CDN script + cp-* tokens)
"""
import os

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import addApiView, api, api_locks, api_nonblock, api_docs, api_docs_missing
from couchpotato.environment import Env


@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    """Set up minimal Env for testing (mirrors test_fastapi_web.py)."""
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
        'username': 'admin',
        'password': 'secret',
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
    api_nonblock.clear()
    api_nonblock.update(old_nonblock)
    api_docs.clear()
    api_docs.update(old_docs)
    api_docs_missing.clear()
    api_docs_missing.extend(old_missing)


@pytest.fixture
def app(setup_env):
    """Create a FastAPI test app. Credentials are set so /login/ is reachable
    (create_app's login_get redirects an already-authenticated user away)."""
    from couchpotato import create_app
    return create_app('testkey123', '/')


@pytest.fixture
def client(app):
    return TestClient(app)


class TestLoginPageRendersDesignSystem:
    """GET /login/ returns the ported Tailwind login page."""

    def test_login_page_returns_200(self, client):
        resp = client.get('/login/')
        assert resp.status_code == 200

    def test_login_page_has_username_input(self, client):
        resp = client.get('/login/')
        assert 'name="username"' in resp.text
        assert 'type="text"' in resp.text

    def test_login_page_has_password_input(self, client):
        resp = client.get('/login/')
        assert 'name="password"' in resp.text
        assert 'type="password"' in resp.text

    def test_login_page_has_remember_me_checkbox(self, client):
        resp = client.get('/login/')
        assert 'name="remember_me"' in resp.text
        assert 'type="checkbox"' in resp.text
        assert 'value="1"' in resp.text
        assert 'checked' in resp.text

    def test_login_page_has_submit_button(self, client):
        resp = client.get('/login/')
        text = resp.text.lower()
        assert '<button' in text and 'type="submit"' in text

    def test_login_page_form_posts_to_same_url(self, client):
        resp = client.get('/login/')
        assert 'method="post"' in resp.text.lower()

    def test_login_page_labels_are_associated_with_inputs(self, client):
        resp = client.get('/login/')
        text = resp.text
        assert 'for="username"' in text
        assert 'id="username"' in text
        assert 'for="password"' in text
        assert 'id="password"' in text

    def test_login_page_has_no_legacy_asset_references(self, client):
        resp = client.get('/login/')
        text = resp.text.lower()
        for banned in ('combined.min.css', 'clientscript', 'mootools', 'uniform'):
            assert banned not in text, f'legacy reference {banned!r} still present'

    def test_login_page_has_no_static_style_reference(self, client):
        resp = client.get('/login/')
        assert 'static/style' not in resp.text.lower()

    def test_login_page_references_tailwind_cdn(self, client):
        resp = client.get('/login/')
        assert 'static/scripts/vendor/new-ui/tailwindcss-cdn.js' in resp.text

    def test_login_page_references_design_tokens(self, client):
        resp = client.get('/login/')
        text = resp.text
        assert '--cp-bg' in text
        assert 'bg-cp-bg' in text
        assert 'bg-cp-card' in text
        assert 'border-cp-border' in text

    def test_login_page_references_inter_font(self, client):
        resp = client.get('/login/')
        assert 'Inter' in resp.text

    def test_login_page_focus_ring_matches_design_system(self, client):
        resp = client.get('/login/')
        assert 'focus:ring-2' in resp.text
        assert 'focus:ring-cp-accent' in resp.text

    def test_login_page_defaults_to_dark_html_class(self, client):
        resp = client.get('/login/')
        assert '<html lang="en" class="dark">' in resp.text


class TestLoginPageBehaviourUnchanged:
    """login_post must keep authenticating with the same field names."""

    def test_login_with_correct_credentials(self, client):
        from couchpotato.core.helpers.variable import md5
        Env.setting('password', value=md5('secret'))

        resp = client.post('/login/', data={
            'username': 'admin',
            'password': 'secret',
        }, follow_redirects=False)

        assert resp.status_code == 302
        assert 'user' in resp.cookies or 'set-cookie' in resp.headers

    def test_login_with_wrong_credentials_does_not_set_cookie(self, client):
        resp = client.post('/login/', data={
            'username': 'admin',
            'password': 'wrong',
        }, follow_redirects=False)

        assert resp.status_code == 302
        assert 'user' not in resp.cookies
