"""GET /partial/movie/<id>/releases -- the htmx endpoint behind the release
list's filter and sort controls (FEAT-007 Part B).

Follows the TestClient pattern in tests/unit/test_fastapi_web.py: build the
real app, register a stub `media.get` handler, and drive the route.
"""

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import api, api_locks
from couchpotato.environment import Env


@pytest.fixture(autouse=True)
def env(tmp_path):
    Env.set('web_base', '/')
    Env.set('api_base', '/api/testkey123/')
    Env.set('static_path', '/static/')
    Env.set('dev', False)
    yield


@pytest.fixture
def client():
    from couchpotato import create_app
    return TestClient(create_app('testkey123', '/'))


def _release(_id, protocol, quality, status, score, size, seeders = None):
    info = {'protocol': protocol, 'score': score, 'size': size, 'age': 3,
            'name': '%s.release.name' % _id}
    if seeders is not None:
        info['seeders'] = seeders
    return {'_id': _id, 'quality': quality, 'status': status, 'info': info}


MOVIE = {
    '_id': 'movie-1',
    'status': 'active',
    'info': {'titles': ['Some Movie'], 'year': 2026},
    'profile': {'label': 'HD', 'qualities': ['1080p', '720p']},
    'releases': [
        _release('nzb1', 'nzb', '1080p', 'available', 210, 8000),
        _release('tor1', 'torrent', '1080p', 'available', 3400, 24000, seeders = 900),
        _release('tor2', 'torrent', '720p', 'ignored', 50, 1200, seeders = 2),
    ],
}


@pytest.fixture
def media_get():
    def handler(**kwargs):
        return {'media': MOVIE}

    old = api.get('media.get')
    api['media.get'] = handler
    api_locks['media.get'] = __import__('threading').Lock()
    yield
    if old:
        api['media.get'] = old
    else:
        api.pop('media.get', None)


class TestReleasesPartialRoute:

    def test_returns_the_table_with_every_release_by_default(self, client, media_get):
        """B7."""
        resp = client.get('/partial/movie/movie-1/releases')
        assert resp.status_code == 200
        assert 'nzb1.release.name' in resp.text
        assert 'tor1.release.name' in resp.text

    def test_source_filter_is_honoured(self, client, media_get):
        """B7."""
        resp = client.get('/partial/movie/movie-1/releases?source=nzb')
        assert resp.status_code == 200
        assert 'nzb1.release.name' in resp.text
        assert 'tor1.release.name' not in resp.text

    def test_status_and_quality_filters_are_honoured(self, client, media_get):
        """B7."""
        resp = client.get('/partial/movie/movie-1/releases?status=ignored')
        assert 'tor2.release.name' in resp.text
        assert 'nzb1.release.name' not in resp.text

        resp = client.get('/partial/movie/movie-1/releases?quality=720p')
        assert 'tor2.release.name' in resp.text
        assert 'nzb1.release.name' not in resp.text

    def test_sort_is_honoured(self, client, media_get):
        """B7: biggest first when sorting by size descending."""
        resp = client.get('/partial/movie/movie-1/releases?sort=size&dir=desc')
        body = resp.text
        assert body.index('tor1.release.name') < body.index('nzb1.release.name')

        resp = client.get('/partial/movie/movie-1/releases?sort=size&dir=asc')
        body = resp.text
        assert body.index('tor2.release.name') < body.index('tor1.release.name')

    @pytest.mark.parametrize('query', [
        'sort=nonsense',
        'dir=sideways',
        'source=usenet',
        'status=../../etc/passwd',
        'sort=__class__&dir=',
        'quality=%00',
    ])
    def test_garbage_params_return_200_not_500(self, client, media_get, query):
        """B6: these URLs get bookmarked, shared and hand-edited."""
        resp = client.get('/partial/movie/movie-1/releases?%s' % query)
        assert resp.status_code == 200

    def test_size_and_seeders_are_rendered(self, client, media_get):
        """B9: both are in the data today but were never displayed."""
        resp = client.get('/partial/movie/movie-1/releases')
        assert 'Size' in resp.text
        assert 'Seeders' in resp.text
        assert '900' in resp.text, 'the torrent seeder count should appear'

    def test_aria_sort_reflects_the_active_column(self, client, media_get):
        """B10."""
        resp = client.get('/partial/movie/movie-1/releases?sort=size&dir=desc')
        assert 'aria-sort="descending"' in resp.text

        resp = client.get('/partial/movie/movie-1/releases?sort=size&dir=asc')
        assert 'aria-sort="ascending"' in resp.text

    def test_the_result_count_is_in_a_live_region(self, client, media_get):
        """B10: a filter change must be announced, not silent."""
        resp = client.get('/partial/movie/movie-1/releases')
        assert 'aria-live="polite"' in resp.text

    def test_an_unauthenticated_request_is_redirected_to_login(self, media_get):
        """B7: the route must be behind the same guard as its siblings.

        Asserting that the name `require_auth` is importable from
        `couchpotato.ui` would prove nothing about this route -- it would pass
        even if the route had no dependency at all. Configure credentials and
        make a real cookie-less request instead: `require_auth`
        (`couchpotato/__init__.py:74-80`) raises a 302 to the login page when
        `get_current_user` finds nobody.
        """
        settings_data = {
            'username': 'admin',
            'password': 'secret',
            'api_key': 'testkey123',
            'dark_theme': False,
        }
        original_setting = Env.setting

        def mock_setting(key = None, *args, **kwargs):
            if 'value' in kwargs:
                settings_data[key] = kwargs['value']
                return
            if key in settings_data:
                return settings_data[key]
            return kwargs.get('default', '')

        Env.setting = staticmethod(mock_setting)
        try:
            from couchpotato import create_app
            guarded = TestClient(create_app('testkey123', '/'), follow_redirects = False)
            resp = guarded.get('/partial/movie/movie-1/releases')
        finally:
            Env.setting = original_setting

        assert resp.status_code == 302
        assert resp.headers.get('location', '').endswith('/login/')

    def test_the_route_is_reachable_when_no_credentials_are_configured(self, client, media_get):
        """The complement: an open install (no username/password) is the
        default and must keep working, so the test above is proving the guard
        rather than a broken route.
        """
        assert client.get('/partial/movie/movie-1/releases').status_code == 200

    def test_a_movie_with_no_releases_renders_the_empty_state(self, client):
        """B14."""
        def handler(**kwargs):
            return {'media': dict(MOVIE, releases = [])}

        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert resp.status_code == 200
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)

    def test_a_failed_media_get_still_returns_a_page(self, client):
        """The detail page must not 500 because the API blew up."""
        def handler(**kwargs):
            raise RuntimeError('boom')

        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert resp.status_code == 200
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)
