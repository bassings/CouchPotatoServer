"""Unit tests for FEAT-008's `movie.restore_to_wanted` -- moving a `done`
movie back to wanted ('active') without losing its release history.

Root-cause context (specs/FEAT-008-search-feedback-and-back-to-wanted.md):
1101 of 1101 sampled production movies have `profile_id = None`. A movie
moved to `active` with no profile is unsearchable -- it would sit in Wanted
forever, and single()'s own first gate would skip it right back
out again. So this view must always ensure a real, resolvable profile before
writing `status = 'active'`, and refuse rather than create a Wanted entry
that can never be found.
"""

import logging
import time
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from CodernityDB.database import RecordNotFound
from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.core.media.movie._base.main import MovieBase


def make_update_with_retry(doc, writes=None):
    """As below, but `writes` (a list) records each actual write.

    Needed because "the doc is unchanged" cannot distinguish "the guard
    short-circuited" from "the mutator rewrote identical values" -- which is
    exactly what an idempotent restore does. Only a write COUNT can see it.
    """
    return _make_update_with_retry(doc, writes)


def _make_update_with_retry(doc, writes=None):
    """Mimic SQLiteAdapter.update_with_retry(mutator, doc_id) by applying the
    mutator to `doc` in place and returning it. Mirrors the helper of the
    same name in test_mark_done.py / test_watch_history.py."""
    def _fake(mutator, doc_id, retries=3):
        assert doc_id == doc['_id']
        result = mutator(doc)
        # Mirror the real contract: a mutator returning False means "no
        # change needed" -- no write, return None.
        if result is False:
            return None
        if writes is not None:
            writes.append(dict(doc))
        return doc
    return _fake


def _fire_stub(isfinish=False, releases=None):
    """fireEvent stand-in for tests that do not care about release marking.

    A bare MagicMock returns a truthy Mock for EVERY event, including
    release.for_media -- which restoreToWanted then iterates. Tests that are
    about something else need to say what that call returns.
    """
    def _fire(name, *a, **k):
        if name == 'quality.isfinish':
            return isfinish
        if name == 'release.for_media':
            return releases or []
        return None
    return _fire


def _movie(status='done', profile_id=None, releases=None):
    return {
        '_id': 'movie-1',
        '_t': 'media',
        'type': 'movie',
        'title': 'Some Movie',
        'status': status,
        'profile_id': profile_id,
        'releases': releases if releases is not None else [
            {'_id': 'rel-1', 'status': 'done', 'quality': '1080p'},
        ],
    }


def _db_get_side_effect(movie, known_profile_ids):
    """A db.get('id', key) stand-in that knows about exactly one media doc
    and a set of "real" profile ids -- everything else raises KeyError, the
    same exception SQLiteAdapter.get() raises for an unknown id."""
    def _get(index_name, key):
        assert index_name == 'id'
        if key == movie['_id']:
            return movie
        if key in known_profile_ids:
            return {'_id': key, '_t': 'profile'}
        raise KeyError('Document not found: %s' % key)
    return _get


