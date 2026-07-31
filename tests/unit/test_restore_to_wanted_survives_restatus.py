"""FEAT-008 AC5: a movie moved back to wanted must actually BE wanted.

`restoreToWanted` sets status='active' and preserves the release the movie
already holds (AC3). That preserved release counts as satisfying the profile in
TWO independent places, and both have to be addressed or "restore" is a no-op
with a friendly toast:

  1. `MediaPlugin.restatus` recomputes status from releases whose status is
     'done'. The held release finishes the movie again on the next sweep -- and
     with `manual_confirmation` (the FEAT-004 default) `previous_status` is now
     'active' rather than 'done', which routes it into the 'downloaded' review
     gate AND fires a `movie.downloaded` "awaiting review" notification for a
     movie the user never re-downloaded.

  2. `MovieSearcher.single`'s has_better_quality loop counts any release whose
     status is not in ('available', 'ignored', 'failed'). A held release at the
     profile's top rung makes it break on the FIRST quality, before contacting
     any provider.

Marking the held releases 'ignored' addresses both at once, using the mechanism
the codebase already has -- and mirrors `markFailedAndResearch`, which marks
the landed release 'failed' for exactly the same reason.

An earlier attempt stamped `restored_to_wanted_at` on the MEDIA doc and had
restatus discount older releases. It was unsound twice over: it fixed (1) but
not (2), so the movie sat in Wanted contacting zero providers forever; and
`release.add` rewrites `last_edit` on any library rescan, which silently
re-armed the original bug. This file covers (1); the searcher half is covered
by test_search_releases_list_only.py::
TestARestoredMovieIsPickedUpByTheAutomaticSearcher.
"""
from unittest.mock import patch

from couchpotato.core.media._base.media.main import MediaPlugin


def _run_restatus(media_doc, profile_doc, releases):
    plugin = MediaPlugin.__new__(MediaPlugin)
    updated = []
    fired = []

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
        fired.append(event)
        if event == 'release.for_media':
            return releases
        if event == 'quality.isfinish':
            return True          # the release WOULD finish the profile
        return None

    with (
        patch('couchpotato.core.media._base.media.main.get_db', return_value=FakeDB()),
        patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=fake_fire_event),
    ):
        result = plugin.restatus(media_doc['_id'], tag_recent=False)

    return result, updated, fired


def _restored_movie():
    """What restoreToWanted leaves behind: active, with a resolvable profile."""
    return {
        '_id': 'movie-1',
        'type': 'movie',
        'title': 'Some Movie',
        'status': 'active',
        'profile_id': 'profile-1',
    }


def _ignored_release():
    """The held release AFTER restoreToWanted marks it 'ignored'."""
    return [{'_id': 'held-1', 'status': 'ignored', 'quality': '1080p',
             'last_edit': 1000, 'is_3d': False}]


class TestARestoredMovieStaysWanted:

    def test_a_manual_confirmation_profile_does_not_send_it_to_the_review_gate(self):
        movie = _restored_movie()
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}

        result, updated, fired = _run_restatus(movie, profile, _ignored_release())

        assert result == 'active', (
            'the restored movie was pushed to %r by the first restatus, so it '
            'left Wanted immediately' % result
        )
        assert 'movie.downloaded' not in fired, (
            'fired a false "downloaded -- awaiting review" notification for a '
            'movie the user never re-downloaded'
        )
        assert not updated, 'a no-op restatus must not write'

    def test_an_auto_profile_does_not_flip_it_straight_back_to_done(self):
        movie = _restored_movie()
        profile = {'_id': 'profile-1', 'qualities': ['1080p']}

        result, _, _ = _run_restatus(movie, profile, _ignored_release())

        assert result == 'active', 'the restored movie went straight back to %r' % result


class TestTheGuardIsNarrow:
    """Ignoring the held release must not stop a genuinely NEW download from
    completing the movie, or restore would break upgrading permanently."""

    def test_a_newly_completed_release_still_completes_the_movie(self):
        movie = _restored_movie()
        profile = {'_id': 'profile-1', 'qualities': ['1080p']}
        releases = _ignored_release() + [
            {'_id': 'new-1', 'status': 'done', 'quality': '1080p',
             'last_edit': 2000, 'is_3d': False},
        ]

        result, updated, _ = _run_restatus(movie, profile, releases)

        assert result == 'done', (
            'a release obtained AFTER the restore must finish the movie '
            'normally, got %r' % result
        )
        assert updated, 'a real transition must write'

    def test_a_movie_that_still_holds_a_done_release_is_unaffected(self):
        """Regression lock for every movie that was never restored: a 'done'
        release must still finish it, exactly as before."""
        movie = _restored_movie()
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}
        releases = [{'_id': 'held-1', 'status': 'done', 'quality': '1080p',
                     'last_edit': 1000, 'is_3d': False}]

        result, updated, fired = _run_restatus(movie, profile, releases)

        assert result == 'downloaded'
        assert 'movie.downloaded' in fired
        assert updated
