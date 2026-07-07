"""Tests for workflow Phase 4a (specs/DOWNLOADED-REVIEW-WORKFLOW.md): a
notification fired exactly once when a movie TRANSITIONS into the
'downloaded' manual-review gate.

Mirrors the `movie.snatched` notification path
(`couchpotato/core/plugins/release/main.py:387`
`fireEvent('%s.snatched' % data['type'], message = snatch_message, data =
media)`) rather than the dead `renamer.after` chain
(specs/RENAMER-EVENT-CHAIN.md).

Fire site: `MediaPlugin.restatus()`
(couchpotato/core/media/_base/media/main.py), inside the guarded
`db.update(m)` block, conditioned on `m['status'] == 'downloaded' and
previous_status != 'downloaded'` -- so it fires exactly once, only on a
genuine transition into 'downloaded', and only when the status change was
actually persisted.

Harness mirrors tests/unit/test_downloaded_review_workflow_phase2.py: real
`restatus()` driven through a FakeDB + a fake fireEvent that records every
event fired (rather than raising on the ones this phase cares about).
"""
from unittest.mock import patch

from couchpotato.core.media._base.media.main import MediaPlugin
from couchpotato.core.notifications.base import Notification
from couchpotato.core.notifications.core.main import CoreNotifier


def _run_restatus(media_doc, profile_doc, releases):
    plugin = MediaPlugin.__new__(MediaPlugin)
    updated = []
    fired = []

    class FakeDB:
        def get(self, index, key, **kwargs):
            if index == 'id' and key == media_doc['_id']:
                return dict(media_doc)
            if profile_doc and index == 'id' and key == profile_doc['_id']:
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
        # Record anything else (including 'movie.downloaded') instead of
        # raising, so we can assert on exactly what fired.
        fired.append((event, args, kwargs))
        return None

    with (
        patch('couchpotato.core.media._base.media.main.get_db', return_value=FakeDB()),
        patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=fake_fire_event),
    ):
        result = plugin.restatus(media_doc['_id'], tag_recent=False)

    return result, updated, fired


def _downloaded_events(fired):
    return [f for f in fired if f[0] == 'movie.downloaded']


class TestNotifyOnEnteringDownloadedGate:

    def test_manual_confirmation_completion_fires_movie_downloaded_once(self):
        """A manual_confirmation profile completing a download: restatus
        transitions active -> downloaded AND fires 'movie.downloaded' exactly
        once, with a message containing the title and data == the (updated)
        media doc."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1', 'title': 'Predestination'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated, fired = _run_restatus(movie, profile, releases)

        assert result == 'downloaded'
        assert len(updated) == 1
        assert updated[0]['status'] == 'downloaded'

        downloaded_events = _downloaded_events(fired)
        assert len(downloaded_events) == 1

        event, args, kwargs = downloaded_events[0]
        assert 'Predestination' in kwargs['message']
        assert kwargs['data'] == updated[0]

    def test_idempotent_second_restatus_on_already_downloaded_movie_does_not_refire(self):
        """Calling restatus again on a movie that's already 'downloaded'
        (previous_status == 'downloaded') must NOT re-fire 'movie.downloaded'
        -- the Phase-1 preservation path keeps it 'downloaded' with no
        genuine transition, and no db.update happens either."""
        movie = {'_id': 'movie-1', 'status': 'downloaded', 'profile_id': 'profile-1', 'title': 'Predestination'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated, fired = _run_restatus(movie, profile, releases)

        assert result == 'downloaded'
        assert updated == []
        assert _downloaded_events(fired) == []

    def test_auto_profile_routes_to_done_and_does_not_fire(self):
        """A profile without manual_confirmation completes to 'done', not
        'downloaded' -- must never fire 'movie.downloaded'."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1', 'title': 'Predestination'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': False}
        releases = [{'status': 'done', 'quality': '1080p', 'last_edit': 0, 'is_3d': False}]

        result, updated, fired = _run_restatus(movie, profile, releases)

        assert result == 'done'
        assert len(updated) == 1
        assert updated[0]['status'] == 'done'
        assert _downloaded_events(fired) == []

    def test_no_transition_does_not_fire(self):
        """An active movie with no finishing release stays 'active'
        (no status change, no db.update) -- must not fire 'movie.downloaded'."""
        movie = {'_id': 'movie-1', 'status': 'active', 'profile_id': 'profile-1', 'title': 'Predestination'}
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}
        releases = []  # no done releases -> stays 'active'

        result, updated, fired = _run_restatus(movie, profile, releases)

        assert result == 'active'
        assert updated == []
        assert _downloaded_events(fired) == []


class TestMovieDownloadedRegisteredWithNotificationListeners:
    """Registration lock: 'movie.downloaded' must be in both notification
    listen_to lists so configured providers AND the core (DB-persisted)
    notifier pick it up -- mirroring how 'movie.snatched' is registered."""

    def test_registered_in_base_notification_listen_to(self):
        assert 'movie.downloaded' in Notification.listen_to

    def test_registered_in_core_notifier_listen_to(self):
        assert 'movie.downloaded' in CoreNotifier.listen_to
