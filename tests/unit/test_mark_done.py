"""Unit tests for media done endpoint behavior."""
import logging
import tempfile
from unittest.mock import MagicMock, patch

from couchpotato.core.db.sqlite_adapter import ConflictError
from couchpotato.core.media._base.media.main import MediaPlugin


def make_update_with_retry(doc):
    """Build a MagicMock side_effect that mimics
    SQLiteAdapter.update_with_retry(mutator, doc_id) by applying the
    mutator to `doc` and returning it -- used to test callers that were
    converted to the CAS retry helper without depending on a real adapter.
    Mirrors the helper of the same name in test_watch_history.py."""
    def _fake(mutator, doc_id, retries=3):
        assert doc_id == doc['_id']
        mutator(doc)
        return doc
    return _fake


def test_mark_done_sets_status_to_done():
    """markDone updates media status via the CAS retry helper and preserves
    its existing {'success': True} return contract (no 'media' key)."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    movie = {'_id': 'movie-1', 'status': 'active'}
    db = MagicMock()
    db.update_with_retry.side_effect = make_update_with_retry(movie)

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db):
        result = plugin.markDone(id='movie-1')

    assert result == {'success': True}
    assert movie['status'] == 'done'
    db.update_with_retry.assert_called_once()
    called_mutator, called_id = db.update_with_retry.call_args.args[:2]
    assert called_id == 'movie-1'
    assert callable(called_mutator)


def test_mark_done_returns_error_when_media_missing():
    """markDone returns the not-found error payload when update_with_retry
    can't find the document (KeyError from SQLiteAdapter.get)."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    db = MagicMock()
    db.update_with_retry.side_effect = KeyError('missing-id')

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db):
        result = plugin.markDone(id='missing-id')

    assert result == {'success': False, 'error': 'Media not found'}


def test_mark_done_conflict_error_after_retries_returns_failure_and_logs_warning(caplog):
    """When update_with_retry exhausts its retries under persistent write
    contention it raises ConflictError -- an expected, distinguishable
    condition, not a code defect. markDone must log it at WARNING (not
    fall through to the generic 'except Exception' ERROR-with-traceback
    branch) while still returning a tailored {'success': False, ...}
    result, exactly mirroring markWatched/markUnwatched's ConflictError
    handling."""
    plugin = MediaPlugin.__new__(MediaPlugin)
    db = MagicMock()
    db.update_with_retry.side_effect = ConflictError('movie-1')

    with patch('couchpotato.core.media._base.media.main.get_db', return_value=db), \
         caplog.at_level(logging.WARNING, logger='couchpotato.core.media._base.media'):
        result = plugin.markDone(id='movie-1')

    assert result['success'] is False
    assert isinstance(result['error'], str) and result['error']

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(warning_records) == 1
    assert 'movie-1' in warning_records[0].getMessage()
    assert error_records == []


def test_mark_done_survives_concurrent_write_via_real_adapter_retry_loop():
    """The mock-based tests above stub `update_with_retry` to just call the
    mutator once inline -- they never run through the REAL
    SQLiteAdapter.update_with_retry retry/CAS loop, so they can't prove
    no-clobber: a real concurrent writer racing markDone's mutator could
    silently stomp the other writer's field if the retry loop didn't
    correctly re-read the post-conflict revision before re-applying its own
    change.

    Mirrors
    test_mark_watched_survives_concurrent_write_via_real_adapter_retry_loop
    in test_watch_history.py: drives markDone against a REAL SQLiteAdapter
    and injects one intervening concurrent write on the first `update()`
    call, touching a field markDone never looks at (`tags`) rather than
    driving the doc to markDone's own target state, so attempt 2 must not
    short-circuit -- it has to actually re-write, proving both convergence
    (succeeds despite the conflict) and no-clobber (the concurrent writer's
    field is still there afterwards, alongside markDone's own status
    change)."""
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    with tempfile.TemporaryDirectory() as tmp_path:
        db = SQLiteAdapter()
        db.create(str(tmp_path))
        real_update = db.update
        try:
            movie = {'_id': 'movie-1', '_t': 'media', 'status': 'active'}
            inserted = db.insert(movie)
            media_id = inserted['_id']

            calls = {'count': 0}

            def flaky_update(data):
                calls['count'] += 1
                if calls['count'] == 1:
                    # A concurrent writer (e.g. another device/tab tagging
                    # this movie) sneaks in between markDone's read and its
                    # write, changing an unrelated field. This change must
                    # survive markDone's retry, not get clobbered.
                    concurrent = db.get('id', media_id)
                    concurrent['tags'] = ['concurrent-writer-was-here']
                    real_update(concurrent)
                return real_update(data)

            db.update = flaky_update

            plugin = MediaPlugin.__new__(MediaPlugin)
            with patch('couchpotato.core.media._base.media.main.get_db', return_value=db):
                result = plugin.markDone(id=media_id)

            db.update = real_update

            assert result == {'success': True}
            # Attempt 1's update() call lost the CAS race (the concurrent
            # write bumped the rev first, so markDone's stale-rev write
            # raised ConflictError); attempt 2 re-read the doc -- picking up
            # the concurrent writer's 'tags' change -- and wrote its own
            # mutation on top of that fresh copy, not the stale one.
            assert calls['count'] == 2

            final = db.get('id', media_id)
            # No-clobber: the concurrent writer's change survived...
            assert final['tags'] == ['concurrent-writer-was-here']
            # ...AND markDone's own change landed on the very same doc.
            assert final['status'] == 'done'
        finally:
            db.update = real_update
            db.close()
