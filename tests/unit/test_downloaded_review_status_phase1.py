"""Tests for workflow Phase 1 (specs/DOWNLOADED-REVIEW-WORKFLOW.md): introduce
the movie-level 'downloaded' ("Downloaded / review") status and make the
searcher treat it as a search-stop state, same as 'done'.

Phase 1 is additive only: nothing in this phase *sets* a movie to
'downloaded' (that is Phase 2's per-profile completion routing). These tests
lock in the gating/preservation behavior so Phase 2 can rely on it safely.
"""
import threading
from unittest.mock import patch

import pytest

from couchpotato.core.media._base.media.main import MediaPlugin
from couchpotato.core.media.movie.searcher import MovieSearcher


# --- searchAll(): batch search must not select 'downloaded' movies --------

class TestSearchAllExcludesDownloaded:

    def _make_searcher(self):
        searcher = MovieSearcher.__new__(MovieSearcher)
        searcher._progress_lock = threading.Lock()
        searcher.in_progress = False
        return searcher

    def test_batch_search_only_requests_active_status(self):
        """searchAll must query media.with_status('active', ...) -- a
        'downloaded' movie is never even fetched for the batch loop."""
        searcher = self._make_searcher()
        with_status_calls = []

        def fake_fire_event(event, *args, **kwargs):
            if event == 'media.with_status':
                with_status_calls.append((args, kwargs))
                return []
            if event == 'notify.frontend':
                return None
            if event == 'searcher.protocols':
                return ['torrent']
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event):
            searcher.searchAll(manual=False)

        assert len(with_status_calls) == 1
        args, kwargs = with_status_calls[0]
        assert args[0] == 'active', "batch search must only select 'active' movies"
        assert kwargs.get('types') == 'movie'

    def test_downloaded_movie_is_never_passed_to_single(self):
        """Given a mixed fixture of active/done/downloaded movies, only the
        active one reaches self.single() -- 'downloaded' is excluded exactly
        like 'done' already is, because media.with_status('active', ...)
        filters it out upstream."""
        searcher = self._make_searcher()

        fixture = {
            'movie-active': {'_id': 'movie-active', 'status': 'active'},
            'movie-done': {'_id': 'movie-done', 'status': 'done'},
            'movie-downloaded': {'_id': 'movie-downloaded', 'status': 'downloaded'},
        }

        def fake_fire_event(event, *args, **kwargs):
            if event == 'media.with_status':
                status_arg = args[0]
                statuses = status_arg if isinstance(status_arg, (list, tuple)) else [status_arg]
                return [{'_id': mid} for mid, doc in fixture.items() if doc['status'] in statuses]
            if event == 'notify.frontend':
                return None
            if event == 'searcher.protocols':
                return ['torrent']
            if event == 'media.get':
                return fixture.get(args[0])
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        singled_ids = []
        with (
            patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event),
            patch.object(searcher, 'single', side_effect=lambda media, *a, **k: singled_ids.append(media['_id'])),
            patch.object(searcher, 'shuttingDown', return_value=False),
        ):
            searcher.searchAll(manual=False)

        assert singled_ids == ['movie-active']
        assert 'movie-downloaded' not in singled_ids
        assert 'movie-done' not in singled_ids


# --- single(): per-movie gating on 'downloaded' ----------------------------

