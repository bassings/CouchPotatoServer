"""Unit tests for media watch history behaviour."""
import logging
import tempfile
from unittest.mock import MagicMock, patch

from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.core.media._base.media.main import MediaPlugin


def make_media(media_id, watched=False, status='done'):
    media = {
        '_id': media_id,
        '_t': 'media',
        'type': 'movie',
        'status': status,
        'title': f'Movie {media_id}',
        'info': {'year': 2026, 'titles': [f'Movie {media_id}']},
        'identifiers': {'imdb': f'tt{media_id}'},
    }
    if watched:
        media.update({
            'watched': True,
            'watched_at': '2026-05-09T01:00:00Z',
            'watched_by': 'Scott',
            'watched_source': 'manual',
        })
    return media


def make_update_with_retry(doc):
    """Build a MagicMock side_effect that mimics
    SQLiteAdapter.update_with_retry(mutator, doc_id) by applying the
    mutator to `doc` and returning it -- used to test callers that were
    converted to the CAS retry helper without depending on a real adapter."""
    def _fake(mutator, doc_id, retries=3):
        assert doc_id == doc['_id']
        mutator(doc)
        return doc
    return _fake


def test_mark_watched_records_watch_metadata_without_changing_media_status():
    """markWatched sets watch fields but preserves existing media status."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    movie = make_media('movie-1', status='active')
    db = MagicMock()
    db.update_with_retry.side_effect = make_update_with_retry(movie)

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
         patch('couchpotato.core.media._base.media.main.fireEvent') as fire_event:
        result = plugin.markWatched(id='movie-1', watched_by='Scott')

    assert result['success'] is True
    assert result['media'] is movie
    assert movie['status'] == 'active'
    assert movie['watched'] is True
    assert movie['watched_by'] == 'Scott'
    assert movie['watched_source'] == 'manual'
    assert movie['watched_at'].endswith('Z')
    db.update_with_retry.assert_called_once()
    fire_event.assert_called_once_with('notify.frontend', type='movie.update', data=movie)


def test_mark_unwatched_clears_watch_metadata_without_changing_media_status():
    """markUnwatched removes watch fields but preserves existing media status."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    movie = make_media('movie-1', watched=True, status='done')
    db = MagicMock()
    db.update_with_retry.side_effect = make_update_with_retry(movie)

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
         patch('couchpotato.core.media._base.media.main.fireEvent'):
        result = plugin.markUnwatched(id='movie-1')

    assert result['success'] is True
    assert movie['status'] == 'done'
    assert movie['watched'] is False
    assert 'watched_at' not in movie
    assert 'watched_by' not in movie
    assert 'watched_source' not in movie
    db.update_with_retry.assert_called_once()


def test_mark_watched_returns_not_found_when_media_missing():
    """markWatched surfaces a not-found result when the media doc is gone,
    matching the previous get()-based not-found behaviour."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    db = MagicMock()
    db.update_with_retry.side_effect = KeyError('missing-1')

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
         patch('couchpotato.core.media._base.media.main.fireEvent') as fire_event:
        result = plugin.markWatched(id='missing-1')

    assert result == {'success': False, 'error': 'Media not found'}
    fire_event.assert_not_called()


def test_mark_watched_conflict_error_after_retries_returns_failure_and_logs_warning(caplog):
    """When update_with_retry exhausts its retries under persistent write
    contention it raises ConflictError -- an expected, distinguishable
    condition, not a code defect. markWatched must log it at WARNING (not
    fall through to the generic 'except Exception' ERROR-with-traceback
    branch) while still returning the same {'success': False, 'error': ...}
    shape the generic-exception path returns."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    db = MagicMock()
    db.update_with_retry.side_effect = ConflictError('movie-1')

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
         patch('couchpotato.core.media._base.media.main.fireEvent') as fire_event, \
         caplog.at_level(logging.WARNING, logger='couchpotato.core.media._base.media'):
        result = plugin.markWatched(id='movie-1', watched_by='Scott')

    assert result['success'] is False
    assert isinstance(result['error'], str) and result['error']
    fire_event.assert_not_called()

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(warning_records) == 1
    assert 'movie-1' in warning_records[0].getMessage()
    assert error_records == []


