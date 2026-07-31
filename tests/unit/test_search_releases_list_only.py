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


class _Calls(list):
    """A list of fired event NAMES that also carries the full (name, args,
    kwargs) tuples, so a test can assert HOW an event was fired and not merely
    that it was."""
    fired = ()


def _drive(searcher, movie, no_results=False, **kwargs):
    """Run single() with the surrounding plumbing mocked, returning the
    fireEvent calls so the assertions can look at what it actually did.

    `no_results` models the common provider failure mode: implementations
    swallow connection/HTTP errors and simply return nothing.
    """
    calls = _Calls()
    fired = []
    found = [] if no_results else [{'name': 'Some.Movie.2160p', 'url': 'http://x/1', 'score': 10}]

    def fake_fire_event(name, *args, **kw):
        calls.append(name)
        fired.append((name, args, kw))
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
            return [] if no_results else ['rel-%d' % len(calls)]
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

    calls.fired = fired          # attach so callers can inspect kwargs too
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


    def test_the_movie_is_touched_so_the_results_survive_cleanup(self, searcher):
        """release.cleanDone() deletes every 'available' release for a movie
        whose last_edit is older than a week, and a 'done' movie's last_edit
        is typically months old. So the last_edit bump is load-bearing here:
        without it the releases this search just surfaced get swept before
        the user can pick one, and the feature is silently useless.

        This is the one mutation a list-only search does make, and it is
        deliberate -- hence a test rather than a gate.
        """
        calls = _drive(searcher, _movie(status='done'), list_only=True)

        tag_calls = [f for f in calls.fired if f[0] == 'media.tag']
        assert tag_calls, 'the movie was never touched, so cleanDone will sweep the results'
        # Asserting the kwarg, not just the event name: without update_edited
        # the tag is added but last_edit is untouched, and the protection this
        # test exists for does not happen.
        assert tag_calls[0][2].get('update_edited') is True


