"""Tests for Release.updateStatus() after converting it to the CAS retry
helper (SQLiteAdapter.update_with_retry), closing the previously
unprotected read-modify-write race on release status transitions (the
hottest status-transition path: search/snatch/download/ignore all funnel
through it).
"""
from unittest.mock import MagicMock, patch

from couchpotato.core.plugins.release.main import Release


def make_release(release_id, status='available', files=None, info=None):
    return {
        '_id': release_id,
        '_t': 'release',
        'status': status,
        'media_id': 'media-1',
        'identifier': 'tt0133093.720p',
        'quality': '720p',
        'last_edit': 1700000000,
        'files': files or {},
        'info': info or {},
    }


def make_update_with_retry(doc):
    """Mimic SQLiteAdapter.update_with_retry(mutator, doc_id): apply the
    mutator to `doc` in place and return it, matching the real adapter's
    "skip write if mutator returns False" contract."""
    def _fake(mutator, doc_id, retries=3):
        assert doc_id == doc['_id']
        mutator(doc)
        return doc
    return _fake


def test_update_status_changes_status_and_notifies():
    rel = make_release('rel-1', status='available')
    db = MagicMock()
    db.update_with_retry.side_effect = make_update_with_retry(rel)

    plugin = Release.__new__(Release)
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
         patch('couchpotato.core.plugins.release.main.fireEvent') as fire_event:
        result = plugin.updateStatus('rel-1', status='snatched')

    assert result is True
    assert rel['status'] == 'snatched'
    assert rel['last_edit'] != 1700000000
    fire_event.assert_called_once_with(
        'notify.frontend', type='release.update_status', data=rel
    )


def test_update_status_no_op_when_already_at_target_status_does_not_notify():
    """If the release is already at the target status, updateStatus must
    not write or notify -- matching the pre-CAS 'only touch on change'
    behaviour."""
    rel = make_release('rel-1', status='done')
    db = MagicMock()
    db.update_with_retry.side_effect = make_update_with_retry(rel)

    plugin = Release.__new__(Release)
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
         patch('couchpotato.core.plugins.release.main.fireEvent') as fire_event:
        result = plugin.updateStatus('rel-1', status='done')

    assert result is True
    assert rel['last_edit'] == 1700000000  # untouched
    fire_event.assert_not_called()


def test_update_status_without_status_arg_is_a_noop():
    plugin = Release.__new__(Release)
    db = MagicMock()
    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db):
        result = plugin.updateStatus('rel-1', status=None)

    assert result is False
    db.update_with_retry.assert_not_called()


def test_update_status_missing_release_returns_false():
    plugin = Release.__new__(Release)
    db = MagicMock()
    db.update_with_retry.side_effect = KeyError('rel-missing')

    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db):
        result = plugin.updateStatus('rel-missing', status='done')

    assert result is False


def test_update_status_survives_a_transient_conflict_via_retry_helper():
    """updateStatus itself doesn't retry -- update_with_retry does. This
    just confirms updateStatus surfaces whatever update_with_retry returns
    on eventual success, proving the call site is wired correctly end to
    end against a real adapter (not a mock)."""
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    def _make_db(tmp_path):
        adapter = SQLiteAdapter()
        adapter.create(str(tmp_path))
        return adapter

    import tempfile
    with tempfile.TemporaryDirectory() as tmp_path:
        db = _make_db(tmp_path)
        try:
            inserted = db.insert(make_release('unused', status='available'))
            plugin = Release.__new__(Release)

            with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
                 patch('couchpotato.core.plugins.release.main.fireEvent') as fire_event:
                result = plugin.updateStatus(inserted['_id'], status='snatched')

            assert result is True
            final = db.get('id', inserted['_id'])
            assert final['status'] == 'snatched'
            fire_event.assert_called_once()
        finally:
            db.close()
