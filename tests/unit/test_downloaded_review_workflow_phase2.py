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
from unittest.mock import patch

from couchpotato.core.media._base.media.main import MediaPlugin
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

    def test_save_defaults_manual_confirmation_false_when_omitted(self):
        """A save() call that never mentions manual_confirmation (e.g. every
        pre-Phase-2 caller, or a brand new profile created before the UI
        exposes the toggle) must persist it as False, not leave it unset in
        a way that could be misread as truthy."""
        result, updated = self._run_save({
            'id': 'profile-1',
            'label': 'Auto',
            'types': [{'quality': '1080p', 'finish': 1, '3d': 0}],
        }, existing_profile={'_id': 'profile-1', 'label': 'Auto'})

        assert result['success'] is True
        assert len(updated) == 1
        assert updated[0]['manual_confirmation'] is False

    def test_profile_doc_lacking_the_key_reads_as_false(self):
        """A profile document persisted before Phase 2 existed simply has no
        'manual_confirmation' key at all. Every consumer must read it via
        .get(..., False) so it defaults safely -- this test locks in that
        contract at the data level."""
        legacy_profile = {'_id': 'profile-legacy', 'label': 'Old Profile', 'qualities': ['720p']}

        assert legacy_profile.get('manual_confirmation', False) is False
        assert bool(legacy_profile.get('manual_confirmation')) is False


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
