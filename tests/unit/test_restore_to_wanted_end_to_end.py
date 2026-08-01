"""The whole FEAT-008 flow, end to end, in one test.

Every defect found in review rounds 3 through 6 lived BETWEEN functions that
each looked correct alone: restore worked, restatus worked, the scanner worked,
and the flow still ended in a broken state. Four designs passed their own unit
tests and failed one step further down. So this drives the real
`restoreToWanted`, the real `Release.add` and the real `MediaPlugin.restatus`
in sequence and asserts the state after each step.

Deliberately uses the hostile configuration rather than a convenient one:

  - the profile has finish=True (what build_profile_doc creates for every
    seeded profile), so a held release satisfies quality.isfinish;
  - manual_confirmation=True (the FEAT-004 default), which is what routes a
    completion into the review gate and fires movie.downloaded;
  - the replacement copy lands at exactly the SAME path as the old one, which
    is what the default renamer template produces since it carries no quality,
    group or source token.

Historic failures this pins, in order of the step that used to break:
  step 2 - a library rescan resurrected the set-aside release, so the movie
           silently left Wanted (or stalled contacting no providers) and fired
           a FALSE "downloaded -- awaiting review" notification;
  step 3 - keying the guard on the quality rung or on file paths filed the new
           copy as 'ignored' too, so the movie never completed and the searcher
           re-grabbed it on a weekly cadence.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.media._base.media.main import MediaPlugin
from couchpotato.core.media.movie._base.main import MovieBase
from couchpotato.core.plugins.release.main import Release, copyIdentity


@pytest.fixture
def world(tmp_path):
    """A done movie with one 1080p copy on disk, on a default-shaped profile."""
    library = tmp_path / 'Some Movie (2020)'
    library.mkdir()
    path = str(library / 'Some Movie.mkv')      # default naming: no quality token
    with open(path, 'w') as fh:
        fh.write('A' * 5000)

    docs = {
        'movie-1': {'_id': 'movie-1', '_t': 'media', 'type': 'movie', 'title': 'Some Movie',
                    'status': 'done', 'profile_id': 'p1', 'identifiers': {'imdb': 'tt1'},
                    'releases': []},
        'p1': {'_id': 'p1', '_t': 'profile', 'qualities': ['1080p'], 'finish': [True],
               'stop_after': [0], '3d': [False], 'manual_confirmation': True},
        'rel-1': {'_id': 'rel-1', '_rev': 'r1', '_t': 'release', 'media_id': 'movie-1',
                  'identifier': 'tt1.unknown.1080p', 'quality': '1080p', 'status': 'done',
                  'files': {'movie': [path]}, 'copy_id': copyIdentity({'movie': [path]}),
                  'last_edit': 1000},
    }

    def _get(index, key, **kw):
        if index == 'media':
            return {'doc': docs['movie-1']}
        if index == 'release_identifier':
            return {'doc': docs['rel-1']} if kw.get('with_doc') else docs['rel-1']
        if index == 'id' and key in docs:
            return docs[key]
        raise KeyError(key)

    db = MagicMock()
    db.get.side_effect = _get
    db.update.side_effect = lambda d: docs.__setitem__(d['_id'], d)

    def _retry(mutator, doc_id, retries=3):
        return None if mutator(docs[doc_id]) is False else docs[doc_id]

    db.update_with_retry.side_effect = _retry
    return {'db': db, 'docs': docs, 'path': path}


def _restore(world):
    """Drives the REAL Release.updateStatus for release.update_status.

    An earlier version of this helper stubbed that event with a one-line
    `status = ...` assignment -- and so skipped the copy-identity backfill that
    lives inside the real implementation, hiding a defect that made the whole
    feature inert on existing installs. A stub at a boundary is exactly where
    these bugs have been hiding all along; this test exists to cross
    boundaries, so it must not fake the far side of one.
    """
    plugin = MovieBase.__new__(MovieBase)
    release_plugin = Release.__new__(Release)

    def _fire(name, *a, **k):
        if name == 'release.for_media':
            return [world['docs']['rel-1']]
        if name == 'release.update_status':
            with patch('couchpotato.core.plugins.release.main.get_db', return_value=world['db']), \
                    patch('couchpotato.core.plugins.release.main.fireEvent', return_value=None):
                return release_plugin.updateStatus(a[0], status = k.get('status'))
        return None

    with patch('couchpotato.core.media.movie._base.main.get_db', return_value=world['db']), \
            patch('couchpotato.core.media.movie._base.main.fireEvent', side_effect=_fire):
        return plugin.restoreToWanted('movie-1')


def _library_scan(world):
    plugin = Release.__new__(Release)
    group = {'identifier': 'tt1',
             'meta_data': {'quality': {'identifier': '1080p', 'is_3d': 0}},
             'files': {'movie': [world['path']]}}
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=world['db']), \
            patch('couchpotato.core.plugins.release.main.fireEvent', return_value=None), \
            patch.object(type(plugin), 'conf', return_value=False, create=True):
        plugin.add(group)


def _restatus(world):
    plugin = MediaPlugin.__new__(MediaPlugin)
    fired = []

    def _fire(name, *a, **k):
        fired.append(name)
        if name == 'release.for_media':
            return [world['docs']['rel-1']]
        if name == 'quality.isfinish':
            return True
        return None

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=world['db']), \
            patch('couchpotato.core.media._base.media.main.fireEvent', side_effect=_fire):
        plugin.restatus('movie-1', tag_recent=False)
    return fired


class TestTheWholeFlow:

    def test_restore_survives_a_rescan_and_a_new_copy_still_completes(self, world):
        docs = world['docs']

        # 1. The user presses "Move back to wanted".
        assert _restore(world)['success'] is True
        assert docs['movie-1']['status'] == 'active'
        assert docs['rel-1']['status'] == 'ignored', 'the held copy still counts'

        # 2. "Update Library" (or the refresh cron) rescans the UNCHANGED file.
        #    This is the step that broke in every earlier design.
        _library_scan(world)
        assert docs['rel-1']['status'] == 'ignored', (
            'a rescan resurrected the set-aside copy, so the movie is about to '
            'leave Wanted again'
        )

        # ...and the movie is still wanted, with no false notification.
        fired = _restatus(world)
        assert docs['movie-1']['status'] == 'active', (
            'the movie left Wanted after a rescan that changed nothing'
        )
        assert 'movie.downloaded' not in fired, (
            'fired "downloaded -- awaiting review" for a movie the user never '
            're-downloaded'
        )

        # 3. The searcher finds a better encode; the renamer lands it at the
        #    SAME path (the default template has no quality token). Only the
        #    size differs -- which is exactly why the identity is size-based.
        with open(world['path'], 'w') as fh:
            fh.write('B' * 9000)
        _library_scan(world)
        assert docs['rel-1']['status'] == 'done', (
            'the new copy was filed as %r, so the movie can never complete and '
            'the searcher will grab it again' % docs['rel-1']['status']
        )

        # 4. And now the movie completes, with a notification that is TRUE.
        fired = _restatus(world)
        assert docs['movie-1']['status'] == 'downloaded'
        assert 'movie.downloaded' in fired, (
            'the user really did download a new copy; this notification is the '
            'one they should get'
        )


class TestAnExistingInstallWithNoCopyIdYet:
    """The world every real user is actually in on the day this ships.

    `copy_id` is written by Release.add, and there is no migration. So every
    release doc that predates FEAT-009 has none -- and the set-aside guard
    requires a STORED id to compare against. Without a backfill at the moment
    the release is set aside, the very first restore is undone by the next full
    scan and fires the false "downloaded -- awaiting review" notification this
    branch has been chasing since round 3.

    The test above did not catch this: its fixture pre-seeds
    `copy_id`, so it only ever exercised the post-migration world. A fixture
    that hands the code the state it needs is the "incidentally passing" trap
    (CLAUDE.md section 11) -- and it hid a CRITICAL in the one test written
    specifically to catch between-function failures.
    """

    def test_restore_backfills_the_identity_so_a_rescan_cannot_undo_it(self, world):
        docs = world['docs']
        del docs['rel-1']['copy_id']            # a pre-FEAT-009 release doc

        assert _restore(world)['success'] is True
        assert docs['rel-1']['status'] == 'ignored'
        assert docs['rel-1'].get('copy_id'), (
            'no identity recorded when the release was set aside, so the next '
            'full scan has nothing to compare against and will resurrect it'
        )

        _library_scan(world)
        assert docs['rel-1']['status'] == 'ignored', (
            'a rescan undid the restore on an existing install -- the feature '
            'is inert for every user who already has a library'
        )

        fired = _restatus(world)
        assert docs['movie-1']['status'] == 'active'
        assert 'movie.downloaded' not in fired, 'fired the false notification again'
