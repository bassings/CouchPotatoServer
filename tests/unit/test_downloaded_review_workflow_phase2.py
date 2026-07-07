"""Tests for workflow Phase 2 (specs/DOWNLOADED-REVIEW-WORKFLOW.md): a
per-profile `manual_confirmation` toggle that routes a completing download to
the movie-level 'downloaded' review gate (added in Phase 1) instead of 'done'.

Decision point: `MediaPlugin.restatus()`
(couchpotato/core/media/_base/media/main.py), specifically the branch that
already promotes a movie from 'active' to 'done' once one of its releases
satisfies `quality.isfinish` for the owning profile. When the owning
profile's `manual_confirmation` is truthy AND this is a genuinely new
completion (the movie wasn't already 'done'), that branch now sets
'downloaded' instead of 'done'. The Phase-1 top-level preservation check
(previous_status == 'downloaded' -> stays 'downloaded') is untouched and
still runs *before* this branch, so an already-'downloaded' movie never
reaches this logic at all.
"""
import threading
from unittest.mock import patch

from couchpotato.core.media._base.media.main import MediaPlugin
from couchpotato.core.media.movie.searcher import MovieSearcher
from couchpotato.core.plugins.manage import Manage
from couchpotato.core.plugins.profile.main import ProfilePlugin
from couchpotato.core.plugins.release.main import Release


# --- media.restatus(): completion routing driven by profile.manual_confirmation

class TestRestatusManualConfirmationRouting:

    def _run_restatus(self, media_doc, profile_doc, releases):
        plugin = MediaPlugin.__new__(MediaPlugin)
        updated = []

        class FakeDB:
            def get(self, index, key, **kwargs):
                if index == 'id' and key == media_doc['_id']:
                    return dict(media_doc)
                if index == 'id' and key == profile_doc['_id']:
                    return dict(profile_doc)
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
            result = plugin.restatus(media_doc['_id'], tag_recent=False)

        return result, updated

    def test_auto_profile_missing_flag_completes_to_done_unchanged(self):
        """Regression lock: a profile that doesn't carry 'manual_confirmation'
        at all (the pre-Phase-2 shape, or a freshly created one that never
        touched the toggle) must behave exactly as today: a finishing
        release drives the movie straight to 'done'."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p']}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated = self._run_restatus(movie, profile, releases)

        assert result == 'done'
        assert len(updated) == 1
        assert updated[0]['status'] == 'done'

    def test_auto_profile_explicit_false_completes_to_done_unchanged(self):
        """Same regression lock, but with the flag explicitly persisted as
        False (the normal post-Phase-2 shape for an auto profile)."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': False}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated = self._run_restatus(movie, profile, releases)

        assert result == 'done'
        assert len(updated) == 1
        assert updated[0]['status'] == 'done'

    def test_manual_profile_routes_completion_to_downloaded_not_done(self):
        """A profile with manual_confirmation ON routes the SAME completion
        (same release, same quality.isfinish outcome) to 'downloaded'
        instead of 'done'."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated = self._run_restatus(movie, profile, releases)

        assert result == 'downloaded'
        assert len(updated) == 1
        assert updated[0]['status'] == 'downloaded'

    def test_manual_profile_does_not_demote_an_already_done_movie(self):
        """A movie that is already 'done' (e.g. confirmed earlier, or from
        before the profile ever had manual_confirmation set) must not be
        pulled back down to 'downloaded' by a later restatus recompute, even
        though its profile now has manual_confirmation ON. Only a genuinely
        new completion (previous_status != 'done') gets gated."""
        movie = {'_id': 'movie-1', 'status': 'done', 'profile_id': 'profile-1'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated = self._run_restatus(movie, profile, releases)

        assert result == 'done'
        # Status didn't change ('done' -> 'done'), so no DB write.
        assert updated == []

    def test_downloaded_movie_stays_downloaded_regardless_of_manual_confirmation(self):
        """Defensive test: the Phase-1 top-level preservation branch
        (previous_status == 'downloaded' -> stays 'downloaded') must still
        run *before* the manual_confirmation branch and win outright --
        confirming the routing decision was correctly placed only inside the
        active-with-a-finishing-release branch, not somewhere that could
        re-evaluate an already-gated movie."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated = self._run_restatus(movie, profile, releases)

        assert result == 'downloaded'
        assert updated == []


# --- profile field persistence -----------------------------------------

