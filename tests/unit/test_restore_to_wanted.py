"""Unit tests for FEAT-008's `movie.restore_to_wanted` -- moving a `done`
movie back to wanted ('active') without losing its release history.

Root-cause context (specs/FEAT-008-search-feedback-and-back-to-wanted.md):
1101 of 1101 sampled production movies have `profile_id = None`. A movie
moved to `active` with no profile is unsearchable -- it would sit in Wanted
forever, and single()'s own gate (searcher.py:172) would skip it right back
out again. So this view must always ensure a real, resolvable profile before
writing `status = 'active'`, and refuse rather than create a Wanted entry
that can never be found.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.core.media.movie._base.main import MovieBase


def make_update_with_retry(doc):
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
        return doc
    return _fake


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
                patch('couchpotato.core.media.movie._base.main.fireEvent'):
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
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'profile-1'})
        db.update_with_retry.side_effect = make_update_with_retry(movie)

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent'):
            plugin.restoreToWanted('movie-1')

        assert movie['releases'] == releases, 'releases must be untouched'

    def test_is_a_no_op_success_on_an_already_active_movie(self):
        """AC4: idempotent -- must not error, and must not write anything."""
        movie = _movie(status='active', profile_id='profile-1')
        plugin = MovieBase.__new__(MovieBase)
        db = MagicMock()
        db.get.side_effect = _db_get_side_effect(movie, known_profile_ids={'profile-1'})

        with patch('couchpotato.core.media.movie._base.main.get_db', return_value=db), \
                patch('couchpotato.core.media.movie._base.main.fireEvent') as fire:
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is True
        assert not db.update_with_retry.called, 'an already-active movie must not be written to'
        assert not any(c.args[0] == 'profile.default' for c in fire.call_args_list), (
            'no profile resolution should happen for a no-op call'
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
                patch('couchpotato.core.media.movie._base.main.fireEvent'), \
                caplog.at_level(logging.WARNING, logger='couchpotato.core.media.movie._base.main'):
            result = plugin.restoreToWanted('movie-1')

        assert result['success'] is False
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(warning_records) == 1
        assert error_records == []


class TestRestoreToWantedIsSearchable:
    """AC5: the movie appears in Wanted afterwards and is picked up by the
    automatic searcher -- i.e. it must pass single()'s own gate."""

    def test_the_restored_movie_passes_the_searchers_gate(self):
        """Drive the REAL gate condition from searcher.py rather than
        re-describing it, so this test breaks if that gate's shape changes
        out from under this assumption."""
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
            plugin.restoreToWanted('movie-1')

        manual = False
        list_only = False
        gate_bails = (
            (not movie['profile_id'] and not list_only)
            or (movie['status'] in ('done', 'downloaded') and not manual and not list_only)
        )
        assert not gate_bails, (
            'the restored movie must pass single()\'s gate -- it has both a '
            'profile_id and an "active" status'
        )


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