class TestRestoreToWantedProfileResolution:

    def test_assigns_the_default_profile_when_the_movie_has_none(self):
        """AC1 / AC5: the exact case the 2026-07-31 report is about -- a
        library-scanned movie with no profile must become searchable."""
        movie = _movie(status='done', profile_id=None)
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids=set())
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.side_effect = lambda name, *a, **k: (
                {'_id': 'default-profile'} if name == 'profile.default' else None
            )
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True
        assert movie['status'] == 'active'
        assert movie['profile_id'] == 'default-profile'

    def test_keeps_the_movies_existing_profile_when_it_still_exists(self):
        """AC1: the caller's profile_id, else the movie's existing one, else
        default -- an existing valid profile must win over the default."""
        movie = _movie(status='done', profile_id='existing-profile')
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'existing-profile'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.side_effect = _fire_stub()
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True
        assert movie['profile_id'] == 'existing-profile'
        assert not any(c.args[0] == 'profile.default' for c in fire.call_args_list), (
            'the default profile must not be resolved when the movie already '
            'has a valid one'
        )

    def test_an_explicit_profile_id_wins_over_the_movies_existing_one(self):
        movie = _movie(status='done', profile_id='old-profile')
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(
            movie, known_profile_ids={'old-profile', 'chosen-profile'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent', side_effect=_fire_stub()):
            result = plugin.restoreToWanted('movie-1', profile_id='chosen-profile')

        assert result['success'] is True
        assert movie['profile_id'] == 'chosen-profile'

    def test_falls_back_to_default_when_the_movies_existing_profile_was_deleted(self):
        """A dangling profile_id (the profile was deleted after assignment)
        must not be trusted blindly -- fall through to the default rather
        than restoring the movie with a profile_id that no longer resolves."""
        movie = _movie(status='done', profile_id='deleted-profile')
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids=set())
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.side_effect = lambda name, *a, **k: (
                {'_id': 'default-profile'} if name == 'profile.default' else None
            )
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True
        assert movie['profile_id'] == 'default-profile'

    def test_refuses_when_no_profile_can_be_resolved_anywhere(self):
        """AC2: refuse with a stated reason rather than create an
        unsearchable Wanted entry -- fresh install / every profile deleted."""
        movie = _movie(status='done', profile_id=None)
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids=set())

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.side_effect = lambda name, *a, **k: None  # no default profile exists
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is False
        assert isinstance(result.get('error'), str) and result['error']
        assert movie['status'] == 'done', 'a refused restore must not touch the movie at all'
        assert not db.update_with_retry.called, (
            'a refused restore must never write to the movie -- that would '
            'create the unsearchable Wanted entry AC2 exists to prevent'
        )


class TestRestoreToWantedReleasesAndIdempotency:

    def test_does_not_delete_or_modify_existing_releases(self):
        """AC3: a done release is not deleted -- the movie just becomes
        eligible for searching/upgrading again."""
        releases = [{'_id': 'rel-1', 'status': 'done', 'quality': '1080p'}]
        movie = _movie(status='done', profile_id='profile-1', releases=releases)
        # Snapshot BEFORE the call. Asserting against `releases` itself was
        # vacuous: it is the same object the movie holds, so an in-place
        # mutation (the likely bug) changed both sides and still compared equal.
        expected = deepcopy(releases)
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'profile-1'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent'):
            plugin.restoreToWanted('movie-1')

        assert movie['releases'] == expected, 'releases must be untouched'

    def test_is_a_no_op_success_on_an_already_active_movie(self):
        """AC4: idempotent -- must not error, and must not change the movie.

        Idempotence is enforced by the CAS mutator (which returns False, so no
        write happens), NOT by an early return. An early return also skipped
        the release marking, which turned this method into a status write
        instead of a repair -- see
        TestRestoreIsARepairPathNotJustAStatusWrite.
        """
        movie = _movie(status='active', profile_id='profile-1')
        before = deepcopy(movie)
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'profile-1'})
        writes = []
        db.update_with_retry.side_effect = make_update_with_retry(movie, writes)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.return_value = None
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True
        assert writes == [], 'an already-active movie must not be written to'
        assert movie == before, 'an already-active movie must not be modified'
        assert not any(c.args[0] == 'profile.default' for c in fire.call_args_list), (
            'the movie has a valid profile; the default must not be resolved'
        )

    def test_returns_error_when_media_does_not_exist(self):
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = KeyError('missing-id')

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db):
            result = plugin.restoreToWanted('missing-id')

        assert result == {'success': False, 'error': 'Media not found'}

    def test_conflict_error_after_retries_returns_failure_and_logs_warning(self, caplog):
        movie = _movie(status='done', profile_id='profile-1')
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'profile-1'})
        db.update_with_retry.side_effect = ConflictError('movie-1')

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent',
                      side_effect=_fire_stub()), \
                caplog.at_level(logging.WARNING, logger='couchpotato.core.media.movie._base.main'):
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is False
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(warning_records) == 1
        assert error_records == []


