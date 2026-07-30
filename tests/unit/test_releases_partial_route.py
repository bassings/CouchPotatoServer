"""GET /partial/movie/<id>/releases -- the htmx endpoint behind the release
list's filter and sort controls (FEAT-007 Part B).

Follows the TestClient pattern in tests/unit/test_fastapi_web.py: build the
real app, register a stub `media.get` handler, and drive the route.
"""

import re

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

    def test_the_result_count_live_region_lives_in_the_static_shell(self):
        """B10: aria-live must exist in detail.html's STATIC markup, not only
        inside movie_releases.html. htmx's hx-swap-oob only updates an id
        that already exists in the document (htmx:oobErrorNoTarget silently
        drops it otherwise) -- and even the very FIRST render of the detail
        body arrives via detail.html's own hx-trigger="load" swap, so an
        announcer defined only inside the swapped-in partial would have no
        existing target on that first render and would never appear at all.
        Verified live in a browser: a marker property set on the node
        survives a subsequent filter/sort swap, proving it is the SAME DOM
        node throughout, and its text updates.
        """
        import pathlib

        template = (
            pathlib.Path(__file__).resolve().parents[2]
            / 'couchpotato' / 'ui' / 'templates' / 'detail.html'
        )
        content = template.read_text()
        assert 'id="release-count-announcer"' in content
        assert 'aria-live="polite"' in content

    def test_the_live_region_survives_a_swap_via_hx_swap_oob(self, client, media_get):
        """Regression: the aria-live count used to live INSIDE #movie-releases,
        which hx-swap="outerHTML" destroys and recreates on every filter/sort
        change -- a screen reader does not announce a brand-new node, only a
        mutation to one already in the accessibility tree. A persistent
        sr-only announcer outside #movie-releases (in detail.html's static
        shell -- see the test above), updated via hx-swap-oob="innerHTML"
        (not the bare "true" outerHTML shorthand, which would recreate the
        target node too), fixes that.
        """
        resp = client.get('/partial/movie/movie-1/releases')
        assert 'id="release-count-announcer"' in resp.text
        assert 'hx-swap-oob="innerHTML"' in resp.text

    def test_filter_selects_use_the_focus_visible_outline_idiom(self, client, media_get):
        """Regression (WCAG 2.4.7): the selects used `focus:outline-none` +
        `focus:border-cp-accent/30`, which loses to base.html's global
        `:focus-visible` outline rule on specificity and to the light
        theme's border override, leaving a keyboard-focused select
        indistinguishable from an unfocused one. They must use the same
        `focus-visible:outline...outline-cp-accent` idiom the sort links
        already use correctly.
        """
        resp = client.get('/partial/movie/movie-1/releases')
        assert 'focus:outline-none' not in resp.text
        assert resp.text.count('focus-visible:outline-cp-accent') >= 4, (
            '3 selects + the sort links should all use the idiom'
        )

    def test_each_sort_link_has_a_stable_id_for_htmx_focus_restoration(self, client, media_get):
        """Regression: htmx only restores keyboard focus after a swap when the
        pre-swap activeElement has an id it can find again in the
        swapped-in content. The sort header anchors had none, so focusing
        Size and pressing Enter measurably threw focus to <body>.
        """
        resp = client.get('/partial/movie/movie-1/releases')
        for key in ('name', 'quality', 'score', 'size', 'seeders', 'source', 'status', 'age'):
            assert 'id="sort-%s"' % key in resp.text

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

    def test_the_full_page_shell_forwards_query_params_into_its_own_hx_get(self, client, media_get):
        """(FEAT-007 B8, mutation-survivor 10b) detail_query has no dedicated
        unit test today -- replacing it with '' (never forwarding the query
        string) leaves the whole suite green. detail.html is a bare htmx
        shell: it is the ONLY place `?source=nzb&sort=size` can be applied on
        first paint, since the shell itself carries no releases content.
        """
        resp = client.get('/movie/movie-1?source=nzb&sort=size')

        assert resp.status_code == 200
        assert 'hx-get="/partial/movie/movie-1?source=nzb&amp;sort=size"' in resp.text

    def test_a_release_outside_the_profile_is_excluded_even_when_others_match(self, client):
        """(mutation-survivor 10a) Replacing the profile-quality matching
        filter in _releases_ctx with `list(all_releases)` (i.e. no filter at
        all) leaves the whole suite green today, because every existing
        fixture's releases already all match their movie's profile. Mix a
        matching and a non-matching quality on the SAME movie so an
        unfiltered pass-through is visibly wrong.
        """
        def handler(**kwargs):
            movie = dict(MOVIE, releases = [
                _release('hd', 'nzb', '1080p', 'available', 100, 5000),
                _release('sd', 'nzb', '480p', 'available', 100, 5000),
            ])
            return {'media': movie}

        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert 'hd.release.name' in resp.text
            assert 'sd.release.name' not in resp.text, (
                '480p is not in the profile\'s [1080p, 720p] qualities'
            )
            assert '1 of 1 release' in resp.text
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)

    def test_query_params_are_applied_on_the_full_page_partial_render(self, client, media_get):
        """(mutation-survivor 10c) `partial_movie_detail` (GET
        /partial/movie/{id}, the full detail body's own first-paint fetch)
        passes `dict(request.query_params)` into _releases_ctx --
        replacing that with `{}` (ignoring the query string on first paint)
        leaves the whole suite green today, since no existing test drives
        this specific route WITH query params.
        """
        resp = client.get('/partial/movie/movie-1?source=nzb')

        assert 'nzb1.release.name' in resp.text
        assert 'tor1.release.name' not in resp.text

    def test_filter_options_render_real_choices_not_just_the_static_all_option(self, client, media_get):
        """(mutation-survivor 10d) Replacing filter_options(...)'s wiring with
        empty lists leaves the whole suite green: every existing assertion
        checks the DEFAULT ('All ...') option, which renders regardless.
        Assert the data-driven <option>s (one per distinct quality/status/
        source actually present) are there too.
        """
        resp = client.get('/partial/movie/movie-1/releases')

        assert '<option value="nzb"' in resp.text
        assert '<option value="torrent"' in resp.text
        assert '<option value="1080p" >1080p</option>' in resp.text
        assert '<option value="720p" >720p</option>' in resp.text
        assert '<option value="available" >available</option>' in resp.text
        assert '<option value="ignored" >ignored</option>' in resp.text

    def test_a_stale_quality_filter_is_shown_as_the_true_selected_value(self, client, media_get):
        """(11b) A bookmarked/hand-edited URL can name a quality no CURRENT
        release offers. Without a fallback option, no <option> matches
        controls.quality, so the browser shows "All qualities" selected
        while the request is still actually filtering to zero results --
        the control would lie about what's applied.
        """
        resp = client.get('/partial/movie/movie-1/releases?quality=1440p')

        assert '<option value="all" >All qualities</option>' in resp.text, (
            "'All qualities' must NOT be marked selected -- it isn't what's applied"
        )
        assert '<option value="1440p" selected>1440p (no matches)</option>' in resp.text

    def test_a_stale_status_filter_is_shown_as_the_true_selected_value(self, client, media_get):
        """(11b) Same as the quality case: 'seeding' is a real, whitelisted
        status, but none of this movie's releases currently have it.
        """
        resp = client.get('/partial/movie/movie-1/releases?status=seeding')

        assert '<option value="seeding" selected>seeding (no matches)</option>' in resp.text

    def test_missing_size_renders_a_dash_not_a_lying_zero(self, client):
        """(11c) "0 MB" reads as an actual zero-byte release, not "unknown" --
        inconsistent with the deliberate blank Seeders already used for the
        same situation. Also asserts the column doesn't wrap (whitespace-nowrap).
        """
        def handler(**kwargs):
            movie = dict(MOVIE, releases = [
                {'_id': 'nosize', 'quality': '1080p', 'status': 'available',
                 'info': {'protocol': 'nzb', 'score': 10, 'age': 1, 'name': 'nosize.release.name'}},
            ])
            return {'media': movie}

        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert '0 MB' not in resp.text
            assert 'size not available' in resp.text
            assert 'whitespace-nowrap' in resp.text
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)

    def test_missing_seeders_has_an_sr_only_not_applicable_label(self, client, media_get):
        """(11d) An NZB's blank Seeders cell must not announce as just
        "blank" to a screen reader with no indication that is expected.
        """
        resp = client.get('/partial/movie/movie-1/releases')
        assert 'not applicable' in resp.text

    def test_the_scrolling_table_wrapper_is_keyboard_reachable(self, client, media_get):
        """(11i) A plain overflow-x-auto div is not in the tab order and has
        no accessible name, so a keyboard-only user has no way to scroll to
        the columns that overflow -- worse now that Size and Seeders added
        two more.
        """
        resp = client.get('/partial/movie/movie-1/releases')
        assert 'tabindex="0"' in resp.text
        assert 'role="region"' in resp.text
        assert 'aria-label="Releases table' in resp.text


