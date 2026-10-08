"""Log clearing must report partial failure without exposing private paths."""

from unittest import mock

from couchpotato.core.plugins.log.main import Logging


def test_clear_reports_rotated_file_failure_without_path_leak(tmp_path, caplog):
    log_path = tmp_path / 'private-person-log'
    log_path.write_text('current')
    rotated = tmp_path / 'private-person-log.1'
    rotated.write_text('previous')
    plugin = Logging()

    with mock.patch('couchpotato.core.plugins.log.main.Env.get', return_value=str(log_path)):
        with mock.patch('couchpotato.core.plugins.log.main.os.remove', side_effect=PermissionError(str(rotated))):
            result = plugin.clear()

    assert result == {'success': False, 'error': 'Unable to clear all logs'}
    assert log_path.read_text() == ''
    assert rotated.read_text() == 'previous'
    assert str(rotated) not in caplog.text
    assert str(log_path) not in caplog.text


def test_clear_reports_current_file_failure_and_keeps_rotated_cleanup(tmp_path, caplog):
    log_path = tmp_path / 'private-person-log'
    log_path.write_text('current')
    rotated = tmp_path / 'private-person-log.1'
    rotated.write_text('previous')
    plugin = Logging()

    with mock.patch('couchpotato.core.plugins.log.main.Env.get', return_value=str(log_path)):
        with mock.patch('couchpotato.core.plugins.log.main.open', side_effect=PermissionError(str(log_path)), create=True):
            result = plugin.clear()

    assert result == {'success': False, 'error': 'Unable to clear all logs'}
    assert log_path.read_text() == 'current'
    assert not rotated.exists()
    assert str(log_path) not in caplog.text


def test_clear_succeeds_when_logs_are_absent_or_removed(tmp_path):
    log_path = tmp_path / 'app.log'
    plugin = Logging()
    with mock.patch('couchpotato.core.plugins.log.main.Env.get', return_value=str(log_path)):
        assert plugin.clear() == {'success': True}
        log_path.write_text('current')
        (tmp_path / 'app.log.1').write_text('previous')
        assert plugin.clear() == {'success': True}
    assert log_path.read_text() == ''
    assert not (tmp_path / 'app.log.1').exists()
