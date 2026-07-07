"""Tests for workflow Phase 3b (specs/DOWNLOADED-REVIEW-WORKFLOW.md): the
backend API views a Phase-3 UI will call for the "Downloaded / review" gate's
per-movie and per-release user actions.

Three routes are covered:

- `media.done` (`MediaPlugin.markDone`, couchpotato/core/media/_base/media/main.py)
  extended so that, in addition to setting the movie to 'done', it also
  completes the movie's landed release (the copy the user is confirming).
- `movie.searcher.mark_failed` (new; `MovieSearcher.markFailedView` /
  `.markFailedAndResearch`, couchpotato/core/media/movie/searcher.py) --
  marks the movie's landed release 'failed', resets the movie to 'active',
  and immediately triggers a manual re-search.
- `release.failed` (new; `Release.failedView`, couchpotato/core/plugins/release/main.py)
  -- a per-release "mark failed" action, mirroring the existing
  `release.ignore` view's shape.

Harness style mirrors test_downloaded_review_workflow_phase2.py: real plugin
methods exercised via `Plugin.__new__(Plugin)` (skips `__init__`'s event/api
registration side effects), with hand-rolled FakeDB objects and a
`fake_fire_event` dispatcher that only answers the exact events the method
under test is expected to call -- any unexpected event raises immediately so
a wiring mistake surfaces as a hard test failure rather than a silent no-op.
"""
from pathlib import Path
from unittest.mock import patch

from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.core.media._base.media.main import MediaPlugin
from couchpotato.core.media.movie.searcher import MovieSearcher
from couchpotato.core.plugins.release.main import Release


SEARCHER_SOURCE = Path(__file__).resolve().parents[2] / 'couchpotato' / 'core' / 'media' / 'movie' / 'searcher.py'
RELEASE_SOURCE = Path(__file__).resolve().parents[2] / 'couchpotato' / 'core' / 'plugins' / 'release' / 'main.py'


# --- MediaPlugin.markDone(): also completes the movie's landed release -----

class TestMarkDoneCompletesLandedRelease:

    def _run_mark_done(self, media_doc, releases, update_with_retry_result='write'):
        plugin = MediaPlugin.__new__(MediaPlugin)

        release_status_calls = []

        class FakeDB:
            def update_with_retry(self, mutator, doc_id, retries=3):
                assert doc_id == media_doc['_id']
                doc = dict(media_doc)
                if mutator(doc) is False:
                    return None
                if update_with_retry_result == 'conflict':
                    raise ConflictError(doc_id)
                return doc

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                assert args[0] == media_doc['_id']
                return [dict(r) for r in releases]
            if event == 'release.update_status':
                release_status_calls.append((args[0], kwargs.get('status')))
                return True
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.media._base.media.main.get_db', return_value=FakeDB()),
            patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=fake_fire_event),
        ):
            result = plugin.markDone(media_doc['_id'])

        return result, release_status_calls

    def test_downloaded_release_is_completed_alongside_the_movie(self):
        movie = {'_id': 'movie-1', 'status': 'downloaded'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]

        result, release_status_calls = self._run_mark_done(movie, releases)

        assert result == {'success': True}
        assert release_status_calls == [('release-1', 'done')]

    def test_snatched_and_seeding_releases_are_also_completed(self):
        """Any 'landed but not yet finalized' status counts, not just
        'downloaded' -- matches the spec's status list verbatim."""
        movie = {'_id': 'movie-1', 'status': 'downloaded'}
        releases = [
            {'_id': 'release-snatched', 'status': 'snatched'},
            {'_id': 'release-seeding', 'status': 'seeding'},
        ]

        _, release_status_calls = self._run_mark_done(movie, releases)

        assert ('release-snatched', 'done') in release_status_calls
        assert ('release-seeding', 'done') in release_status_calls
        assert len(release_status_calls) == 2

    def test_available_release_is_left_untouched(self):
        """An 'available' candidate release (never snatched) is not the
        landed copy -- it must not be silently marked done."""
        movie = {'_id': 'movie-1', 'status': 'downloaded'}
        releases = [{'_id': 'release-available', 'status': 'available'}]

        _, release_status_calls = self._run_mark_done(movie, releases)

        assert release_status_calls == []

    def test_already_done_ignored_and_failed_releases_are_left_alone(self):
        movie = {'_id': 'movie-1', 'status': 'downloaded'}
        releases = [
            {'_id': 'release-done', 'status': 'done'},
            {'_id': 'release-ignored', 'status': 'ignored'},
            {'_id': 'release-failed', 'status': 'failed'},
        ]

        _, release_status_calls = self._run_mark_done(movie, releases)

        assert release_status_calls == []

    def test_no_release_case_still_marks_movie_done(self):
        movie = {'_id': 'movie-1', 'status': 'downloaded'}

        result, release_status_calls = self._run_mark_done(movie, releases=[])

        assert result == {'success': True}
        assert release_status_calls == []

    def test_conflict_on_movie_update_returns_failure_without_touching_releases(self):
        """The pre-existing ConflictError -> {'success': False} contract
        must be preserved, and since the movie write never landed, the
        release-completion step must not run at all."""
        movie = {'_id': 'movie-1', 'status': 'downloaded'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]

        result, release_status_calls = self._run_mark_done(movie, releases, update_with_retry_result='conflict')

        assert result == {'success': False, 'error': 'Database busy, please retry'}
        assert release_status_calls == []


# --- MovieSearcher: "Mark Failed & re-search" -------------------------------

