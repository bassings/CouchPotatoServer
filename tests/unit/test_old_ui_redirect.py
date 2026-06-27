"""Tests for the legacy /old UI redirect (specs/UI-MIGRATION.md step 1).

Every request to /old or /old/<anything> must return a permanent redirect (301)
to the web UI root — no content is served from the legacy stack.

Write-order: these tests were written BEFORE the implementation so they fail on
the original handler (which served views or self-redirected to /old/#…).
"""
import os

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import (
    api,
    api_docs,
    api_docs_missing,
    api_locks,
    api_nonblock,
)
from couchpotato.environment import Env

_UNSET = object()


# ---------------------------------------------------------------------------
# Fixtures — mirrors the setup in test_fastapi_web.py
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_env():
    """Minimal Env for testing, with full state restored on teardown."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    # Preserve web_base so per-test mutation (custom base) is parallel-safe.
    old_web_base = getattr(Env, '_web_base', _UNSET)

    Env.set("web_base", "/")
    Env.set("api_base", "/api/testkey123/")
    Env.set("static_path", "/static/")
    Env.set(
        "app_dir",
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )
    Env.set("dev", False)

    settings_data = {
        "username": "",
        "password": "",
        "api_key": "testkey123",
        "dark_theme": False,
    }
    original_setting = Env.setting

    def mock_setting(key=None, *args, **kwargs):
        if "value" in kwargs:
            settings_data[key] = kwargs["value"]
            return
        if key in settings_data:
            return settings_data[key]
        return kwargs.get("default", "")

    Env.setting = staticmethod(mock_setting)

    yield settings_data

    Env.setting = original_setting
    if old_web_base is _UNSET:
        if hasattr(Env, '_web_base'):
            delattr(Env, '_web_base')
    else:
        Env.set("web_base", old_web_base)
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

    return create_app("testkey123", "/")


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLegacyOldRedirect:
    """/old and /old/* must permanently redirect to the new UI root."""

    def test_old_root_redirects_to_web_base(self, client):
        """/old returns a 301 permanent redirect to /."""
        resp = client.get("/old", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers.get("location") == "/"

    def test_old_trailing_slash_redirects_in_one_hop(self, client):
        """/old/ returns a single 301 to / (no 307→301 double hop)."""
        resp = client.get("/old/", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers.get("location") == "/"

    def test_old_deep_path_redirects_to_web_base(self, client):
        """/old/some/deep/path returns a 301 permanent redirect to /."""
        resp = client.get("/old/some/deep/path", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers.get("location") == "/"

    def test_old_known_docs_route_redirects_not_serves(self, client):
        """/old/docs returns 301 to / rather than serving legacy API docs."""
        resp = client.get("/old/docs", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers.get("location") == "/"

    def test_old_appcache_redirects_not_serves(self, client):
        """/old/couchpotato.appcache returns 301 to / not legacy manifest."""
        resp = client.get("/old/couchpotato.appcache", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers.get("location") == "/"

    def test_old_redirect_with_custom_web_base(self, setup_env):
        """/cp/old/* redirects to /cp/ when the app is mounted under /cp/."""
        from couchpotato import create_app

        Env.set("web_base", "/cp/")
        app = create_app("testkey123", "/cp/")
        c = TestClient(app)

        resp = c.get("/cp/old", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers.get("location") == "/cp/"

        resp2 = c.get("/cp/old/some/route", follow_redirects=False)
        assert resp2.status_code == 301
        assert resp2.headers.get("location") == "/cp/"

    def test_old_redirect_does_not_require_auth(self, setup_env):
        """An unauthenticated visitor still gets a 301 from /old (no login gate).

        The redirect handler intentionally carries no auth dependency — auth is
        enforced once the visitor reaches the new UI root (see the companion
        new-UI gate test below).
        """
        from couchpotato import create_app

        setup_env["username"] = "admin"
        setup_env["password"] = "secret"
        app = create_app("testkey123", "/")
        c = TestClient(app)
        # No auth cookie set.
        resp = c.get("/old/some/page", follow_redirects=False)
        assert resp.status_code == 301
        assert resp.headers.get("location") == "/"

    def test_new_ui_root_gates_unauthenticated_visitor(self, setup_env):
        """The destination (/) enforces auth: an unauthenticated GET / redirects
        to /login/.

        This proves the /old redirect doesn't open an auth bypass — the visitor
        lands on the new UI, which still requires a session when credentials are
        configured.
        """
        from couchpotato import create_app

        setup_env["username"] = "admin"
        setup_env["password"] = "secret"
        app = create_app("testkey123", "/")
        c = TestClient(app)
        # No auth cookie set.
        resp = c.get("/", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "login" in resp.headers.get("location", "")
