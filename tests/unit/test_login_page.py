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
    """UI-CLEANUP-01 boot/smoke regression.

    UI-CLEANUP-01 retired most of the legacy MooTools/SCSS asset layer, but
    `couchpotato/core/_base/clientscript.py` (the `ClientScript` plugin) and
    its three compiled bundles (`combined.vendor.min.js`,
    `combined.base.min.js`, `combined.plugins.min.js`, `combined.min.css`)
    were kept: `couchpotato.index()` — and therefore `index.html`, which
    calls `fireEvent('clientscript.get_styles'/'get_scripts')` — is still
    called directly by `Userscript.iFrame` (the `userscript` API view), so
    `clientscript.get_styles`/`get_scripts` remain registered events, unlike
    the rest of the legacy view machinery. These tests guard the boot path:
    the app must start with no ClientScript plugin-load failure, login must
    still render 200, and ClientScript's declared paths must point only at
    files that actually still exist on disk (not any of the deleted raw
    MooTools/SCSS sources).
    """

    def test_app_boots_and_login_still_returns_200(self, client):
        """The FastAPI app builds successfully and /login/ still renders."""
        resp = client.get('/login/')
        assert resp.status_code == 200

    def test_clientscript_module_imports_without_error(self):
        """Importing the ClientScript plugin module must not raise."""
        import importlib

        module = importlib.import_module('couchpotato.core._base.clientscript')
        assert hasattr(module, 'ClientScript')

    def test_clientscript_declared_paths_exist_on_disk(self):
        """ClientScript.paths must reference only surviving compiled bundles.

        Guards against a future edit deleting `combined.*.min.js`/
        `combined.min.css` while forgetting `ClientScript` still needs them
        (its `__init__` calls `os.path.getmtime` on each path and would
        raise `FileNotFoundError` at plugin-load time).
        """
        from couchpotato.core._base.clientscript import ClientScript

        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        for static_type, rel_paths in ClientScript.paths.items():
            for rel_path in rel_paths:
                file_path = os.path.join(app_dir, 'couchpotato', 'static', rel_path)
                assert os.path.isfile(file_path), (
                    f'ClientScript.paths[{static_type!r}] references missing file: {rel_path}'
                )

    def test_clientscript_paths_reference_no_deleted_legacy_assets(self):
        """None of ClientScript's declared paths point at assets removed by
        UI-CLEANUP-01 (mootools.js, couchpotato.js, page/block/library
        sources, raw *.scss, static/fonts, etc.)."""
        from couchpotato.core._base.clientscript import ClientScript

        banned = (
            'mootools', 'dynamics.js', 'fastclick.js', 'history.js',
            'Array.stableSort.js', 'requestAnimationFrame.js',
            'couchpotato.js', 'api.js', 'page.js', 'block.js',
            'page/', 'block/', 'library/', '.scss', 'fonts/',
        )
        all_paths = [p for paths in ClientScript.paths.values() for p in paths]
        for rel_path in all_paths:
            for token in banned:
                assert token not in rel_path, (
                    f'ClientScript.paths still references deleted legacy asset: {rel_path}'
                )


class TestPreservedUserscriptChain:
    """UI-CLEANUP-01 kept clientscript.py + index.html + index() specifically
    because `Userscript.iFrame` still depends on them. These tests guard that
    justification so a future 'cleanup' PR can't silently delete `index()` (which
    would break the userscript import) without a test going red — the deletion
    the audit *would* have made if the chain hadn't been traced.
    """

    def test_couchpotato_index_still_exists_and_is_callable(self):
        """The userscript add-via-URL embed renders through couchpotato.index()."""
        import couchpotato

        assert callable(getattr(couchpotato, 'index', None)), (
            'couchpotato.index() was removed, but Userscript.iFrame still calls '
            'it — see specs/UI-CLEANUP-01 / UI-MIGRATION.md before deleting it.'
        )

    def test_userscript_iframe_imports_and_calls_index(self):
        """Userscript.iFrame imports index from couchpotato and calls it. If
        index() is deleted, importing this plugin module raises ImportError —
        this test surfaces that as a clear failure at the call site."""
        import inspect

        from couchpotato.core.plugins.userscript import main as userscript_main

        module_src = inspect.getsource(userscript_main)
        assert 'from couchpotato import index' in module_src, (
            'Userscript no longer imports index from couchpotato — if the '
            'add-via-URL embed was ported/removed, update specs/UI-MIGRATION.md '
            'and UI-CLEANUP-02 may now delete the kept legacy chain.'
        )
        iframe_src = inspect.getsource(userscript_main.Userscript.iFrame)
        assert 'index()' in iframe_src, (
            'Userscript.iFrame no longer calls index() — re-evaluate whether the '
            'kept clientscript/index.html/combined-bundle chain is still needed.'
        )