class TestMarkFailedAndResearch:

    def _run(self, media_doc, releases, media_get_result=None, update_with_retry_result='write'):
        searcher = MovieSearcher.__new__(MovieSearcher)

        release_status_calls = []
        single_search_calls = []

        class FakeDB:
            def update_with_retry(self, mutator, doc_id, retries=3):
                assert doc_id == media_doc['_id']
                doc = dict(media_doc)
                if mutator(doc) is False:
                    return None
                if update_with_retry_result == 'conflict':
                    raise ConflictError(doc_id)
                return doc

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                assert args[0] == media_doc['_id']
                return [dict(r) for r in releases]
            if event == 'release.update_status':
                release_status_calls.append((args[0], kwargs.get('status')))
                return True
            if event == 'media.get':
                return media_get_result
            if event == 'movie.searcher.single':
                single_search_calls.append((args[0], kwargs.get('manual')))
                return None
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.media.movie.searcher.get_db', return_value=FakeDB()),
            patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event),
        ):
            result = searcher.markFailedAndResearch(media_doc['_id'])

        return result, release_status_calls, single_search_calls

    def test_landed_release_marked_failed_not_ignored(self):
        """BLOCKING distinction from the pre-existing try_next/tryNextRelease
        view, which marks the old release 'ignored'. The spec calls for the
        bad copy to be marked 'failed' here instead."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]
        refreshed_movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1', 'releases': releases}

        result, release_status_calls, single_search_calls = self._run(
            movie, releases, media_get_result=refreshed_movie,
        )

        assert result is True
        assert release_status_calls == [('release-1', 'failed')]

    def test_movie_reset_to_active_and_research_triggered_exactly_once(self):
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]
        refreshed_movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1', 'releases': releases}

        result, _, single_search_calls = self._run(
            movie, releases, media_get_result=refreshed_movie,
        )

        assert result is True
        assert len(single_search_calls) == 1
        fired_media, fired_manual = single_search_calls[0]
        assert fired_media == refreshed_movie
        assert fired_manual is True

    def test_snatched_seeding_and_done_landed_releases_are_all_marked_failed(self):
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [
            {'_id': 'release-snatched', 'status': 'snatched'},
            {'_id': 'release-seeding', 'status': 'seeding'},
            {'_id': 'release-done', 'status': 'done'},
        ]
        refreshed_movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1'}

        _, release_status_calls, _ = self._run(movie, releases, media_get_result=refreshed_movie)

        assert ('release-snatched', 'failed') in release_status_calls
        assert ('release-seeding', 'failed') in release_status_calls
        assert ('release-done', 'failed') in release_status_calls
        assert len(release_status_calls) == 3

    def test_available_and_ignored_releases_are_not_touched(self):
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [
            {'_id': 'release-available', 'status': 'available'},
            {'_id': 'release-ignored', 'status': 'ignored'},
        ]
        refreshed_movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1'}

        _, release_status_calls, _ = self._run(movie, releases, media_get_result=refreshed_movie)

        assert release_status_calls == []

    def test_conflict_resetting_movie_status_returns_false_without_searching(self):
        """CAS conflict on the movie-status write must not crash, must
        report failure, and must not kick off a search against a movie
        whose status we couldn't confirm."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]

        result, _, single_search_calls = self._run(
            movie, releases, update_with_retry_result='conflict',
        )

        assert result is False
        assert single_search_calls == []

    def test_media_not_found_returns_false_without_searching(self):
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]

        result, _, single_search_calls = self._run(
            movie, releases, media_get_result=None,
        )

        assert result is False
        assert single_search_calls == []

    def test_view_wraps_result_in_success_dict(self):
        searcher = MovieSearcher.__new__(MovieSearcher)

        with patch.object(searcher, 'markFailedAndResearch', return_value=True) as mocked:
            result = searcher.markFailedView(media_id='movie-1')

        mocked.assert_called_once_with('movie-1')
        assert result == {'success': True}

    def test_view_reports_failure(self):
        searcher = MovieSearcher.__new__(MovieSearcher)

        with patch.object(searcher, 'markFailedAndResearch', return_value=False):
            result = searcher.markFailedView(media_id='movie-1')

        assert result == {'success': False}


# --- Release.failedView(): per-release "Mark failed" ------------------------

class TestReleaseFailedView:

    def test_calls_update_status_with_failed(self):
        plugin = Release.__new__(Release)

        with patch.object(plugin, 'updateStatus', return_value=True) as mocked:
            result = plugin.failedView(id='release-1')

        mocked.assert_called_once_with('release-1', 'failed')
        assert result == {'success': True}

    def test_reports_failure_when_update_status_fails(self):
        """Covers the CAS/conflict path: Release.updateStatus already
        swallows ConflictError internally and returns False rather than
        raising, so failedView must surface that as {'success': False}
        instead of crashing or reporting a false success."""
        plugin = Release.__new__(Release)

        with patch.object(plugin, 'updateStatus', return_value=False):
            result = plugin.failedView(id='release-1')

        assert result == {'success': False}

    def test_missing_id_reports_failure_without_calling_update_status(self):
        plugin = Release.__new__(Release)

        with patch.object(plugin, 'updateStatus') as mocked:
            result = plugin.failedView()

        mocked.assert_not_called()
        assert result == {'success': False}


# --- Reachability: routes must be registered via addApiView so /api/<route>
# doesn't 404 for the frontend PR that wires up the buttons. -----------------

class TestApiViewsRegistered:

    def test_movie_searcher_mark_failed_route_registered(self):
        source = SEARCHER_SOURCE.read_text()
        assert "addApiView('movie.searcher.mark_failed'" in source

    def test_release_failed_route_registered(self):
        source = RELEASE_SOURCE.read_text()
        assert "addApiView('release.failed'" in source
