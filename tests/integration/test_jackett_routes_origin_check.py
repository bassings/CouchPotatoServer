"""SEC-004 P2, AC-SEC-9 rule (b): the Jackett routes refuse a request with no same-origin evidence.

``torrentpotato.jackett_sync`` rewrites the torrentpotato rows and
``torrentpotato.jackett_test`` spends the stored Jackett key. Both are reachable
as a plain GET, which a cross-site ``<img>`` sends with no ``Origin`` and with a
``Referer`` the page can suppress, so a request carrying neither, or a foreign
one, must be refused with ``config.ini`` unchanged and no request made to
Jackett. The same-origin counterweight proves the guard is not refusing
everything.

The real provider registers its own routes into the real app (``create_app`` +
``TestClient``); only its network call is replaced, by a recorder.
"""
import os

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from couchpotato import ORIGIN_CHECKED_API_ROUTES, create_app
from couchpotato.environment import Env
from tests.helpers.combine_groups import group_settings, sha

pytestmark = pytest.mark.integration

API_KEY = 'placeholder-api-key-for-jackett-routes'
SAVED_URL = 'http://saved-jackett.invalid:9117'
SAVED_KEY = 'placeholder-saved-jackett-key'
ROUTES = ('torrentpotato.jackett_sync', 'torrentpotato.jackett_test')
INDEXERS_XML = (
    '<indexers><indexer id="alpha" configured="true"><title>Alpha</title></indexer></indexers>'
)
CROSS_ORIGIN_REFUSED = {'success': False, 'error': 'Cross-origin request refused'}


@pytest.fixture
def world(tmp_path, monkeypatch):
    stored = {'torrentpotato': {'jackett_url': SAVED_URL, 'jackett_api_key': SAVED_KEY}}
    with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
        monkeypatch.setattr(Env, '_settings', settings)
        monkeypatch.setattr(Env, '_web_base', '/', raising=False)
        monkeypatch.setattr(Env, '_api_base', '/api/%s/' % API_KEY, raising=False)
        monkeypatch.setattr(Env, '_static_path', '/static/', raising=False)
        monkeypatch.setattr(Env, '_app_dir', os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), raising=False)
        monkeypatch.setattr(Env, '_dev', False, raising=False)

        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        provider = TorrentPotato()
        requested = []
        monkeypatch.setattr(provider, 'urlopen',
                            lambda url, **kwargs: requested.append(url) or INDEXERS_XML)

        values = {'api_key': API_KEY, 'username': '', 'password': '', 'dark_theme': False,
                  'rate_limit_max': 0, 'rate_limit_window': 60, 'cors_origins': ''}
        with patch.object(Env, 'setting', side_effect=lambda key=None, *a, **kw: values.get(
                key, kw.get('default', ''))):
            app = create_app(api_key=API_KEY, web_base='/')
        yield settings, TestClient(app, raise_server_exceptions=False), requested


def url(route):
    return '/api/%s/%s/' % (API_KEY, route)


def test_both_routes_are_in_the_origin_checked_set():
    assert set(ROUTES) <= ORIGIN_CHECKED_API_ROUTES


@pytest.mark.parametrize('route', ROUTES)
class TestARequestWithoutSameOriginEvidenceIsRefused:

    def refused(self, settings, requested, response, before):
        assert response.status_code == 403, response.text
        assert response.json() == CROSS_ORIGIN_REFUSED
        assert sha(settings.file) == before, 'config.ini changed'
        assert requested == [], 'a request reached Jackett'

    def test_no_origin_and_no_referer(self, world, route):
        settings, client, requested = world
        before = sha(settings.file)

        self.refused(settings, requested, client.get(url(route)), before)

    def test_a_foreign_origin(self, world, route):
        settings, client, requested = world
        before = sha(settings.file)

        response = client.get(url(route), headers={'Origin': 'https://evil.invalid'})

        self.refused(settings, requested, response, before)

    def test_a_foreign_referer_and_no_origin(self, world, route):
        settings, client, requested = world
        before = sha(settings.file)

        response = client.get(url(route), headers={'Referer': 'https://evil.invalid/page'})

        self.refused(settings, requested, response, before)

    def test_a_post_with_a_foreign_origin_is_refused_too(self, world, route):
        settings, client, requested = world
        before = sha(settings.file)

        response = client.post(url(route), headers={'Origin': 'https://evil.invalid'})

        self.refused(settings, requested, response, before)


@pytest.mark.parametrize('route', ROUTES)
class TestTheFirstPartyCallersStillGetThrough:
    """The Settings button fetches with no parameters and the browser adds a
    same-origin Referer; the wizard does the same."""

    def test_a_same_origin_referer_reaches_the_handler(self, world, route):
        _, client, requested = world

        response = client.get(url(route), headers={'Referer': 'http://testserver/settings/'})

        assert response.status_code == 200
        assert response.json()['success'] is True
        assert len(requested) == 1
        assert requested[0].startswith(SAVED_URL)

    def test_a_same_origin_origin_header_reaches_the_handler(self, world, route):
        _, client, requested = world

        response = client.get(url(route), headers={'Origin': 'http://testserver'})

        assert response.status_code == 200
        assert response.json()['success'] is True
        assert len(requested) == 1
