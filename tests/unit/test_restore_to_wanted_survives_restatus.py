"""FEAT-008 AC5: a movie moved back to wanted must STAY wanted.

Review finding (2026-07-31, second round). `restoreToWanted` writes
status='active' and deliberately PRESERVES the existing 'done' release (AC3).
But `MediaPlugin.restatus` recomputes status from the releases it finds, and
the preserved release still satisfies `quality.isfinish` -- seeded profiles are
built with finish=[True]*n and stop_after=[0]*n, so essentially any held
release finishes the movie.

So the very next automatic sweep (`searchAll` selects status='active', then
`single()` fires media.restatus) wrote the movie straight back out of Wanted.
Worse, with `manual_confirmation` -- the FEAT-004 DEFAULT -- `previous_status`
is now 'active' rather than 'done', which routes it to the 'downloaded' review
gate AND fires a `movie.downloaded` "awaiting review" notification for a movie
the user never re-downloaded.

Net effect without this guard: "Move back to wanted" appeared to work, then
silently undid itself within one search cycle, with a false notification. That
is AC5 ("the movie appears in the Wanted view afterwards and is picked up by
the automatic searcher") not holding at all.
"""
import time
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
            return True          # the held release DOES finish the profile
        return None

    with (
        patch('couchpotato.core.media._base.media.main.get_db', return_value=FakeDB()),
        patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=fake_fire_event),
    ):
        result = plugin.restatus(media_doc['_id'], tag_recent=False)

    return result, updated, fired


def _restored_movie(**extra):
    """Exactly the document restoreToWanted leaves behind: active, a
    resolvable profile, and the pre-existing done release untouched."""
    movie = {
        '_id': 'movie-1',
        'type': 'movie',
        'title': 'Some Movie',
        'status': 'active',
        'profile_id': 'profile-1',
        'restored_to_wanted_at': time.time(),
    }
    movie.update(extra)
    return movie


# The release the user already had -- edited BEFORE the restore.
def _held_release():
    return [{'status': 'done', 'quality': '1080p', 'last_edit': time.time() - 86400, 'is_3d': False}]


class TestARestoredMovieStaysWanted:

    def test_a_manual_confirmation_profile_does_not_send_it_to_the_review_gate(self):
        movie = _restored_movie()
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}

        result, updated, fired = _run_restatus(movie, profile, _held_release())

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

        result, updated, _ = _run_restatus(movie, profile, _held_release())

        assert result == 'active', (
            'the restored movie went straight back to %r' % result
        )


class TestTheGuardIsNarrow:
    """It must suppress ONLY the release the user already had. A genuinely new
    download has to complete the movie normally, or restore would break
    upgrading permanently."""

    def test_a_release_grabbed_after_the_restore_still_completes_the_movie(self):
        restored_at = time.time() - 3600
        movie = _restored_movie(restored_to_wanted_at=restored_at)
        profile = {'_id': 'profile-1', 'qualities': ['1080p']}
        # Edited AFTER the restore -- this is the upgrade the user asked for.
        new_release = [{'status': 'done', 'quality': '1080p',
                        'last_edit': restored_at + 60, 'is_3d': False}]

        result, _, _ = _run_restatus(movie, profile, new_release)

        assert result == 'done', (
            'a release obtained AFTER the restore must finish the movie '
            'normally, got %r' % result
        )

    def test_a_movie_that_was_never_restored_is_completely_unaffected(self):
        """Regression lock for every existing movie: with no restore marker the
        behaviour must be byte-for-byte what it was before this guard."""
        movie = _restored_movie()
        del movie['restored_to_wanted_at']
        profile = {'_id': 'profile-1', 'qualities': ['1080p'], 'manual_confirmation': True}

        result, updated, fired = _run_restatus(movie, profile, _held_release())

        assert result == 'downloaded'
        assert 'movie.downloaded' in fired
        assert updated, 'a real transition must still write'
