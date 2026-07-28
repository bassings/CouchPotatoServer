"""Search for releases on a movie you already have (FEAT-005).

Owner's report: "they are marked as done, but I may want to download a better
version in the future should one come out, if I open the title it should
search for releases".

Three things blocked that, and `manual=True` alone fixes only the first:

1. `single()` short-circuits for `done`/`downloaded` movies.
2. The has-better-quality check breaks out of the quality loop -- for a movie
   that already holds its profile's top quality that is an immediate break, so
   nothing is searched at all.
3. The download gate is `force_download or not could_not_be_released or
   always_search`, and for a released movie the middle term is true -- so a
   manual search would SNATCH rather than list.

`list_only=True` addresses all three without touching the automatic path.
See specs/FEAT-005-search-releases-for-done-movies.md.
"""

from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.media.movie.searcher import MovieSearcher


@pytest.fixture
def searcher():
    s = MovieSearcher.__new__(MovieSearcher)
    return s


def _movie(status='done', releases=None):
    return {
        '_id': 'movie-1',
        'title': 'Some Movie',
        'profile_id': 'profile-1',
        'status': status,
        'releases': releases if releases is not None else [],
        'info': {'year': 2020, 'titles': ['Some Movie']},
        'identifiers': {'imdb': 'tt1234567'},
    }


def _profile():
    return {
        '_id': 'profile-1',
        'qualities': ['2160p', '1080p', '720p'],
        'finish': [True, True, True],
        'wait_for': [0, 0, 0],
        'stop_after': [0, 0, 0],
        '3d': [False, False, False],
        'minimum_score': 1,
    }


def _drive(searcher, movie, **kwargs):
    """Run single() with the surrounding plumbing mocked, returning the
    fireEvent calls so the assertions can look at what it actually did."""
    calls = []
    found = [{'name': 'Some.Movie.2160p', 'url': 'http://x/1', 'score': 10}]

    def fake_fire_event(name, *args, **kw):
        calls.append(name)
        if name == 'quality.pre_releases':
            return []
        if name == 'movie.update_release_dates':
            return {'theater': 1, 'dvd': 0}
        if name == 'quality.single':
            return {'identifier': kw.get('identifier', '1080p'), 'label': 'q'}
        if name == 'searcher.search':
            return list(found)
        if name == 'media.get':
            return movie
        if name == 'release.create_from_search':
            return ['rel-%d' % len(calls)]
        if name == 'release.try_download_result':
            return True
        if name == 'quality.ishigher':
            return 'equal'          # "we already have this" -> would break
        if name == 'media.restatus':
            return movie['status']
        return None

    db = MagicMock()
    db.get.return_value = _profile()
    env = MagicMock()
    env.prop.return_value = 0

    with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event), \
            patch('couchpotato.core.media.movie.searcher.get_db', return_value=db), \
            patch('couchpotato.core.media.movie.searcher.Env', env), \
            patch.object(type(searcher), 'conf', return_value=False, create=True), \
            patch.object(type(searcher), 'shuttingDown', return_value=False, create=True):
        searcher.single(movie, search_protocols=['nzb'], **kwargs)

    return calls


class TestListOnlySearchesDoneMovies:

    def test_a_done_movie_is_searched(self, searcher):
        """AC1: the short-circuit that normally returns early must not fire."""
        calls = _drive(searcher, _movie(status='done'), list_only=True)

        assert 'searcher.search' in calls

    def test_a_review_gated_movie_is_searched(self, searcher):
        """AC1: 'downloaded' is gated the same way as 'done'."""
        calls = _drive(searcher, _movie(status='downloaded'), list_only=True)

        assert 'searcher.search' in calls

    def test_nothing_is_downloaded(self, searcher):
        """AC2: the whole point -- list, do not snatch. The movie here is
        released, so the automatic path WOULD download."""
        calls = _drive(searcher, _movie(status='done'), list_only=True)

        assert 'release.try_download_result' not in calls

    def test_results_are_still_stored(self, searcher):
        """AC4: without this the search would be pointless -- the releases
        have to land somewhere the UI can show them."""
        calls = _drive(searcher, _movie(status='done'), list_only=True)

        assert 'release.create_from_search' in calls

    def test_every_profile_quality_is_searched(self, searcher):
        """AC3: quality.ishigher is stubbed to 'equal', i.e. "we already hold
        this" -- which makes the automatic path break out of the loop on the
        first quality. list_only must keep going so the user sees what exists
        at every quality in the profile."""
        movie = _movie(status='done', releases=[
            {'status': 'done', 'quality': '2160p', 'is_3d': False},
        ])

        calls = _drive(searcher, movie, list_only=True)

        assert calls.count('searcher.search') == 3, (
            'expected one search per profile quality, got %d'
            % calls.count('searcher.search')
        )


class TestAutomaticPathUnchanged:
    """AC6 -- list_only defaults false and must change nothing."""

    def test_a_done_movie_is_still_skipped_automatically(self, searcher):
        calls = _drive(searcher, _movie(status='done'))

        assert 'searcher.search' not in calls

    def test_the_has_better_quality_break_still_applies(self, searcher):
        """The automatic path must still stop once it holds the quality --
        that is what stops it re-grabbing forever."""
        movie = _movie(status='active', releases=[
            {'status': 'done', 'quality': '2160p', 'is_3d': False},
        ])

        calls = _drive(searcher, movie)

        assert calls.count('searcher.search') == 0

    def test_the_automatic_path_still_downloads(self, searcher):
        calls = _drive(searcher, _movie(status='active'))

        assert 'release.try_download_result' in calls


class TestApiView:
    """AC7 -- exposed so the UI can call it."""

    def test_search_releases_is_registered(self):
        import inspect

        from couchpotato.core.media.movie.searcher import MovieSearcher

        source = inspect.getsource(MovieSearcher.__init__)

        assert "addApiView('movie.searcher.search_releases'" in source

    def test_the_view_reports_how_many_were_found(self, searcher):
        movie = _movie(status='done')

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            fire.side_effect = lambda name, *a, **k: movie if name == 'media.get' else None
            result = searcher.searchReleasesView(media_id='movie-1')

        assert result.get('success') is True
        assert single.called, 'the view must actually run a search'
        assert single.call_args.kwargs.get('list_only') is True


class TestMovieDetailButton:
    """AC8 -- the action has to be reachable from the UI, and specifically on
    a movie that is already done, since that is the case it exists for."""

    def _render(self, status):
        import pathlib as _p

        from jinja2 import Environment, FileSystemLoader

        root = _p.Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates'
        env = Environment(loader=FileSystemLoader(str(root)), autoescape=True)
        tmpl = env.get_template('partials/movie_detail.html')
        return tmpl.render(movie={
            '_id': 'movie-1',
            'title': 'Some Movie',
            'status': status,
            'releases': [],
            'info': {'year': 2020},
            'identifiers': {'imdb': 'tt1234567'},
        }, url_base='/', api_base='/api/key')

    def test_the_button_is_rendered_for_a_done_movie(self):
        html = self._render('done')

        assert 'data-testid="search-releases"' in html
        assert 'Search for releases' in html

    def test_it_calls_the_list_only_endpoint(self):
        """A button wired to the wrong endpoint would download rather than
        list -- the exact behaviour this feature exists to avoid."""
        html = self._render('done')

        assert 'movie.searcher.search_releases' in html
        assert 'movie.searcher.full_search' not in html

    def test_it_is_also_available_while_awaiting_review(self):
        html = self._render('downloaded')

        assert 'data-testid="search-releases"' in html