# AC5 ("picked up by the automatic searcher") is verified in
# tests/unit/test_search_releases_list_only.py::
# TestARestoredMovieIsPickedUpByTheAutomaticSearcher, which drives the REAL
# single() gate. A test that lived here re-typed a copy of the gate expression
# into its own body and evaluated that instead -- replacing the entire gate
# with `if True:` left it green, so it was pinning nothing. It is gone rather
# than fixed: this file has no searcher harness, and the other file does.


class TestRestoreToWantedApiView:

    def test_the_view_is_registered(self):
        import inspect

        source = inspect.getsource(MovieBase.__init__)

        assert "addApiView('movie.restore_to_wanted'" in source

    def test_the_view_reads_profile_id_from_params_and_delegates(self):
        plugin = MovieBase.__new__(MovieBase)

        with patch.object(type(plugin), 'restoreToWanted', return_value={'success': True}, create=True) as core:
            result = plugin.restoreToWantedView(media_id='movie-1', profile_id='profile-9')

        assert result == {'success': True}
        core.assert_called_once_with('movie-1', profile_id='profile-9')


class TestIdempotenceStillHonoursTheProfileGuarantee:
    """Review finding: the idempotence short-circuit skipped AC1.

    `if media['status'] == 'active': return success` fired before the profile
    was resolved, so an already-active movie with `profile_id=None` got a
    success with nothing written -- and stayed UNSEARCHABLE, because single()'s
    gate skips profile-less movies. Half of what "wanted" means is having a
    profile to search against; reporting success without one is the same class
    of misleading report as FEAT-008's other half.
    """

    def test_an_active_movie_with_no_profile_is_repaired_not_rubber_stamped(self):
        movie = _movie(status='active', profile_id=None)
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids=set())
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.side_effect = lambda name, *a, **k: (
                {'_id': 'default-profile'} if name == 'profile.default' else None
            )
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True
        assert movie['profile_id'] == 'default-profile', (
            'an active movie with no profile was left unsearchable'
        )

    def test_an_active_movie_that_already_has_a_profile_is_a_true_no_op(self):
        """The genuine no-op case must stay one -- nothing changes.

        Asserts the INVARIANT (the movie is untouched), not the mechanism.
        It used to assert `update_with_retry` was never called, which pinned
        the early-return implementation rather than the behaviour -- and that
        early return had to go, because it also skipped the release marking
        and made restore unable to repair a half-restored movie.
        """
        movie = _movie(status='active', profile_id='existing-profile')
        before = deepcopy(movie)
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'existing-profile'})
        writes = []
        db.update_with_retry.side_effect = make_update_with_retry(movie, writes)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.side_effect = lambda name, *a, **k: None
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True
        assert writes == [], 'wrote a movie that needed nothing done'
        assert movie == before, 'changed a movie that needed nothing done'
        assert movie['profile_id'] == 'existing-profile'
        assert not any(c.args[0] == 'profile.default' for c in fire.call_args_list), (
            'resolved the default profile for a movie that already has one'
        )


class TestLosingTheCasRaceReportsTheWinnersState:
    """Backend finding: when update_with_retry's mutator returns False on a
    retry (another writer got there first), it returns None and the code fell
    back to `media` -- the doc read BEFORE the race. That pre-race snapshot was
    then handed to notify.frontend and returned to the caller, so the UI was
    pushed stale state (status still 'done') for a movie that IS now active.
    The fallback must re-read, not reuse the stale read."""

    def test_it_re_reads_instead_of_returning_the_pre_race_snapshot(self):
        stale = _movie(status='done', profile_id=None)
        winner = _movie(status='active', profile_id='profile-winner')

        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()

        reads = {'n': 0}

        def _get(key, value, **kwargs):
            if key == 'id' and value == 'movie-1':
                reads['n'] += 1
                # First read is ours; by the time we re-read, the other
                # writer's version is what the database holds.
                return stale if reads['n'] == 1 else winner
            if key == 'id' and value == 'profile-winner':
                return {'_id': 'profile-winner'}
            raise RecordNotFound(value)

        db.get.side_effect = _get
        # Lost the race: the mutator's own guard returns False -> None.
        db.update_with_retry.return_value = None

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            # Explicit: restoreToWanted iterates release.for_media, which a
            # bare Mock would return a non-iterable Mock for.
            fire.side_effect = _fire_stub()
            result = plugin.restoreToWanted('movie-1', profile_id='profile-winner')

        assert result['success'] is True
        assert result['media']['status'] == 'active', (
            'returned the pre-race snapshot instead of re-reading the winner'
        )

        notified = [c for c in fire.call_args_list if c.args and c.args[0] == 'notify.frontend']
        assert notified, 'no frontend notification was sent'
        assert notified[0].kwargs['data']['status'] == 'active', (
            'pushed stale pre-race state to the UI'
        )