class TestProfileManualConfirmationPersistence:

    def _run_save(self, kwargs, existing_profile=None):
        plugin = ProfilePlugin.__new__(ProfilePlugin)
        updated = []

        class FakeDB:
            def get(self, index, key, **kw):
                if existing_profile and index == 'id' and key == existing_profile['_id']:
                    return dict(existing_profile)
                raise Exception('not found')

            def insert(self, data):
                data = dict(data)
                data['_id'] = 'new-profile'
                return data

            def update(self, doc):
                updated.append(dict(doc))
                return doc

        with patch('couchpotato.core.plugins.profile.main.get_db', return_value=FakeDB()):
            result = plugin.save(**kwargs)

        return result, updated

    def test_save_persists_manual_confirmation_true(self):
        result, updated = self._run_save({
            'id': 'profile-1',
            'label': 'Manual Review',
            'types': [{'quality': '1080p', 'finish': 1, '3d': 0}],
            'manual_confirmation': 1,
        }, existing_profile={'_id': 'profile-1', 'label': 'Manual Review'})

        assert result['success'] is True
        assert len(updated) == 1
        assert updated[0]['manual_confirmation'] is True

    def test_save_defaults_manual_confirmation_false_when_omitted_on_new_profile(self):
        """A save() call that never mentions manual_confirmation AND has no
        existing doc to fall back to (a brand new profile, or a caller whose
        id doesn't resolve) must persist it as False, not leave it unset in
        a way that could be misread as truthy."""
        result, updated = self._run_save({
            'id': 'profile-new',
            'label': 'Auto',
            'types': [{'quality': '1080p', 'finish': 1, '3d': 0}],
        }, existing_profile=None)

        assert result['success'] is True
        assert len(updated) == 1
        assert updated[0]['manual_confirmation'] is False

    def test_save_omitting_key_on_existing_true_profile_preserves_true(self):
        """BLOCKING bug (workflow phase 2 review): the live profile editor
        never sends manual_confirmation in its save payload -- it only sends
        label/order/types/etc for a routine rename or quality edit. Before
        the fix, save() unconditionally recomputed manual_confirmation from
        kwargs with a bare `0` default, silently flipping an existing True
        profile back to False on every such edit. The fix mirrors the
        sibling 'order' field, which already falls back to the persisted
        value (`p.get('order', 999)`) when the key is omitted."""
        result, updated = self._run_save({
            'id': 'profile-1',
            'label': 'Manual Review (renamed)',
            'types': [{'quality': '1080p', 'finish': 1, '3d': 0}],
        }, existing_profile={'_id': 'profile-1', 'label': 'Manual Review', 'manual_confirmation': True})

        assert result['success'] is True
        assert len(updated) == 1
        assert updated[0]['manual_confirmation'] is True

    def test_save_legacy_profile_without_key_omitting_payload_key_persists_as_false(self):
        """Replaces a prior tautological test that only asserted dict.get()
        on a local literal. A profile doc persisted before Phase 2 existed
        carries no 'manual_confirmation' key at all. Saving it (e.g. a
        rename) via a payload that also omits the key must exercise the real
        save() fallback and persist an explicit False, not leave the key
        unset or misread as truthy."""
        result, updated = self._run_save({
            'id': 'profile-legacy',
            'label': 'Old Profile (renamed)',
            'types': [{'quality': '720p', 'finish': 1, '3d': 0}],
        }, existing_profile={'_id': 'profile-legacy', 'label': 'Old Profile', 'qualities': ['720p']})

        assert result['success'] is True
        assert len(updated) == 1
        assert updated[0]['manual_confirmation'] is False

    def test_save_explicit_true_on_existing_false_profile_turns_it_on(self):
        """Sanity check alongside the fallback fix: explicitly sending the
        key must still win over the persisted value (the fallback only
        applies when the key is omitted)."""
        result, updated = self._run_save({
            'id': 'profile-1',
            'label': 'Now Manual',
            'types': [{'quality': '1080p', 'finish': 1, '3d': 0}],
            'manual_confirmation': 1,
        }, existing_profile={'_id': 'profile-1', 'label': 'Now Manual', 'manual_confirmation': False})

        assert result['success'] is True
        assert len(updated) == 1
        assert updated[0]['manual_confirmation'] is True


# --- Step D: hardcoded movie-status lists must include 'downloaded' -----

