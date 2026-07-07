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

    def _run(self, media_doc, releases, update_with_retry_result='write', media_get_returns_none=False):
        """Faithful harness for the movie-status CAS reset.

        `FakeDB.update_with_retry` actually invokes the mutator on the stored
        movie doc and *persists* the result (matching the real
        SQLiteAdapter.update_with_retry contract: returns the updated doc on a
        write, or None if the mutator returns False and no write happens).
        This is deliberate: an earlier version discarded the mutated doc and
        the production code re-read a hardcoded `media.get` fixture, which
        meant gutting the reset mutator to a permanent no-op still passed --
        a tautology. Persisting here lets a test assert the movie actually
        became 'active', and lets a reverted guard/reset be *caught* (see the
        revert-proof notes on each test).

        Returns the FakeDB instance too so tests can inspect the persisted
        movie doc (`fake_db.stored`).
        """
        searcher = MovieSearcher.__new__(MovieSearcher)

        release_status_calls = []
        single_search_calls = []

        class FakeDB:
            def __init__(self):
                self.stored = dict(media_doc)

            def update_with_retry(self, mutator, doc_id, retries=3):
                assert doc_id == media_doc['_id']
                doc = dict(self.stored)
                if mutator(doc) is False:
                    # No write -- movie left exactly as stored.
                    return None
                if update_with_retry_result == 'conflict':
                    # Mutator wanted to write, but the CAS lost every retry;
                    # nothing is persisted.
                    raise ConflictError(doc_id)
                self.stored = doc
                return doc

        fake_db = FakeDB()

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                assert args[0] == media_doc['_id']
                return [dict(r) for r in releases]
            if event == 'release.update_status':
                release_status_calls.append((args[0], kwargs.get('status')))
                return True
            if event == 'media.get':
                if media_get_returns_none:
                    return None
                enriched = dict(fake_db.stored)
                enriched['releases'] = [dict(r) for r in releases]
                return enriched
            if event == 'movie.searcher.single':
                single_search_calls.append((args[0], kwargs.get('manual')))
                return None
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.media.movie.searcher.get_db', return_value=fake_db),
            patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event),
        ):
            result = searcher.markFailedAndResearch(media_doc['_id'])

        return result, release_status_calls, single_search_calls, fake_db

    def test_landed_release_marked_failed_not_ignored(self):
        """BLOCKING distinction from the pre-existing try_next/tryNextRelease
        view, which marks the old release 'ignored'. The spec calls for the
        bad copy to be marked 'failed' here instead."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]

        result, release_status_calls, _, _ = self._run(movie, releases)

        assert result is True
        assert release_status_calls == [('release-1', 'failed')]

    def test_movie_persisted_active_and_research_triggered_exactly_once(self):
        """Locks the reset itself (BLOCKING 3): the persisted movie doc must
        actually become 'active', and the enriched doc handed to the
        re-search must reflect that. Revert-proof: gut `_reset_if_downloaded`
        to a permanent no-op (or drop the `media['status'] = 'active'` line)
        and `fake_db.stored['status']` stays 'downloaded' -> this fails."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]

        result, _, single_search_calls, fake_db = self._run(movie, releases)

        assert result is True
        assert fake_db.stored['status'] == 'active', "movie must be persisted active"
        assert len(single_search_calls) == 1
        fired_media, fired_manual = single_search_calls[0]
        assert fired_media['status'] == 'active', "re-search must see the reset movie"
        assert fired_manual is True

    def test_snatched_seeding_and_done_landed_releases_are_all_marked_failed(self):
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [
            {'_id': 'release-snatched', 'status': 'snatched'},
            {'_id': 'release-seeding', 'status': 'seeding'},
            {'_id': 'release-done', 'status': 'done'},
        ]

        _, release_status_calls, _, _ = self._run(movie, releases)

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

        _, release_status_calls, _, _ = self._run(movie, releases)

        assert release_status_calls == []

    def test_zero_releases_still_resets_and_researches(self):
        """Parity case the reviewer flagged: a 'downloaded' movie with no
        release rows must still be reset to 'active' and re-searched (the
        release-failing loop is simply a no-op). Revert-proof: if the reset
        were gated behind 'has a landed release', this movie would never
        flip to active."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}

        result, release_status_calls, single_search_calls, fake_db = self._run(movie, releases=[])

        assert result is True
        assert fake_db.stored['status'] == 'active'
        assert release_status_calls == []
        assert len(single_search_calls) == 1

    def test_done_movie_is_a_noop_and_never_reopens(self):
        """BLOCKING 2 lock: the action is spec-scoped to a 'downloaded'
        (review-gated) movie. A stale-tab / double-submit / direct-API
        mark_failed on an already-confirmed 'done' movie must be a hard
        no-op -- its confirmed 'done' release must NOT be flipped to
        'failed', its status must NOT be rewritten, and NO re-search may
        fire (its profile_id is still set, so single()'s gate wouldn't block
        it). Revert-proof: change the guard to accept any status (e.g.
        `if media.get('status') == 'active'`) and this movie's release gets
        failed + status flips to active + search fires -> every assertion
        here breaks."""
        movie = {'_id': 'movie-1', 'status': 'done', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'done'}]

        result, release_status_calls, single_search_calls, fake_db = self._run(movie, releases)

        assert result is False
        assert release_status_calls == [], "a confirmed release must not be failed"
        assert single_search_calls == [], "a confirmed movie must not be re-searched"
        assert fake_db.stored['status'] == 'done', "status must be untouched"

    def test_active_movie_is_a_noop(self):
        """Guard also covers an already-'active' movie (nothing to reopen):
        no release change, no search, no write. Revert-proof alongside the
        'done' case -- with the old `== 'active' -> no-op, else flip` mutator
        this specific movie happened to be a no-op too, so on its own it
        wouldn't catch a broken guard; it's the 'done' test that does. Kept
        for completeness of the guard's status matrix."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'snatched'}]

        result, release_status_calls, single_search_calls, fake_db = self._run(movie, releases)

        assert result is False
        assert release_status_calls == []
        assert single_search_calls == []
        assert fake_db.stored['status'] == 'active'

    def test_reset_failure_prevents_any_release_from_being_failed(self):
        """BLOCKING 1 lock (ordering / no half-done state): when the movie
        CAS reset can't land (persistent ConflictError), NOTHING downstream
        may run -- no release may be marked 'failed' and no re-search may
        fire. Otherwise the movie is stuck 'downloaded' with its only landed
        release already 'failed' and no auto-recovery. Revert-proof: move the
        release-failing loop back *before* the reset and `release_status_calls`
        becomes non-empty here -> this fails."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]

        result, release_status_calls, single_search_calls, fake_db = self._run(
            movie, releases, update_with_retry_result='conflict',
        )

        assert result is False
        assert release_status_calls == [], "no release may be failed if the reset didn't land"
        assert single_search_calls == []
        assert fake_db.stored['status'] == 'downloaded', "movie must stay in the review gate"

    def test_media_not_found_after_reset_returns_false_without_searching(self):
        """If the enriched re-fetch comes back empty (movie deleted between
        the reset and the re-fetch), report failure and don't fire a search
        against a missing movie. The reset already landed and the release was
        already failed by this point -- that's an acceptable degraded state
        (movie is 'active', the next cron picks it up), NOT the half-done
        state BLOCKING 1 guards against (there the movie was left
        'downloaded')."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'_id': 'release-1', 'status': 'downloaded'}]

        result, _, single_search_calls, _ = self._run(
            movie, releases, media_get_returns_none=True,
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
