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

    def test_login_page_allows_pinch_zoom(self, client):
        """A11Y (WCAG 1.4.4): the viewport must not disable user scaling — the
        legacy login page shipped `maximum-scale=1.0, user-scalable=no`, which
        blocks pinch-zoom for low-vision users. The ported page must match
        base.html and leave zoom enabled."""
        resp = client.get('/login/')
        assert 'user-scalable=no' not in resp.text
        assert 'maximum-scale' not in resp.text

    def test_login_page_honors_saved_light_theme(self, client):
        """The page ships the runtime theme-init that applies the user's saved
        'cp-theme' preference, so a light-theme user doesn't get a dark login."""
        resp = client.get('/login/')
        assert "localStorage.getItem('cp-theme')" in resp.text
        assert "classList.add('light')" in resp.text


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


class TestBootAfterLegacyAssetCleanup:
    """UI-CLEANUP-02 boot/smoke regression.

    UI-CLEANUP-01 kept `couchpotato/core/_base/clientscript.py` (the
    `ClientScript` plugin), its three compiled bundles
    (`combined.vendor.min.js`, `combined.base.min.js`,
    `combined.plugins.min.js`, `combined.min.css`), `couchpotato/templates/
    index.html`, and `couchpotato.index()` because `Userscript.iFrame` still
    called `index()` directly. Investigation confirmed that embed was already
    broken/unused (the API dispatch JSON-encodes the HTML instead of serving
    `text/html`), so UI-CLEANUP-02 deleted the whole chain: `iFrame`, `index()`,
    `index.html`, `clientscript.py`, and the four compiled bundles are all
    gone. These tests guard the boot path post-cleanup: the app must still
    start with no ClientScript plugin-load failure (there's nothing to fail to
    load — the plugin module itself is gone), and `/login/` must still render
    200.
    """

    def test_app_boots_and_login_still_returns_200(self, client):
        """The FastAPI app builds successfully and /login/ still renders."""
        resp = client.get('/login/')
        assert resp.status_code == 200

    def test_clientscript_module_no_longer_exists(self):
        """The ClientScript plugin module was deleted in UI-CLEANUP-02 —
        importing it must fail, not silently succeed."""
        import importlib

        with pytest.raises(ImportError):
            importlib.import_module('couchpotato.core._base.clientscript')

    def test_clientscript_source_file_is_gone(self):
        """The clientscript.py source file itself must no longer exist on
        disk (not just fail to import for some unrelated reason)."""
        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        file_path = os.path.join(app_dir, 'couchpotato', 'core', '_base', 'clientscript.py')
        assert not os.path.exists(file_path)

    def test_combined_bundles_are_gone(self):
        """The four compiled legacy bundles ClientScript used to serve must
        no longer exist on disk."""
        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        static_dir = os.path.join(app_dir, 'couchpotato', 'static')
        deleted = (
            os.path.join(static_dir, 'style', 'combined.min.css'),
            os.path.join(static_dir, 'scripts', 'combined.vendor.min.js'),
            os.path.join(static_dir, 'scripts', 'combined.base.min.js'),
            os.path.join(static_dir, 'scripts', 'combined.plugins.min.js'),
        )
        for file_path in deleted:
            assert not os.path.exists(file_path), f'legacy bundle still present: {file_path}'


class TestPreservedUserscriptChain:
    """UI-CLEANUP-01 kept clientscript.py + index.html + index() specifically
    because `Userscript.iFrame` depended on them. UI-CLEANUP-02 confirmed that
    embed was already broken/unused and deleted the whole chain, now that
    `userscript.add_via_url` is ported to the new UI independently (see
    UI-PORT-03) and no longer needs the iFrame/index() path. These tests guard
    the *new* state: `index()` is gone, `Userscript` no longer imports or calls
    it, `index.html` is gone, and the working `add_via_url` resolver is
    unaffected.
    """

    def test_couchpotato_index_no_longer_exists(self):
        """The userscript iFrame embed and its couchpotato.index() renderer
        were both deleted in UI-CLEANUP-02."""
        import couchpotato

        assert getattr(couchpotato, 'index', None) is None, (
            'couchpotato.index() should have been removed by UI-CLEANUP-02 — '
            'see specs/UI-MIGRATION.md.'
        )

    def test_index_html_template_is_gone(self):
        """The legacy index.html template must no longer exist on disk."""
        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        file_path = os.path.join(app_dir, 'couchpotato', 'templates', 'index.html')
        assert not os.path.exists(file_path)

    def test_userscript_no_longer_imports_or_calls_index(self):
        """Userscript must no longer import `index` from couchpotato or
        define an `iFrame` method — both were removed in UI-CLEANUP-02."""
        import inspect

        from couchpotato.core.plugins.userscript import main as userscript_main

        module_src = inspect.getsource(userscript_main)
        assert 'from couchpotato import index' not in module_src, (
            'Userscript still imports index from couchpotato — UI-CLEANUP-02 '
            'should have removed the legacy iFrame embed entirely.'
        )
        assert not hasattr(userscript_main.Userscript, 'iFrame'), (
            'Userscript.iFrame should have been deleted by UI-CLEANUP-02.'
        )

    def test_userscript_add_via_url_still_registered_and_callable(self):
        """The working `userscript.add_via_url` resolver (getViaUrl) must
        survive the cleanup — UI-PORT-03 surfaces it in the new UI."""
        from couchpotato.core.plugins.userscript.main import Userscript

        assert hasattr(Userscript, 'getViaUrl')
        assert callable(Userscript.getViaUrl)