class TestAnActiveMovieWithADanglingProfileIsRepaired:
    """Review finding: the idempotence pre-check and the CAS mutator used two
    DIFFERENT definitions of "has a profile" --

        pre-check: existingProfileId(db, media)   -> resolvable
        mutator:   m.get('profile_id')            -> merely truthy

    so a movie that is 'active' with a profile_id pointing at a DELETED profile
    fell through the pre-check (correctly), resolved a good default... and then
    the mutator bailed on truthiness and wrote nothing. Success was reported
    for a movie left exactly as unsearchable as before: single()'s own gate
    passes the truthiness check, then db.get('id', profile_id) raises and
    searchAll swallows it as 'Search failed'. The two guards must agree.
    """

    def test_the_dangling_reference_is_replaced_with_a_resolvable_profile(self):
        movie = _movie(status='active', profile_id='deleted-profile')

        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        # 'deleted-profile' no longer exists; only the default does.
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'default-profile'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.side_effect = lambda name, *a, **k: (
                {'_id': 'default-profile'} if name == 'profile.default' else None
            )
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True
        assert movie['profile_id'] == 'default-profile', (
            'the dangling profile reference was left in place, so the movie is '
            'still unsearchable while the call reported success'
        )


class TestACallerSuppliedProfileIdIsNotTrusted:
    """The caller's profile_id is validated before use, but nothing pinned it:
    replacing `existingProfileId(db, {'profile_id': profile_id})` with a bare
    `profile_id` left the entire 1880-test suite green. Every other test that
    passes a profile_id passes a RESOLVABLE one, so the guard that stops AC2's
    unsearchable Wanted entry -- when a user's picker is showing a profile that
    has since been deleted -- was completely unconstrained.
    """

    def test_a_stale_id_from_the_caller_falls_back_instead_of_being_stored(self):
        movie = _movie(status='done', profile_id=None)
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        # The caller's pick no longer exists; only the default does.
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'default-profile'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            fire.side_effect = lambda name, *a, **k: (
                {'_id': 'default-profile'} if name == 'profile.default' else None
            )
            result = plugin.restoreToWanted('movie-1', profile_id='profile-deleted-in-another-tab')

        assert result['success'] is True
        assert movie['profile_id'] == 'default-profile', (
            "stored the caller's dangling profile_id, creating exactly the "
            'unsearchable Wanted entry AC2 exists to prevent'
        )


