"""Unit tests for media done endpoint behavior."""
import logging
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
