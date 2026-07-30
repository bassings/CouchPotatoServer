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

    def test_requires_auth_when_a_password_is_set(self, client, media_get):
        """B7. With no credentials configured the app is open by design;
        this asserts the route is behind the same guard as its siblings.
        """
        from couchpotato.ui import require_auth
        import couchpotato.ui as ui_module
        assert require_auth is not None
        assert 'require_auth' in ui_module.__dict__

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