class TestStaleReleaseCleanupIncludesDownloaded:
    """couchpotato/core/plugins/release/main.py Release.cleanDone() (the
    weekly stale-release cleanup) used to hardcode media.with_status(['done',
    'active']). Now that manual-review profiles produce 'downloaded' movies,
    omitting that status would silently exempt review-gated movies from
    having their stale/duplicate releases cleaned up."""

    def test_weekly_cleanup_queries_downloaded_alongside_done_and_active(self):
        plugin = Release.__new__(Release)

        class FakeDB:
            def all(self, table, with_doc=False):
                return []

        calls = []

        def fake_fire_event(event, *args, **kwargs):
            if event == 'media.with_status':
                calls.append(args[0])
                return []
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.plugins.release.main.get_db', return_value=FakeDB()),
            patch('couchpotato.core.plugins.release.main.fireEvent', side_effect=fake_fire_event),
        ):
            plugin.cleanDone()

        assert calls == [['done', 'active', 'downloaded']]


class TestProfileOrphanRepairIncludesDownloaded:
    """ProfilePlugin.forceDefaults() reassigns movies with a dangling
    profile_id to the default profile. It used to only look at 'active'
    movies. A 'downloaded' (review-gated) movie still needs a working
    profile_id (restatus() reads it every call, and the future "mark failed
    & re-search" action needs it too), so it must be covered by the same
    orphan repair or a deleted-profile reference would strand it."""

    def test_orphan_profile_repair_queries_downloaded_alongside_active(self):
        plugin = ProfilePlugin.__new__(ProfilePlugin)

        class FakeDB:
            def count(self, func, table):
                return 1  # pretend profiles already exist, skip self.fill()

            def all(self, table, with_doc=False):
                return [{'doc': {'_id': 'profile-default', 'qualities': ['1080p']}}]

        calls = []

        def fake_fire_event(event, *args, **kwargs):
            if event == 'media.with_status':
                calls.append(args[0])
                return []
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.plugins.profile.main.get_db', return_value=FakeDB()),
            patch('couchpotato.core.plugins.profile.main.fireEvent', side_effect=fake_fire_event),
        ):
            plugin.forceDefaults()

        assert calls == [['active', 'downloaded']]


# --- BLOCKING 1: a review-gated ('downloaded') movie must be exempt from
# manage/cleanup deletion, even though its release is 'done'. -------------
#
# `Manage.updateLibrary()`'s cleanup scan queries
# `fireEvent('media.list', status='done', release_status='done', status_or=True, ...)`.
# `status_or=True` makes MediaPlugin.list() treat this as an OR union: a movie
# whose *movie* status is 'done' OR whose *release* status is 'done'. A
# 'downloaded' movie (workflow phase 2 review gate) always has a 'done'
# release while it awaits review, so it landed in done_movies and could be
# silently deleted (delete_from='all') by a routine full library scan
# (the 'cleanup' config defaults on). The sibling manage-tab delete path
# (MediaPlugin.delete(delete_from='manage')) has the same OR exposure via
# `release.status == 'done' or media.status == 'done'`.

class TestManageCleanupExemptsDownloadedMovies:

    def _run_update_library(self, done_movies):
        manage = Manage.__new__(Manage)
        manage._progress_lock = threading.Lock()
        manage.in_progress = False

        delete_calls = []

        def fake_fire_event(event, *args, **kwargs):
            if event == 'media.list':
                return len(done_movies), done_movies
            if event == 'media.delete':
                delete_calls.append(dict(kwargs))
                return True
            if event == 'notify.frontend':
                return None
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        class FakeDB:
            def reindex(self):
                pass

        with (
            patch.object(Manage, 'conf', return_value=True),
            patch.object(Manage, 'isDisabled', return_value=False),
            patch.object(Manage, 'directories', return_value=[]),
            patch.object(Manage, 'shuttingDown', return_value=False),
            patch('couchpotato.core.plugins.manage.fireEvent', side_effect=fake_fire_event),
            patch('couchpotato.core.plugins.manage.get_db', return_value=FakeDB()),
            patch('couchpotato.core.plugins.manage.Env.prop',
                  side_effect=lambda identifier, value=None, default=None: default if value is None else None),
        ):
            manage.updateLibrary(full=True)

        return delete_calls

    def test_downloaded_movie_with_done_release_is_not_deleted_by_cleanup(self):
        """The BLOCKING bug scenario: a review-gated movie (movie status
        'downloaded') whose release is 'done' lands in done_movies via the
        status_or union, but must never be swept up by the cleanup scan's
        delete_from='all' path."""
        downloaded_movie = {
            '_id': 'movie-downloaded',
            'status': 'downloaded',
            'identifiers': {'imdb': 'tt1'},
            'releases': [],
        }

        delete_calls = self._run_update_library([downloaded_movie])

        assert delete_calls == []

    def test_genuinely_done_movie_missing_from_disk_is_still_cleaned_up(self):
        """Regression lock: the exemption must not change behavior for a
        movie that's actually 'done' -- if it wasn't found on this scan
        (not in added_identifiers), it's still deleted exactly as before."""
        done_movie = {
            '_id': 'movie-done',
            'status': 'done',
            'identifiers': {'imdb': 'tt2'},
            'releases': [],
        }

        delete_calls = self._run_update_library([done_movie])

        assert delete_calls == [{'media_id': 'movie-done', 'delete_from': 'all'}]