def test_mark_unwatched_conflict_error_after_retries_returns_failure_and_logs_warning(caplog):
    """Same proof as test_mark_watched_conflict_error_after_retries_returns_failure_and_logs_warning
    but for markUnwatched."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    db = MagicMock()
    db.update_with_retry.side_effect = ConflictError('movie-1')

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
         patch('couchpotato.core.media._base.media.main.fireEvent') as fire_event, \
         caplog.at_level(logging.WARNING, logger='couchpotato.core.media._base.media'):
        result = plugin.markUnwatched(id='movie-1')

    assert result['success'] is False
    assert isinstance(result['error'], str) and result['error']
    fire_event.assert_not_called()

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(warning_records) == 1
    assert 'movie-1' in warning_records[0].getMessage()
    assert error_records == []


def test_mark_watched_survives_concurrent_write_via_real_adapter_retry_loop():
    """The mock-based tests above stub `update_with_retry` to just call the
    mutator once inline -- they never run through the REAL
    SQLiteAdapter.update_with_retry retry/CAS loop, so they can't prove
    no-clobber: a real concurrent writer racing markWatched's mutator could
    silently stomp the other writer's field if the retry loop didn't
    correctly re-read the post-conflict revision before re-applying its own
    change.

    This drives markWatched against a REAL SQLiteAdapter and injects one
    intervening concurrent write on the first `update()` call, mirroring
    test_release_update_status_cas.py::test_update_status_lost_race_then_already_at_target_does_not_notify.
    Unlike that test, the concurrent writer here touches a field markWatched
    never looks at (`tags`) rather than driving the doc to markWatched's own
    target state, so attempt 2 must not short-circuit -- it has to actually
    re-write, proving both convergence (succeeds despite the conflict) and
    no-clobber (the concurrent writer's field is still there afterwards,
    alongside markWatched's own change)."""
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    with tempfile.TemporaryDirectory() as tmp_path:
        db = SQLiteAdapter()
        db.create(str(tmp_path))
        real_update = db.update
        try:
            movie = make_media('movie-1', status='active')
            inserted = db.insert(movie)
            media_id = inserted['_id']

            calls = {'count': 0}

            def flaky_update(data):
                calls['count'] += 1
                if calls['count'] == 1:
                    # A concurrent writer (e.g. another device/tab tagging
                    # this movie) sneaks in between markWatched's read and
                    # its write, changing an unrelated field. This change
                    # must survive markWatched's retry, not get clobbered.
                    concurrent = db.get('id', media_id)
                    concurrent['tags'] = ['concurrent-writer-was-here']
                    real_update(concurrent)
                return real_update(data)

            db.update = flaky_update

            plugin = MediaPlugin.__new__(MediaPlugin)
            with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
                 patch('couchpotato.core.media._base.media.main.fireEvent') as fire_event:
                result = plugin.markWatched(id=media_id, watched_by='Scott')

            db.update = real_update

            assert result['success'] is True
            # Attempt 1's update() call lost the CAS race (the concurrent
            # write bumped the rev first, so markWatched's stale-rev write
            # raised ConflictError); attempt 2 re-read the doc -- picking up
            # the concurrent writer's 'tags' change -- and wrote its own
            # mutation on top of that fresh copy, not the stale one.
            assert calls['count'] == 2

            final = db.get('id', media_id)
            # No-clobber: the concurrent writer's change survived...
            assert final['tags'] == ['concurrent-writer-was-here']
            # ...AND markWatched's own change landed on the very same doc.
            assert final['watched'] is True
            assert final['watched_by'] == 'Scott'
            fire_event.assert_called_once()
        finally:
            db.update = real_update
            db.close()


def test_mark_unwatched_survives_concurrent_write_via_real_adapter_retry_loop():
    """Same proof as test_mark_watched_survives_concurrent_write_via_real_adapter_retry_loop
    but for markUnwatched: drives it against a real SQLiteAdapter with an
    injected concurrent write racing the first update() call, and asserts
    both the concurrent writer's field and markUnwatched's own clearing of
    the watch fields survive together."""
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    with tempfile.TemporaryDirectory() as tmp_path:
        db = SQLiteAdapter()
        db.create(str(tmp_path))
        real_update = db.update
        try:
            movie = make_media('movie-1', watched=True, status='done')
            inserted = db.insert(movie)
            media_id = inserted['_id']

            calls = {'count': 0}

            def flaky_update(data):
                calls['count'] += 1
                if calls['count'] == 1:
                    concurrent = db.get('id', media_id)
                    concurrent['tags'] = ['concurrent-writer-was-here']
                    real_update(concurrent)
                return real_update(data)

            db.update = flaky_update

            plugin = MediaPlugin.__new__(MediaPlugin)
            with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
                 patch('couchpotato.core.media._base.media.main.fireEvent') as fire_event:
                result = plugin.markUnwatched(id=media_id)

            db.update = real_update

            assert result['success'] is True
            assert calls['count'] == 2

            final = db.get('id', media_id)
            # No-clobber: the concurrent writer's change survived...
            assert final['tags'] == ['concurrent-writer-was-here']
            # ...AND markUnwatched's own change landed on the very same doc.
            assert final['watched'] is False
            assert 'watched_at' not in final
            assert 'watched_by' not in final
            assert 'watched_source' not in final
            fire_event.assert_called_once()
        finally:
            db.update = real_update
            db.close()


def test_list_can_filter_watched_movies():
    """media.list accepts watched=True and returns only watched media."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    watched = make_media('movie-a', watched=True)
    unwatched = make_media('movie-b', watched=False)

    with patch('couchpotato.core.media._base.media.main.get_db') as mock_db, \
         patch('couchpotato.core.media._base.media.main.fireEvent') as mock_fire:
        db = MagicMock()
        mock_db.return_value = db
        db.get_many.side_effect = lambda index, key=None: (
            [{'_id': 'movie-a'}, {'_id': 'movie-b'}] if index == 'media_by_type'
            else [{'_id': 'movie-a'}] if index == 'media_watched' and key is True
            else []
        )
        db.all.return_value = [{'_id': 'movie-a'}, {'_id': 'movie-b'}]

        def fire_side_effect(event, *args, **kwargs):
            if event == 'media.get':
                return watched if args[0] == 'movie-a' else unwatched
            return []

        mock_fire.side_effect = fire_side_effect

        total, movies = plugin.list(types=['movie'], watched=True)

    assert total == 1
    assert movies == [watched]


def test_watch_history_lists_watched_movies_newest_first():
    """watchHistory returns watched media sorted by watched_at descending."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    older = make_media('old', watched=True)
    older['watched_at'] = '2026-05-01T10:00:00Z'
    newer = make_media('new', watched=True)
    newer['watched_at'] = '2026-05-09T10:00:00Z'

    with patch.object(plugin, 'list', return_value=(2, [older, newer])) as list_media:
        result = plugin.watchHistory()

    assert result['success'] is True
    assert result['total'] == 2
    assert [movie['_id'] for movie in result['movies']] == ['new', 'old']
    list_media.assert_called_once_with(types=['movie'], watched=True)