class TestRestoreIsScopedToStatusesItMakesSenseFor:
    """`markFailedAndResearch` deliberately refuses unless the movie is in the
    status it is written for, so a confirmed movie is never silently reopened.
    This had no such guard: any status was flipped to 'active'.

    The reachable case is a 'chart' or 'suggested' entry (movie/charts), which
    an API call would otherwise promote straight into the wanted list. The UI
    only offers the control for a 'done' movie, so this is API reach.

    It is NOT about 'snatched'. An earlier version of this test used
    status='snatched' and claimed the guard stopped a second copy being grabbed
    mid-download -- but nothing in this codebase assigns media status
    'snatched' (it is a RELEASE status), so the test pinned a state that cannot
    exist. The mutation killed it, which is exactly why an unreal scenario is
    worth catching: it read as covered.
    """

    def test_a_chart_entry_is_refused(self):
        movie = _movie(status='chart', profile_id='profile-1')
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'profile-1'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent', side_effect=_fire_stub()):
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is False
        # A specific assertion: the earlier form was
        #   `'snatched' in error.lower() or result.get('error')`
        # whose second clause passes for ANY non-empty error, so the first
        # could never fail the test.
        assert 'chart' in result.get('error', '').lower(), (
            'the refusal must name the status it refused: %r' % result.get('error')
        )
        assert movie['status'] == 'chart', 'a refused restore must not write'
        assert not db.update_with_retry.called

    @pytest.mark.parametrize('status', ['done', 'downloaded'])
    def test_the_statuses_the_feature_exists_for_are_still_allowed(self, status):
        """The other direction -- the guard must not block the feature itself.
        'downloaded' is the review gate, which a user may equally want to send
        back to wanted."""
        movie = _movie(status=status, profile_id='profile-1')
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'profile-1'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent', side_effect=_fire_stub()):
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True, 'refused the case the feature is for'
        assert movie['status'] == 'active'


class TestTheHeldReleasesAreDiscounted:
    """Setting status='active' is not enough on a real install.

    Every profile this app creates uses finish=True on every rung
    (plugins/profile/main.py: "take the best thing available now, then stop"),
    so quality.isfinish is True for ANY held release. Measured against the real
    isFinish and the real single():

        profile [1080p]         holding 1080p -> isFinish True,  0 searches
        profile [2160p, 1080p]  holding 1080p -> isFinish False, 1 search

    So on a default profile the movie would be finished again by the next
    media.restatus, and single()'s has_better_quality loop would break before
    contacting a provider. Marking the held releases 'ignored' addresses both:
    restatus counts only 'done', and has_better_quality skips
    ('available', 'ignored', 'failed').

    Durability is release.add's job -- see
    tests/unit/test_release_add_preserves_ignored.py. Relying on a profile that
    leaves room instead was considered and rejected: it would refuse essentially
    every real restore, because no default profile leaves room.
    """

    def _restore(self, releases, status='done'):
        movie = _movie(status=status, profile_id='profile-1')
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'profile-1'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)
        updates = []

        def _fire(name, *a, **k):
            if name == 'release.for_media':
                return releases
            if name == 'release.update_status':
                updates.append((a[0] if a else None, k.get('status')))
            return None

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent', side_effect=_fire):
            result = plugin.restoreToWanted('movie-1')
        return result, movie, updates

    def test_a_held_done_release_is_marked_ignored(self):
        result, _, updates = self._restore([{'_id': 'rel-1', 'status': 'done'}])

        assert result['success'] is True
        assert ('rel-1', 'ignored') in updates, (
            'the held release still satisfies the profile, so the next sweep '
            'finishes the movie again and no search ever runs'
        )

    def test_seeding_and_downloaded_releases_are_discounted_too(self):
        _, _, updates = self._restore([
            {'_id': 'rel-seed', 'status': 'seeding'},
            {'_id': 'rel-dl', 'status': 'downloaded'},
        ])

        assert ('rel-seed', 'ignored') in updates
        assert ('rel-dl', 'ignored') in updates

    def test_releases_the_movie_does_not_hold_are_left_alone(self):
        """An 'available' release is a search RESULT, not a copy the user has --
        rewriting it would throw away the list the UI shows."""
        _, _, updates = self._restore([
            {'_id': 'rel-avail', 'status': 'available'},
            {'_id': 'rel-failed', 'status': 'failed'},
        ])

        assert updates == [], 'rewrote releases the movie does not hold: %r' % updates

    def test_a_refused_restore_does_not_touch_releases(self):
        result, movie, updates = self._restore(
            [{'_id': 'rel-1', 'status': 'done'}], status='chart')

        assert result['success'] is False
        assert updates == []
        assert movie['status'] == 'chart'


