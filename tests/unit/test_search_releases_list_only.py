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


@pytest.fixture(autouse=True)
def _db_available():
    """A working database for every test in this module.

    _searchReleases' AC4 pre-flight now resolves the profile through the DB
    rather than trusting a truthy profile_id (a DANGLING id used to skip the
    check and be reported as a completed search). The view tests previously
    patched only fireEvent, so they had no db at all. Tests that care about
    specific db behaviour patch get_db themselves; an inner patch wins, so this
    only supplies the boring "profiles exist" default.
    """
    db = MagicMock()
    db.get.return_value = _profile()
    with patch('couchpotato.core.media.movie.searcher.get_db', return_value=db):
        yield db


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


def _drive(searcher, movie, no_results=False, restatus_to=None, **kwargs):
    """Run single() with the surrounding plumbing mocked, returning the
    fireEvent calls so the assertions can look at what it actually did.

    `no_results` models the common provider failure mode: implementations
    swallow connection/HTTP errors and simply return nothing.

    `restatus_to` makes the media.restatus stub WRITE that status to the movie,
    the way the real event does. Leave it None for tests that don't care.
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
            # The real media.restatus (_base/media/main.py) COMPUTES a status
            # and writes it to the doc. This stub used to just echo
            # movie['status'] with no side effect, which made
            # "a list-only search does not change status" unobservable: the
            # only thing that can change status never changed anything, so the
            # assertion passed no matter what single() did. Mirror the real
            # contract -- a movie holding a 'done' release restatuses to 'done'.
            movie['status'] = restatus_to if restatus_to is not None else movie['status']
            return movie['status']
        if name == 'profile.default':
            # A CONCRETE id. Returning None made two assertions blind: assigning
            # `movie['profile_id'] = <resolved>` was invisible because the
            # resolved value was also None, and "uses the default profile" could
            # not check which profile was actually used.
            return {'_id': 'default-profile-1'}
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


def _view_events(movie, protocols=('nzb',), default_profile=None):
    """fireEvent stub for the VIEW-level tests (_searchReleases).

    Models an install that can actually search: a movie exists, and at least one
    protocol is enabled. `searcher.protocols` matters because _searchReleases
    now pre-flights it — getSearchProtocols returns [] (it does not raise) when
    no downloader is enabled, and single() would then "search" an empty protocol
    list, contacting nothing while reporting success.
    """
    def _fire(name, *a, **k):
        if name == 'media.get':
            return movie
        if name == 'searcher.protocols':
            return list(protocols)
        if name == 'profile.default':
            return default_profile
        return None
    return _fire


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
            fire.side_effect = _view_events(movie)
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
            fire.side_effect = _view_events(movie)
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


class TestSearchButtonUpdatesInPlace:
    """FEAT-008 AC5/AC6: the button must update the release list in place and
    report which of the three outcomes happened -- not reload the whole page
    and leave the user guessing whether anything ran.

    Renders the real template (not a copy) and inspects the `@click` handler
    source, mirroring TestMovieDetailButton above.
    """

    def _render(self, status):
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

    def _search_button_handler(self, html):
        """Isolate the search-releases button's own onclick markup so
        assertions can't accidentally pass by matching some OTHER button's
        handler (e.g. Refresh, which legitimately still reloads)."""
        idx = html.index('data-testid="search-releases"')
        # The @click attribute is emitted before data-testid on this button;
        # walk back to the start of the <button> tag it belongs to.
        start = html.rindex('<button', 0, idx)
        end = html.index('</button>', idx)
        return html[start:end]

    def test_the_search_button_no_longer_forces_a_full_page_reload(self):
        handler = self._search_button_handler(self._render('done'))

        assert 'location.reload()' not in handler, (
            'AC5: the release list must update in place, not via a full reload'
        )

    def test_the_search_button_refreshes_the_release_list_via_htmx(self):
        handler = self._search_button_handler(self._render('done'))

        # See the restore-template test for why this must be cpSwap: a bare
        # htmx.ajax cannot report failure, so the release list could silently
        # stay stale after a failed refresh.
        assert 'cpSwap(' in handler, 'the swap must go through the error-aware wrapper'
        assert 'htmx.ajax' not in handler
        assert 'partial/movie/movie-1/releases' in handler
        assert '#movie-releases' in handler
        # The endpoint's own root element already has id="movie-releases"
        # (partials/movie_releases.html) -- an innerHTML swap would nest a
        # second copy of that id inside the first. outerHTML replaces the
        # node itself, matching every other swap against this same target
        # (the filter form / sort links in movie_releases.html).
        assert 'outerHTML' in handler

    def test_the_search_button_reports_the_three_outcomes(self):
        """AC3/AC5: the toast text must actually branch on `searched`/
        `reason`, not just the old `success`/`found` shape -- otherwise a
        could-not-search outcome (searched: false) would still be reported
        as if a search ran and found nothing."""
        handler = self._search_button_handler(self._render('done'))

        assert 'd.searched' in handler, (
            'the handler must branch on the new searched/found/reason '
            'contract to tell "found nothing" apart from "could not search"'
        )
        assert 'd.reason' in handler, (
            'a could-not-search outcome must surface its reason to the user'
        )


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
            fire.side_effect = _view_events(movie)
            return searcher.searchReleasesView(media_id='movie-1')

    def test_available_counts_only_available_releases(self, searcher):
        """`available` is the total the movie now holds."""
        result = self._view(searcher, [
            {'status': 'available', 'quality': '2160p'},
            {'status': 'available', 'quality': '1080p'},
            {'status': 'done', 'quality': '720p'},
            {'status': 'failed', 'quality': '720p'},
            {'status': 'ignored', 'quality': 'brrip'},
        ])

        assert result['available'] == 2

    def test_found_reports_what_THIS_search_produced_not_the_running_total(self, searcher):
        """A movie with existing releases whose search finds nothing must not
        report a win.

        `found` used to be the total count of available releases, so a movie
        holding 3 of them reported "Found 3 releases" in green after a search
        that contacted providers and got nothing -- a total provider outage
        looked like success. It is now the delta this search produced; the
        running total is `available`.
        """
        result = self._view(searcher, [
            {'status': 'available', 'quality': '2160p'},
            {'status': 'available', 'quality': '1080p'},
            {'status': 'available', 'quality': '720p'},
        ])

        assert result['found'] == 0, 'a search that added nothing must report found=0'
        assert result['available'] == 3

    def test_no_available_releases_reports_zero(self, searcher):
        result = self._view(searcher, [{'status': 'done', 'quality': '720p'}])

        assert result['found'] == 0

    def test_a_failure_inside_the_search_does_not_500(self, searcher):
        """single() can raise for a movie with incomplete info -- e.g. a
        library import with no 'year', which single() indexes directly. Its
        siblings tryNextRelease and markFailedAndResearch both wrap their work;
        this view did not, so a plausible edge case for exactly the movies
        this feature targets returned a 500 instead of a handled failure.

        FEAT-008: the return shape gained `searched`/`reason` (AC3) -- an
        exception is a "could not search" outcome, so `searched` must be
        False here too, not just `success`."""
        movie = _movie(status='done')

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', side_effect=KeyError('year'), create=True):
            fire.side_effect = _view_events(movie)
            result = searcher.searchReleasesView(media_id='movie-1')

        assert result['success'] is False
        assert result['found'] == 0
        assert result['searched'] is False, (
            'an exception means no search actually completed -- searched must be False'
        )
        assert result.get('reason'), 'a could-not-search outcome must name a reason'

    def test_a_movie_that_no_longer_exists_is_reported_as_a_failure(self, searcher):
        """The detail page can be open while the movie is deleted in another
        tab; the click must not report success for a search that never ran.

        FEAT-008: same shape update as the exception case above -- a movie
        that vanished is "could not search", not "searched, found 0"."""
        with patch('couchpotato.core.media.movie.searcher.fireEvent', return_value=None), \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            result = searcher.searchReleasesView(media_id='gone')

        assert result['success'] is False
        assert result['found'] == 0
        assert result['searched'] is False
        assert result.get('reason')
        assert not single.called, 'no search should run for a movie that is gone'


class TestListOnlyOnAMovieWithNoProfile:
    """FEAT-008 / the 2026-07-31 bug report.

    `single()`'s first gate is:

        if not movie['profile_id'] or (status in ('done','downloaded')
                                       and not manual and not list_only):

    `list_only` was threaded through every other gate but NOT through the
    no-profile clause, which is an independent `or`. Movies imported by the
    library scanner never get a profile, so on the reporter's production
    instance **1101 of 1101 movies have profile_id=None** and "Search for
    releases" returns `{'success': true, 'found': 0}` in 0.0s having searched
    nothing. That is indistinguishable from a real search that found nothing,
    which is why it reads as "it doesn't refresh / no way to know it finished".
    """

    def test_a_profileless_done_movie_is_still_searched(self, searcher):
        """AC1: the case the feature exists for must actually search."""
        movie = _movie(status='done')
        movie['profile_id'] = None

        calls = _drive(searcher, movie, list_only=True)

        assert 'searcher.search' in calls, (
            'a list-only search on a movie with no profile never reached the '
            'providers -- this is the reported bug'
        )

    def test_a_profileless_movie_uses_the_default_profile(self, searcher):
        """AC1: fall back the same way movie.add does, via profile.default."""
        movie = _movie(status='done')
        movie['profile_id'] = None

        calls = _drive(searcher, movie, list_only=True)

        assert 'profile.default' in calls, (
            'expected the default profile to be resolved for a profile-less movie'
        )

    def test_a_list_only_search_does_not_assign_a_profile_to_the_movie(self, searcher):
        """AC2: read-only. Answering "what's available?" must not edit the library."""
        movie = _movie(status='done')
        movie['profile_id'] = None

        _drive(searcher, movie, list_only=True)

        assert movie['profile_id'] is None, (
            'a list-only search assigned a profile to the movie; it must not '
            'mutate library state'
        )

    def test_list_only_makes_no_status_change_the_automatic_path_would_not(self, searcher):
        """AC2 / spec Risk 1: the list_only bypass must not introduce a status
        change of its own.

        This is deliberately DIFFERENTIAL rather than 'status is still done'.
        Both paths legitimately fire media.restatus -- the automatic path from
        inside the first gate, the list-only path from the restatus call that
        follows the title check
        -- and that event genuinely writes. So asserting a fixed value would
        either be wrong about real behaviour or (as the earlier version was)
        pass only because the restatus stub was inert and nothing in single()
        assigns to the movie dict directly.

        What actually matters is that list_only adds nothing: run both paths
        over identical movies with a restatus stub that really writes, and the
        resulting status must match. A stray `movie['status'] = ...` on the
        list-only branch fails this; the shared restatus write does not.
        """
        automatic = _movie(status='active')
        automatic['profile_id'] = 'profile-1'
        list_only = _movie(status='active')
        list_only['profile_id'] = 'profile-1'

        _drive(searcher, automatic, restatus_to='done')
        _drive(searcher, list_only, restatus_to='done', list_only=True)

        assert list_only['status'] == automatic['status'], (
            'the list-only path changed status in a way the automatic path '
            'does not: %r vs %r' % (list_only['status'], automatic['status'])
        )

    def test_the_automatic_path_still_returns_early_without_a_profile(self, searcher):
        """Risk guard: the non-list_only behaviour must be unchanged.

        A profile-less movie must still be skipped by the automatic searcher --
        widening the gate for everyone would start searching the entire library.

        status='active', NOT 'done', and that is the whole test. With 'done' the
        STATUS clause of the gate bails first and masks the profile clause
        entirely: disabling the profile clause outright
        (`not movie['profile_id'] and False`) left all 35 tests in this file
        green. Driving the real single() with status='active' shows the
        difference -- unmutated fires no search, mutated searches the whole
        library. A risk guard that the risk can walk straight past is worse than
        no guard, because it reads as covered.
        """
        movie = _movie(status='active')
        movie['profile_id'] = None

        calls = _drive(searcher, movie)          # no list_only, no manual

        assert 'searcher.search' not in calls, (
            'the automatic path now searches profile-less movies; the bypass '
            'must be limited to list_only'
        )


class TestSearchReleasesThreeWayOutcome:
    """FEAT-008 AC3/AC4: _searchReleases must let the UI tell apart

        1. searched, found N            -> searched=True,  found=N
        2. searched, found nothing      -> searched=True,  found=0
        3. could not search, with why   -> searched=False, reason=<str>

    `{'success': True, 'found': 0}` regardless of which of these happened
    (the pre-FEAT-008 shape) is exactly the "no way to know when the search
    is completed" bug report: a movie that was never searched at all looked
    identical to one that was searched and came up empty.
    """

    def test_a_completed_search_reports_searched_true_and_the_found_count(self, searcher):
        """A search that genuinely turns up new releases reports them.

        `single()` here ADDS releases, rather than being a no-op returning None.
        That matters: `found` is the delta this search produced, so a no-op mock
        against a movie that already holds releases would report found=0 and the
        test would be asserting the wrong thing for the right-looking reason.
        """
        movie = _movie(status='done', releases=[
            {'status': 'done', 'quality': '2160p'},
        ])

        def _adds_two(*a, **k):
            movie['releases'].extend([
                {'status': 'available', 'quality': '1080p'},
                {'status': 'available', 'quality': '720p'},
            ])

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', side_effect=_adds_two, create=True) as single:
            fire.side_effect = _view_events(movie)
            result = searcher.searchReleasesView(media_id='movie-1')

        assert single.called, 'a movie with a profile must actually be searched'
        assert result == {'success': True, 'searched': True,
                          'found': 2, 'available': 2}

    def test_a_completed_search_that_finds_nothing_is_still_searched_true(self, searcher):
        """The specific outcome the bug report described: a search that ran
        and genuinely found nothing must be distinguishable from one that
        never ran (both used to report the exact same payload)."""
        movie = _movie(status='done', releases=[])

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            fire.side_effect = _view_events(movie)
            result = searcher.searchReleasesView(media_id='movie-1')

        assert single.called
        assert result == {'success': True, 'searched': True,
                          'found': 0, 'available': 0}

    def test_no_profile_anywhere_reports_could_not_search_with_a_reason(self, searcher):
        """AC4: a movie with no profile_id, on an install with no default
        profile either (fresh install / every profile deleted), must refuse
        with a reason -- never a bare success, and never silently doing
        nothing while reporting 'found: 0' as if it had searched."""
        movie = _movie(status='done')
        movie['profile_id'] = None

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            fire.side_effect = _view_events(movie)
            result = searcher.searchReleasesView(media_id='movie-1')

        assert not single.called, (
            'with no profile resolvable anywhere, single() must never be '
            'invoked at all -- there is nothing to search with'
        )
        assert result['success'] is False
        assert result['searched'] is False
        assert result['found'] == 0
        assert isinstance(result.get('reason'), str) and result['reason'], (
            'a could-not-search outcome must name a reason the UI can show'
        )

    def test_a_profileless_movie_with_a_default_available_still_gets_searched(self, searcher):
        """The common real-world case (FEAT-008's actual bug): no profile on
        the movie, but the install has a default profile -- must search, not
        refuse."""
        movie = _movie(status='done')
        movie['profile_id'] = None

        fake_fire = _view_events(movie, default_profile={'_id': 'default-profile'})

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire), \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            result = searcher.searchReleasesView(media_id='movie-1')

        assert single.called, 'a default profile is available -- the search must run'
        assert result['searched'] is True
        assert result['success'] is True


class TestNeverSearchedIsNeverReportedAsSearched:
    """FEAT-008's core promise, tightened after review.

    A reviewer wired in the REAL searcher and counted actual provider calls:
    three further paths reached `searched: True, found: 0` having contacted
    nobody. The realistic one is "no downloader enabled" -- `getSearchProtocols`
    returns `[]` rather than raising (it even logs "There aren't any downloaders
    enabled"), `single()` then iterates an empty protocol list, and the user was
    told "Searched -- no releases found".

    That is the same lie the feature exists to remove, on a far more common
    trigger than the profile-less case that prompted it.
    """

    def test_no_enabled_downloader_refuses_rather_than_claiming_a_search(self, searcher):
        movie = _movie(status='done')

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            fire.side_effect = _view_events(movie, protocols=())
            result = searcher.searchReleasesView(media_id='movie-1')

        assert single.called is False, 'must not even call single() with no protocols'
        assert result['searched'] is False
        assert result['success'] is False
        assert 'downloader' in result['reason'].lower()

    def test_a_movie_with_no_usable_title_refuses(self, searcher):
        """single() bails read-only without a title, so no search happens."""
        movie = _movie(status='done')
        movie['title'] = ''
        movie['info'] = {'year': 2020, 'titles': []}

        with patch('couchpotato.core.media.movie.searcher.fireEvent') as fire, \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            fire.side_effect = _view_events(movie)
            result = searcher.searchReleasesView(media_id='movie-1')

        assert single.called is False
        assert result['searched'] is False
        assert 'title' in result['reason'].lower()

    def test_every_refusal_carries_a_reason_the_ui_can_show(self, searcher):
        """AC3: a refusal the user cannot act on is barely better than a lie."""
        movie = _movie(status='done')
        movie['profile_id'] = None

        # The 'no protocols' movie needs a REAL profile. With profile_id=None
        # the profile check in _searchReleases fires first, so both cases below
        # exercised the same branch and returned the same reason -- a loop that
        # read as "every refusal" while covering one of them.
        with_profile = _movie(status='done')
        with_profile['profile_id'] = 'profile-1'

        cases = {
            'no protocols': (with_profile, _view_events(with_profile, protocols=())),
            'no profile anywhere': (movie, _view_events(movie, default_profile=None)),
        }
        reasons = {}
        for label, (_case_movie, stub) in cases.items():
            with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=stub), \
                    patch.object(type(searcher), 'single', return_value=None, create=True):
                result = searcher.searchReleasesView(media_id='movie-1')

            assert result['searched'] is False, label
            assert result.get('reason'), 'no reason given for: %s' % label
            assert len(result['reason']) > 15, 'reason too terse to act on: %s' % label
            reasons[label] = result['reason']

        # Distinct branches must give distinct guidance -- "no downloader" and
        # "no profile" need different fixes from the user.
        assert reasons['no protocols'] != reasons['no profile anywhere'], (
            'both refusal branches returned the same reason (%r), so one of '
            'them is not actually being reached' % reasons['no protocols']
        )


class TestStaleProfileFallback:
    """The stale-profile branch in single() (the `except` around
    `db.get('id', profile_id)`) had ZERO coverage --
    _drive()'s db.get always succeeded, so ~20 lines of new code, including the
    `if not list_only: raise` that is the only thing preserving the automatic
    path's behaviour, were never executed. Both mutations below used to leave
    the whole suite green.
    """

    def _drive_with_stale_profile(self, searcher, movie, default_exists=True, **kwargs):
        """Like _drive, but db.get raises for the movie's (dangling) profile_id
        and resolves only the default profile."""
        calls = _Calls()
        fired = []

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
                return []
            if name == 'release.create_from_search':
                return []
            if name == 'quality.ishigher':
                return 'lower'
            if name == 'media.get':
                return movie
            if name == 'media.restatus':
                return movie['status']
            if name == 'profile.default':
                return {'_id': 'default-profile-1'} if default_exists else None
            return None

        def _get(index_name, key):
            if key == 'default-profile-1' and default_exists:
                return _profile()
            raise KeyError('Document not found: %s' % key)

        db = MagicMock()
        db.get.side_effect = _get
        env = MagicMock()
        env.prop.return_value = 0

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event), \
                patch('couchpotato.core.media.movie.searcher.get_db', return_value=db), \
                patch('couchpotato.core.media.movie.searcher.Env', env), \
                patch.object(type(searcher), 'conf', return_value=False, create=True), \
                patch.object(type(searcher), 'shuttingDown', return_value=False, create=True):
            searcher.single(movie, search_protocols=['nzb'], **kwargs)

        calls.fired = fired
        return calls

    def test_list_only_falls_back_to_the_default_when_the_profile_was_deleted(self, searcher):
        """Without this the user got "an unexpected error occurred" while a
        perfectly good default profile sat unused."""
        movie = _movie(status='done')
        movie['profile_id'] = 'deleted-profile'

        calls = self._drive_with_stale_profile(searcher, movie, list_only=True)

        assert 'searcher.search' in calls, (
            'a dangling profile reference aborted the list-only search instead '
            'of falling back to the default profile'
        )

    def test_it_gives_up_quietly_when_the_profile_is_stale_and_no_default_exists(self, searcher):
        movie = _movie(status='done')
        movie['profile_id'] = 'deleted-profile'

        calls = self._drive_with_stale_profile(
            searcher, movie, default_exists=False, list_only=True)

        assert 'searcher.search' not in calls
        assert 'media.delete' not in calls, 'gave up by deleting the movie'

    def test_the_automatic_path_still_raises_on_a_stale_profile(self, searcher):
        """Spec Risk 3: the non-list_only path must behave EXACTLY as before.
        The fallback is deliberately list-only; the automatic path must keep
        propagating the error so searchAll logs it rather than silently
        searching against a profile the user never chose.

        status='active' with a real-looking profile_id, so the gate lets it
        through and the stale db.get is actually reached.
        """
        movie = _movie(status='active')
        movie['profile_id'] = 'deleted-profile'

        with pytest.raises(KeyError):
            self._drive_with_stale_profile(searcher, movie)


class TestARestoredMovieIsPickedUpByTheAutomaticSearcher:
    """FEAT-008 AC5, verified against the REAL gate.

    test_restore_to_wanted.py used to check this by re-typing a copy of the
    gate expression into the test body and evaluating that. Replacing the whole
    gate in searcher.py with `if True:` -- i.e. nothing is ever searched --
    left it green, because it was only ever asserting that its own copied
    expression agreed with the movie dict.

    This drives single() itself, so it fails if the gate stops letting a
    restored movie through for any reason.
    """

    def test_a_movie_in_the_state_restore_to_wanted_leaves_it_gets_searched(self, searcher):
        # Exactly what restoreToWanted leaves behind -- INCLUDING the
        # preserved 'done' release AC3 requires it to keep.
        #
        # The release is the whole point. This test used to use _movie()'s
        # default of releases=[], a state restoreToWanted never produces, and
        # so it certified AC5 against a movie that could not exhibit the
        # problem: with the held release present, single()'s has_better_quality
        # loop counts it on the FIRST profile rung and breaks before any
        # provider is contacted, so the "restored" movie sat in Wanted forever
        # contacting nothing.
        restored = _movie(status='active', releases=[
            {'_id': 'held-1', 'status': 'ignored', 'quality': '2160p', 'is_3d': False},
        ])
        restored['profile_id'] = 'default-profile-1'

        calls = _drive(searcher, restored)

        assert 'searcher.search' in calls, (
            'a movie restored to wanted is not picked up by the automatic '
            "searcher -- it would sit in Wanted forever, which is the exact "
            'outcome AC5 exists to prevent'
        )

    def test_the_same_movie_without_a_profile_is_still_skipped(self, searcher):
        """The other direction: this must pass because the movie is restored
        properly, not because the gate lets everything through."""
        not_restored = _movie(status='active')
        not_restored['profile_id'] = None

        calls = _drive(searcher, not_restored)

        assert 'searcher.search' not in calls


class TestADanglingProfileIsNotReportedAsASuccessfulSearch:
    """AC4 hole (review, second round). The pre-flight only fired when
    `profile_id` was FALSY. A movie whose profile_id is truthy but points at a
    DELETED profile skipped it entirely, entered single(), hit the stale-profile
    fallback, found no default, and returned without contacting a provider --
    and _searchReleases then reported `searched: True, found: 0`.

    That is precisely AC4's named scenario ("every profile deleted") and
    precisely the lie FEAT-008 exists to remove: the UI showed
    "No new releases", so the user was told a search had happened when zero
    providers were queried.
    """

    def _drive_view(self, searcher, movie, known_profiles, default_profile=None):
        def _fire(name, *a, **k):
            if name == 'media.get':
                return movie
            if name == 'searcher.protocols':
                return ['nzb']
            if name == 'profile.default':
                return default_profile
            return None

        def _get(index_name, key):
            if key in known_profiles:
                return _profile()
            raise KeyError('Document not found: %s' % key)

        db = MagicMock()
        db.get.side_effect = _get
        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=_fire), \
                patch('couchpotato.core.media.movie.searcher.get_db', return_value=db), \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            result = searcher.searchReleasesView(media_id='movie-1')
        return result, single

    def test_a_stale_profile_with_no_default_refuses_instead_of_claiming_success(self, searcher):
        movie = _movie(status='done')
        movie['profile_id'] = 'deleted-profile'

        result, single = self._drive_view(searcher, movie, known_profiles=set())

        assert result['searched'] is False, (
            'reported a completed search for a movie whose profile no longer '
            'exists and for which no default could be resolved -- no provider '
            'was contacted'
        )
        assert result.get('reason'), 'a refusal must say why'
        assert single.called is False, 'single() was called despite nothing being searchable'

    def test_a_stale_profile_that_can_fall_back_to_a_default_still_searches(self, searcher):
        """The other direction: the fallback exists precisely so this case
        DOES search. Refusing here would break the repair path."""
        movie = _movie(status='done')
        movie['profile_id'] = 'deleted-profile'

        result, single = self._drive_view(
            searcher, movie,
            known_profiles={'default-profile-1'},
            default_profile={'_id': 'default-profile-1'})

        assert result['searched'] is True, (
            'refused a search that the stale-profile fallback can perform'
        )
        assert single.called is True


class TestAProfileWithNoQualitiesIsNotACompletedSearch:
    """Residual AC4 hole. The pre-flight checked that the profile RESOLVES, but
    single() iterates profile['qualities'] -- so a profile with an empty list
    contacts no provider at all while the view reported
    'searched: true, found: 0'. forceDefaults strips ''/'-1' entries
    (plugins/profile/main.py), so an empty qualities list is reachable.
    """

    def test_it_refuses_rather_than_claiming_a_search(self, searcher):
        movie = _movie(status='done')
        movie['profile_id'] = 'empty-profile'

        def _fire(name, *a, **k):
            if name == 'media.get':
                return movie
            if name == 'searcher.protocols':
                return ['nzb']
            if name == 'profile.default':
                return None
            return None

        db = MagicMock()
        db.get.return_value = {'_id': 'empty-profile', 'qualities': []}

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=_fire), \
                patch('couchpotato.core.media.movie.searcher.get_db', return_value=db), \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            result = searcher.searchReleasesView(media_id='movie-1')

        assert result['searched'] is False, (
            'reported a completed search against a profile with no qualities, '
            'which iterates nothing and contacts no provider'
        )
        assert single.called is False

    def test_a_profile_with_qualities_is_still_accepted(self, searcher):
        """The other direction -- the check must not refuse a normal profile."""
        movie = _movie(status='done')
        movie['profile_id'] = 'profile-1'

        def _fire(name, *a, **k):
            if name == 'media.get':
                return movie
            if name == 'searcher.protocols':
                return ['nzb']
            return None

        db = MagicMock()
        db.get.return_value = _profile()

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=_fire), \
                patch('couchpotato.core.media.movie.searcher.get_db', return_value=db), \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            result = searcher.searchReleasesView(media_id='movie-1')

        assert result['searched'] is True
        assert single.called is True


class TestTheMoviesOwnEmptyProfileIsNotMaskedByTheDefault:
    """Residual half of the AC4 hole, and the reachable configuration.

    _resolvableProfileId falls back to the DEFAULT profile when the movie's own
    profile has no qualities -- but single() does not: it uses
    movie['profile_id'] whenever it is truthy and resolvable. So whenever a
    healthy default exists (the normal case) the pre-flight passed on the
    default while single() iterated the movie's EMPTY one, contacted no
    provider, and the view reported 'searched: true, found: 0'.

    The earlier test for this stubbed profile.default -> None, so it only
    covered the case where BOTH profiles are unusable -- passing for a
    configuration that is not the reachable one.
    """

    def test_a_healthy_default_does_not_mask_the_movies_empty_profile(self, searcher):
        movie = _movie(status='done')
        movie['profile_id'] = 'empty-profile'

        def _fire(name, *a, **k):
            if name == 'media.get':
                return movie
            if name == 'searcher.protocols':
                return ['nzb']
            if name == 'profile.default':
                return {'_id': 'good-default'}      # a perfectly healthy default
            return None

        def _get(index_name, key):
            if key == 'empty-profile':
                return {'_id': 'empty-profile', 'qualities': []}
            if key == 'good-default':
                return _profile()
            raise KeyError(key)

        db = MagicMock()
        db.get.side_effect = _get

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=_fire), \
                patch('couchpotato.core.media.movie.searcher.get_db', return_value=db), \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            result = searcher.searchReleasesView(media_id='movie-1')

        assert result['searched'] is False, (
            'the pre-flight approved the DEFAULT profile while single() would '
            "iterate the movie's own empty one, contacting no provider"
        )
        assert single.called is False


class TestADatabaseFaultIsNotReportedAsAMissingProfile:
    """A DB fault used to surface as "No quality profile is configured", which
    sends the user off to create a profile they already have. Mutation-caught:
    changing the handler to `except ZeroDivisionError` left the whole suite
    green, so the branch was shipped untested.
    """

    def test_it_says_the_profiles_could_not_be_read(self, searcher):
        movie = _movie(status='done')

        def _fire(name, *a, **k):
            if name == 'media.get':
                return movie
            if name == 'searcher.protocols':
                return ['nzb']
            return None

        db = MagicMock()
        db.get.side_effect = RuntimeError('database is locked')

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=_fire), \
                patch('couchpotato.core.media.movie.searcher.get_db', return_value=db), \
                patch.object(type(searcher), 'single', return_value=None, create=True) as single:
            result = searcher.searchReleasesView(media_id='movie-1')

        assert result['searched'] is False
        assert single.called is False
        reason = result.get('reason', '').lower()
        assert 'read' in reason and 'profile' in reason, (
            'a database fault must not be reported as a configuration problem: %r'
            % result.get('reason')
        )


class TestARestoredMovieSearchesOnADefaultProfile:
    """The configuration every real install actually has.

    _profile() here uses finish=[True, True, True], matching what
    plugins/profile/main.py creates for every seeded profile ("take the best
    thing available now, then stop"). On that profile a held release satisfies
    quality.isfinish at ANY rung, and single()'s has_better_quality loop counts
    any release whose status is not in ('available', 'ignored', 'failed') --
    so a restored movie holding a 'done' release contacts zero providers.

    restoreToWanted marks the held releases 'ignored' precisely so this works.
    The earlier AC5 test used releases=[] -- a state restoreToWanted never
    produces -- and so certified this against a movie that could not exhibit
    the problem.
    """

    def test_the_held_release_no_longer_blocks_the_search(self, searcher):
        restored = _movie(status='active', releases=[
            {'_id': 'held-1', 'status': 'ignored', 'quality': '2160p', 'is_3d': False},
        ])
        restored['profile_id'] = 'profile-1'

        calls = _drive(searcher, restored)

        assert 'searcher.search' in calls, (
            'a restored movie contacts no providers on a default profile -- it '
            'would sit in Wanted forever'
        )

    def test_the_same_movie_still_blocked_if_the_release_were_left_done(self, searcher):
        """The other direction, so the test above cannot pass for the wrong
        reason: leave the held release 'done' and the search must NOT run."""
        not_restored = _movie(status='active', releases=[
            {'_id': 'held-1', 'status': 'done', 'quality': '2160p', 'is_3d': False},
        ])
        not_restored['profile_id'] = 'profile-1'

        calls = _drive(searcher, not_restored)

        assert 'searcher.search' not in calls