class TestListOnlyIsNonDestructive:
    """Two data-loss paths the list-only bypass newly reaches.

    Both were previously unreachable for a done/downloaded movie because the
    status short-circuit returned before them. Bypassing that gate exposed
    them, so list-only has to opt out of each.
    """

    def test_it_never_deletes_a_movie_with_no_title(self, searcher):
        """single() deletes any movie whose title won't resolve -- reasonable
        for the automatic path (it cannot be searched), catastrophic for a
        read-only 'show me what's available' action on a library record."""
        movie = _movie(status='done')
        movie['title'] = ''
        movie['info'] = {'year': 2020}

        calls = _drive(searcher, movie, list_only=True)

        assert 'media.delete' not in calls, (
            'a list-only search deleted the library record'
        )

    def test_it_does_not_delete_existing_releases_when_providers_return_nothing(self, searcher):
        """single() removes previously-available releases the current search
        did not return. Providers routinely swallow connection errors and
        return [], so one failed search would wipe the release list the user
        opened the page to look at."""
        movie = _movie(status='done', releases=[
            {'_id': 'old-1', 'status': 'available', 'quality': '1080p',
             'identifier': 'kept', 'is_3d': False},
        ])

        calls = _drive(searcher, movie, list_only=True, no_results=True)

        assert 'release.delete' not in calls, (
            'a list-only search whose providers returned nothing deleted the '
            'movie\'s existing releases'
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

    def test_the_search_is_not_served_from_cache(self, searcher):
        """A user pressing "Search for releases" is asking what is available
        NOW. single() derives bypass_cache from `manual`, so without it the
        click is answered from the 30-minute provider cache -- stale results
        for an explicitly user-initiated action.

        manual=True is also the established idiom for "a human asked for
        this" across try_next and mark_failed. It cannot cause a download
        here: list_only short-circuits the download gate regardless.
        """
        movie = _movie(status='done')

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            fire.side_effect = lambda name, *a, **k: movie if name == 'media.get' else None
            searcher.searchReleasesView(media_id='movie-1')

        assert single.call_args.kwargs.get('manual') is True, (
            'without manual=True the search is answered from the provider '
            'cache, so a user-initiated refresh can return stale results'
        )

    def test_a_cached_search_would_still_not_download(self, searcher):
        """manual=True widens what is searched (it also ignores the ETA
        gate). Pin that this cannot turn the list-only action into a
        downloading one."""
        calls = _drive(searcher, _movie(status='done'), list_only=True, manual=True)

        assert 'release.try_download_result' not in calls


class TestMovieDetailButton:
    """AC8 -- the action has to be reachable from the UI, and specifically on
    a movie that is already done, since that is the case it exists for."""

    def _render(self, status):
        # partials/movie_detail.html {% include %}s partials/movie_releases.html
        # (FEAT-007 Part B) and gets its `title` from couchpotato.ui._releases_ctx()
        # rather than recomputing it locally (that recompute was deleted so
        # there is exactly one title derivation, not two that can drift) --
        # build the same context the real routes do, mirroring
        # tests/unit/test_review_actions_ui_template.py's `_render`.
        from couchpotato.environment import Env
        from couchpotato.ui import _jinja, _releases_ctx

        Env.set('web_base', '/')
        movie = {
            '_id': 'movie-1',
            'title': 'Some Movie',
            'status': status,
            'releases': [],
            'info': {'year': 2020},
            'identifiers': {'imdb': 'tt1234567'},
        }
        ctx = {
            'api_key': 'test-key',
            'api_base': '/api/key',
            'web_base': '/',
            'new_base': '/',
            'movie': movie,
        }
        ctx.update(_releases_ctx(movie, movie['_id'], {}))
        return _jinja.get_template('partials/movie_detail.html').render(**ctx)

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


class TestListOnlyImpliesFreshResults:
    """list_only on its own must not be served from cache, so a future caller
    of the movie.searcher.single event cannot accidentally get stale results
    by forgetting manual=True."""

    def test_list_only_alone_bypasses_the_cache(self, searcher):
        import inspect

        from couchpotato.core.media.movie.searcher import MovieSearcher

        source = inspect.getsource(MovieSearcher.single)

        assert 'bypass_cache = manual or list_only' in source


class TestFoundCount:
    """The count the toast reports, exercised against real release data
    rather than inferred from a mocked-out single()."""

    def _view(self, searcher, releases):
        movie = _movie(status='done', releases=releases)

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', return_value=None, create=True):
            fire.side_effect = lambda name, *a, **k: movie if name == 'media.get' else None
            return searcher.searchReleasesView(media_id='movie-1')

    def test_it_counts_only_available_releases(self, searcher):
        result = self._view(searcher, [
            {'status': 'available', 'quality': '2160p'},
            {'status': 'available', 'quality': '1080p'},
            {'status': 'done', 'quality': '720p'},
            {'status': 'failed', 'quality': '720p'},
            {'status': 'ignored', 'quality': 'brrip'},
        ])

        assert result['found'] == 2

    def test_no_available_releases_reports_zero(self, searcher):
        result = self._view(searcher, [{'status': 'done', 'quality': '720p'}])

        assert result['found'] == 0

    def test_a_failure_inside_the_search_does_not_500(self, searcher):
        """single() can raise for a movie with incomplete info -- e.g. a
        library import with no 'year', which single() indexes directly. Its
        siblings tryNextRelease and markFailedAndResearch both wrap their work;
        this view did not, so a plausible edge case for exactly the movies
        this feature targets returned a 500 instead of a handled failure."""
        movie = _movie(status='done')

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', side_effect=KeyError('year'), create=True):
            fire.side_effect = lambda name, *a, **k: movie if name == 'media.get' else None
            result = searcher.searchReleasesView(media_id='movie-1')

        assert result == {'success': False, 'found': 0}

    def test_a_movie_that_no_longer_exists_is_reported_as_a_failure(self, searcher):
        """The detail page can be open while the movie is deleted in another
        tab; the click must not report success for a search that never ran."""
        with patch('couchpotato.core.media.movie.searcher.fireEvent', return_value=None), \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            result = searcher.searchReleasesView(media_id='gone')

        assert result == {'success': False, 'found': 0}
        assert not single.called, 'no search should run for a movie that is gone'
