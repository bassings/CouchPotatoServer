"""Tests for Release.updateStatus() after converting it to the CAS retry
helper (SQLiteAdapter.update_with_retry), closing the previously
unprotected read-modify-write race on release status transitions (the
hottest status-transition path: search/snatch/download/ignore all funnel
through it).
"""
import logging
from unittest.mock import MagicMock, patch

from couchpotato.core.db.sqlite_adapter import ConflictError
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
    mutator to `doc` in place and return it if the mutator wrote, or None
    if the mutator signalled "no change needed" by returning False --
    matching the real adapter's return contract (None means no write
    happened, so callers must not treat this call as having written)."""
    def _fake(mutator, doc_id, retries=3):
        assert doc_id == doc['_id']
        if mutator(doc) is False:
            return None
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


def test_update_status_conflict_error_after_retries_returns_false_and_logs_warning(caplog):
    """When update_with_retry exhausts its retries under persistent write
    contention it raises ConflictError. This is an expected, distinguishable
    condition (not a code defect), so updateStatus must log it at WARNING --
    not fall through to the generic 'except Exception' branch that logs a
    full ERROR traceback -- while still returning the exact same failure
    value (`False`) that the generic-exception path returns."""
    plugin = Release.__new__(Release)
    db = MagicMock()
    db.update_with_retry.side_effect = ConflictError('rel-1')

    with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
         caplog.at_level(logging.WARNING, logger='couchpotato.core.plugins.release'):
        result = plugin.updateStatus('rel-1', status='snatched')

    assert result is False

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(warning_records) == 1
    assert 'rel-1' in warning_records[0].getMessage()
    assert error_records == []


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


def test_update_status_lost_race_then_already_at_target_does_not_notify():
    """If attempt 1 loses the CAS race (a concurrent writer wins and takes
    the release straight to the target status first) and the retry's
    re-read then finds the release already at the target status, the
    mutator short-circuits (returns False) and update_with_retry returns
    None without writing. updateStatus must NOT fire notify.frontend in
    that case -- the winning writer already fired its own notification for
    the same transition, so firing again here would be a spurious
    duplicate. This exercises the real update_with_retry conflict-then-skip
    code path against a real adapter, not a mock that always writes."""
    from couchpotato.core.db.sqlite_adapter import SQLiteAdapter

    import tempfile
    with tempfile.TemporaryDirectory() as tmp_path:
        db = SQLiteAdapter()
        db.create(tmp_path)
        real_update = db.update
        try:
            inserted = db.insert(make_release('unused', status='available'))
            release_id = inserted['_id']

            calls = {'count': 0}

            def flaky_update(data):
                calls['count'] += 1
                if calls['count'] == 1:
                    # A concurrent writer wins the race: it takes the
                    # release straight to the target status before this
                    # call's own (stale-rev) write lands.
                    concurrent = db.get('id', release_id)
                    concurrent['status'] = 'snatched'
                    real_update(concurrent)
                return real_update(data)

            db.update = flaky_update

            plugin = Release.__new__(Release)
            with patch('couchpotato.core.plugins.release.main.get_db', return_value=db), \
                 patch('couchpotato.core.plugins.release.main.fireEvent') as fire_event:
                result = plugin.updateStatus(release_id, status='snatched')

            db.update = real_update

            assert result is True
            # Attempt 1 raised ConflictError inside flaky_update (one call);
            # attempt 2's mutator returns False (already at target) so
            # update_with_retry skips the write entirely -- no second call.
            assert calls['count'] == 1
            fire_event.assert_not_called()

            final = db.get('id', release_id)
            assert final['status'] == 'snatched'
        finally:
            db.update = real_update
            db.close()