class TestSingleGatesOnDownloadedStatus:

    def _make_searcher(self):
        return MovieSearcher.__new__(MovieSearcher)

    def test_skips_downloaded_movie_when_not_manual(self):
        """A 'downloaded' movie must be skipped (no search, no upgrade) just
        like a 'done' movie -- confirmed by never reaching the
        'movie.searcher.started' notification that only fires past the gate."""
        searcher = self._make_searcher()
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1', 'title': 'Test Movie'}

        events = []

        def fake_fire_event(event, *args, **kwargs):
            events.append((event, kwargs))
            if event == 'media.restatus':
                return 'downloaded'
            return None

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event):
            result = searcher.single(movie, search_protocols=['torrent'], manual=False)

        assert result is None
        event_names = [e for e, _ in events]
        assert event_names == ['media.restatus'], (
            "skip path must only call media.restatus and return immediately"
        )
        assert not any(
            e == 'notify.frontend' and kw.get('type') == 'movie.searcher.started'
            for e, kw in events
        ), "a downloaded movie must never start a search"

    # NOTE: this test documents the manual=True override precedent only. It does
    # NOT by itself prove 'downloaded' is in the gating tuple, since
    # `status in (...) and not manual` short-circuits to False whenever
    # manual=True regardless of the tuple's contents. That gating is proven by
    # the sibling test `test_skips_downloaded_movie_when_not_manual` above,
    # which would fail if 'downloaded' were removed from the tuple.
    def test_manual_true_overrides_the_downloaded_gate(self):
        """A manual/forced search (manual=True) must still be able to act on
        a 'downloaded' movie -- mirrors the existing 'done' + manual=True
        precedent (media_id gating uses `and not manual`)."""
        searcher = self._make_searcher()
        movie = {
            '_id': 'movie-1',
            'status': 'downloaded',
            'profile_id': 'profile-1',
            'title': 'Test Movie',
        }

        events = []

        def fake_fire_event(event, *args, **kwargs):
            events.append((event, kwargs))
            if event == 'media.restatus':
                return 'downloaded'
            if event == 'quality.pre_releases':
                return []
            if event == 'movie.update_release_dates':
                return {}
            if event == 'notify.frontend':
                return None
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        fake_profile = {'_id': 'profile-1', 'qualities': [], 'finish': [], 'wait_for': []}

        class FakeDB:
            def get(self, index, key, **kwargs):
                if index == 'id' and key == 'profile-1':
                    return dict(fake_profile)
                raise AssertionError('Unexpected db.get call: %r %r' % (index, key))

        with (
            patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event),
            patch('couchpotato.core.media.movie.searcher.get_db', return_value=FakeDB()),
            patch.object(MovieSearcher, 'conf', return_value=True),
            patch.object(MovieSearcher, 'shuttingDown', return_value=False),
        ):
            result = searcher.single(movie, search_protocols=['torrent'], manual=True)

        assert result is False, "empty profile qualities means nothing to grab, but the call must proceed"
        event_names = [e for e, _ in events]
        assert 'quality.pre_releases' in event_names, (
            "manual=True must bypass the downloaded gate and reach the search body"
        )
        assert any(
            e == 'notify.frontend' and kw.get('type') == 'movie.searcher.started'
            for e, kw in events
        ), "manual search on a downloaded movie must still start"


# --- media.restatus(): must preserve an existing 'downloaded' status ------

class TestRestatusPreservesDownloaded:

    def _run_restatus(self, media_doc, releases=None):
        plugin = MediaPlugin.__new__(MediaPlugin)
        updated = []

        class FakeDB:
            def get(self, index, key, **kwargs):
                if index == 'id' and key == media_doc['_id']:
                    return dict(media_doc)
                raise AssertionError('Unexpected db.get call: %r %r' % (index, key))

            def update(self, doc):
                updated.append(dict(doc))
                return doc

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                return releases or []
            if event == 'quality.isfinish':
                return False
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.media._base.media.main.get_db', return_value=FakeDB()),
            patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=fake_fire_event),
        ):
            result = plugin.restatus(media_doc['_id'], tag_recent=False)

        return result, updated

    def test_downloaded_movie_stays_downloaded_with_no_releases(self):
        """A movie already awaiting review, with no 'done' releases (the
        upgrade-quality release check hasn't found anything better), must
        stay 'downloaded' -- restatus must not fall through to the
        active/done branch and demote it."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}

        result, updated = self._run_restatus(movie)

        assert result == 'downloaded'
        # Status didn't change, so restatus should not have written to the DB.
        assert updated == []

    def test_downloaded_movie_stays_downloaded_even_with_a_done_release(self):
        """Even if the owning release happens to carry a 'done' status (e.g.
        a stale record), a movie already in the review gate must not be
        auto-promoted to 'done' by restatus in this phase -- Phase 2 owns
        that transition via the per-profile toggle."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated = self._run_restatus(movie, releases=releases)

        assert result == 'downloaded'
        assert updated == []

    def test_downloaded_movie_without_profile_still_preserved(self):
        """Guard applies before the 'no profile -> done' branch too."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': None}

        result, updated = self._run_restatus(movie)

        assert result == 'downloaded'
        assert updated == []

    def test_active_movie_without_profile_still_becomes_done(self):
        """Regression guard: the new 'downloaded' branch must not change
        existing behavior for movies that were never in the review gate."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': None}

        result, updated = self._run_restatus(movie)

        assert result == 'done'
        assert len(updated) == 1
        assert updated[0]['status'] == 'done'

    def test_active_movie_with_done_release_still_promotes_to_done(self):
        """Regression guard: unrelated existing behavior (active -> done via
        a finished release) is untouched by the new preservation branch."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1'}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        plugin = MediaPlugin.__new__(MediaPlugin)
        updated = []

        class FakeDB:
            def get(self, index, key, **kwargs):
                if index == 'id' and key == movie['_id']:
                    return dict(movie)
                if index == 'id' and key == 'profile-1':
                    return {'_id': 'profile-1', 'qualities': ['1080p']}
                raise AssertionError('Unexpected db.get call: %r %r' % (index, key))

            def update(self, doc):
                updated.append(dict(doc))
                return doc

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                return releases
            if event == 'quality.isfinish':
                return True
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.media._base.media.main.get_db', return_value=FakeDB()),
            patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=fake_fire_event),
        ):
            result = plugin.restatus(movie['_id'], tag_recent=False)

        assert result == 'done'
        assert len(updated) == 1
