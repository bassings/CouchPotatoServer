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
        """B14: genuinely nothing to show yet -- no heading, no table, no
        profile-hidden message. A bare 200 (the old assertion) also passes
        when the route dumps an unrelated error page, so it names nothing
        about what the empty state actually looks like.
        """
        def handler(**kwargs):
            return {'media': dict(MOVIE, releases = [])}

        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert resp.status_code == 200
            assert '<table' not in resp.text
            assert 'Releases</h2>' not in resp.text
            assert 'No releases match the selected profile qualities' not in resp.text
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)

    def test_releases_hidden_by_the_profile_are_distinguished_from_no_releases(self, client):
        """Regression: `total_releases` became the profile-matching count, and
        the template gated the ENTIRE releases block on it -- so a movie
        whose only release is a quality the profile doesn't want rendered an
        empty <div id="movie-releases"> with no heading, no table, and no
        explanation. Master rendered "No releases match the selected profile
        qualities." here; the user needs to be able to tell "nothing found
        yet" apart from "found releases your profile is hiding", since only
        the second is something they can act on (widen the profile).
        """
        def handler(**kwargs):
            movie = dict(MOVIE, releases = [
                _release('r480', 'nzb', '480p', 'available', 10, 100),
            ])
            return {'media': movie}

        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert resp.status_code == 200
            assert 'No releases match the selected profile qualities' in resp.text
            assert '<table' not in resp.text, (
                'nothing matches the profile, so there is nothing to put in a table'
            )
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


class TestMovieDetailHtmxBranch:
    """The filter form (partials/movie_releases.html) targets GET /movie/{id}
    directly rather than /partial/movie/{id}/releases, so its
    hx-push-url="true" pushes a URL that is also valid to land on directly --
    the standalone partial route returns a bare, unstyled fragment, which
    would look broken sitting in the address bar. movie_detail branches on
    the HX-Request header htmx sets on every request it issues: present ->
    the releases partial (matching #movie-releases, the form's hx-target);
    absent -> the ordinary full-page shell, unchanged.
    """

    def test_an_htmx_request_gets_the_releases_partial_not_the_shell(self, client, media_get):
        resp = client.get('/movie/movie-1', headers = {'HX-Request': 'true'})

        assert resp.status_code == 200
        assert 'id="movie-releases"' in resp.text
        assert 'id="movie-detail-container"' not in resp.text, (
            'an htmx (fragment) request must not get the full-page shell'
        )

    def test_an_htmx_request_honours_the_query_params(self, client, media_get):
        """Exactly what the filter form's serialized fields drive."""
        resp = client.get('/movie/movie-1', params = {'source': 'nzb'},
                           headers = {'HX-Request': 'true'})

        assert 'nzb1.release.name' in resp.text
        assert 'tor1.release.name' not in resp.text

    def test_a_plain_navigation_still_gets_the_full_page_shell(self, client, media_get):
        """No HX-Request header -- e.g. a browser reload of a pushed,
        filtered URL -- must still get detail.html, which re-fetches the
        filtered content itself (FEAT-007 B8), not the bare releases
        fragment.
        """
        resp = client.get('/movie/movie-1?source=nzb')

        assert resp.status_code == 200
        assert 'id="movie-detail-container"' in resp.text
        assert 'id="movie-releases"' not in resp.text

    def test_the_filter_form_pushes_a_bookmarkable_url(self, client, media_get):
        """Regression: the form used to target /partial/movie/{id}/releases
        with no hx-push-url at all, so a filter change never touched the
        address bar -- unlike the sort links a few lines below it, which
        already push a bookmarkable URL. A reload after filtering silently
        dropped the filter.
        """
        resp = client.get('/partial/movie/movie-1/releases')

        assert 'hx-push-url="true"' in resp.text
        assert 'hx-get="/movie/movie-1"' in resp.text, (
            'the form must fetch through movie_detail\'s own path, not the '
            'standalone partial route, so the pushed URL is valid to land on directly'
        )