class TestManageDeleteExemptsDownloadedMovies:

    def _run_delete(self, media, releases):
        plugin = MediaPlugin.__new__(MediaPlugin)

        db_deletes = []
        db_updates = []

        class FakeDB:
            def get(self, index, key, **kwargs):
                if index == 'id' and key == media['_id']:
                    return dict(media)
                raise AssertionError('Unexpected db.get call: %r %r' % (index, key))

            def delete(self, doc):
                db_deletes.append(dict(doc))

            def update(self, doc):
                db_updates.append(dict(doc))
                return doc

        def fake_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                return [dict(r) for r in releases]
            if event == 'media.restatus':
                return media.get('status')
            if event in ('media.untag', 'notify.frontend'):
                return None
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.media._base.media.main.get_db', return_value=FakeDB()),
            patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=fake_fire_event),
        ):
            plugin.delete(media['_id'], delete_from='manage')

        return db_deletes, db_updates

    def test_downloaded_movie_release_survives_manage_delete(self):
        """The BLOCKING bug scenario for MediaPlugin.delete(): a
        review-gated movie's release is 'done' by design, so the manage
        path's `release.status == 'done' or media.status == 'done'` check
        used to delete it out from under an in-progress review. Must now
        survive untouched."""
        movie = {'_id': 'movie-1', 'status': 'downloaded'}
        releases = [{'_id': 'release-1', 'status': 'done'}]

        db_deletes, _ = self._run_delete(movie, releases)

        assert db_deletes == []

    def test_genuinely_done_movie_release_is_still_deleted_by_manage_delete(self):
        """Regression lock: unchanged behavior for a movie that's actually
        'done' -- its release is still deleted, and since every release
        ended up deleted the movie itself is deleted too."""
        movie = {'_id': 'movie-2', 'status': 'done'}
        releases = [{'_id': 'release-2', 'status': 'done'}]

        db_deletes, _ = self._run_delete(movie, releases)

        deleted_ids = [d.get('_id') for d in db_deletes]
        assert 'release-2' in deleted_ids
        assert 'movie-2' in deleted_ids


# --- End-to-end composition: manual-confirmation routing + searcher gate --

class TestManualConfirmationRoutingGatesSearcher:
    """Ties Phase 2 (restatus() routes a manual-confirmation completion to
    'downloaded') to Phase 1 (the searcher gate skips a 'downloaded' movie)
    instead of testing each in isolation."""

    def test_manual_confirmation_completion_is_then_skipped_by_searcher(self):
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        media_plugin = MediaPlugin.__new__(MediaPlugin)

        class FakeMediaDB:
            def get(self, index, key, **kwargs):
                if index == 'id' and key == movie['_id']:
                    return dict(movie)
                if index == 'id' and key == profile['_id']:
                    return dict(profile)
                raise AssertionError('Unexpected db.get call: %r %r' % (index, key))

            def update(self, doc):
                movie.update(doc)
                return doc

        def fake_restatus_fire_event(event, *args, **kwargs):
            if event == 'release.for_media':
                return releases
            if event == 'quality.isfinish':
                return True
            raise AssertionError('Unexpected fireEvent call: %r' % (event,))

        with (
            patch('couchpotato.core.media._base.media.main.get_db', return_value=FakeMediaDB()),
            patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=fake_restatus_fire_event),
        ):
            routed_status = media_plugin.restatus(movie['_id'], tag_recent=False)

        # Phase 2: the manual-confirmation profile routed the completion to
        # 'downloaded', not 'done'.
        assert routed_status == 'downloaded'
        assert movie['status'] == 'downloaded'

        # Phase 1: feed that same (now 'downloaded') movie into the
        # searcher's gate and confirm it's skipped outright.
        searcher = MovieSearcher.__new__(MovieSearcher)
        event_names = []

        def fake_searcher_fire_event(event, *args, **kwargs):
            event_names.append(event)
            if event == 'media.restatus':
                return movie['status']
            raise AssertionError('Unexpected fireEvent call past the downloaded gate: %r' % (event,))

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_searcher_fire_event):
            searcher.single(movie, search_protocols=['torrent'], manual=False)

        assert event_names == ['media.restatus'], (
            "a 'downloaded' movie must be skipped before any search-related "
            "event fires"
        )