class TestSeederHealthColour:
    """docs/design-system/README.md:149 / CONFORMANCE.md require seed colour
    by health (success / muted / warning). The now-accessible :root.light
    overrides in base.html (5.48:1 / 5.02:1 against the light theme's white
    cp-card) make the bare text-cp-success/warning tokens safe here.

    The Seeders <td> is found by COLUMN POSITION (regex over every
    `font-mono whitespace-nowrap` cell -- Size is first, Seeders second),
    not by text search: the row also contains a Source badge that
    legitimately uses text-cp-warning/success for unrelated reasons (NZB/
    Torrent colouring), so searching the whole row's text would false-match.
    """

    def _seeders_cell_class(self, resp_text):
        cells = re.findall(r'<td class="([^"]*font-mono whitespace-nowrap[^"]*)"', resp_text)
        assert len(cells) == 2, 'expected exactly Size then Seeders as font-mono whitespace-nowrap cells'
        return cells[1]

    def _movie_with_seeders(self, seeders):
        return dict(MOVIE, releases = [
            _release('r', 'torrent', '1080p', 'available', 10, 5000, seeders = seeders),
        ])

    def test_zero_seeders_is_warning(self, client):
        def handler(**kwargs):
            return {'media': self._movie_with_seeders(0)}
        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert 'text-cp-warning' in self._seeders_cell_class(resp.text)
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)

    def test_healthy_seeders_is_success(self, client):
        def handler(**kwargs):
            return {'media': self._movie_with_seeders(50)}
        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            assert 'text-cp-success' in self._seeders_cell_class(resp.text)
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)

    def test_a_weak_but_live_swarm_stays_muted_not_warning(self, client):
        """1-4 seeders is weak but not dead -- not alarming enough to warrant
        the warning colour."""
        def handler(**kwargs):
            return {'media': self._movie_with_seeders(2)}
        old = api.get('media.get')
        api['media.get'] = handler
        api_locks['media.get'] = __import__('threading').Lock()
        try:
            resp = client.get('/partial/movie/movie-1/releases')
            cell_class = self._seeders_cell_class(resp.text)
            assert 'text-cp-warning' not in cell_class
            assert 'text-cp-success' not in cell_class
            assert 'text-cp-muted' in cell_class
        finally:
            if old:
                api['media.get'] = old
            else:
                api.pop('media.get', None)
