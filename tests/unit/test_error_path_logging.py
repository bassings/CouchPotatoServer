"""Failure responses retain their public shape and useful diagnostic logs."""

from unittest.mock import Mock

import pytest

from couchpotato.core.plugins.category import main as category_main
from couchpotato.core.plugins.profile import main as profile_main
from couchpotato.core.notifications import xbmc as xbmc_main


@pytest.mark.parametrize(
    ('method', 'kwargs', 'expected'),
    [
        ('save', {'label': 'Drama'}, {'success': False, 'category': None}),
        ('saveOrder', {'ids': ['missing']}, {'success': False}),
        ('delete', {'id': 'missing'}, {'success': False}),
        ('removeFromMovie', {'category_id': 'missing'}, None),
    ],
)
def test_category_database_failure_logs_and_returns_failure(monkeypatch, method, kwargs, expected):
    failure = RuntimeError('database unavailable')

    def unavailable():
        raise failure

    logger = Mock()
    monkeypatch.setattr(category_main, 'get_db', unavailable)
    monkeypatch.setattr(category_main, 'log', logger)

    result = getattr(category_main.CategoryPlugin.__new__(category_main.CategoryPlugin), method)(**kwargs)

    assert result == expected
    logger.error.assert_called_once()
    template, detail = logger.error.call_args.args
    assert template == 'Failed: %s'
    assert 'RuntimeError: database unavailable' in detail


@pytest.mark.parametrize(
    ('method', 'kwargs', 'expected'),
    [
        ('save', {'label': 'HD'}, {'success': False}),
        ('saveOrder', {'ids': ['missing']}, {'success': False}),
        ('delete', {'id': 'missing'}, {'success': False}),
        ('fill', {}, False),
    ],
)
def test_profile_database_failure_logs_and_returns_failure(monkeypatch, method, kwargs, expected):
    failure = RuntimeError('database unavailable')

    def unavailable():
        raise failure

    logger = Mock()
    monkeypatch.setattr(profile_main, 'get_db', unavailable)
    monkeypatch.setattr(profile_main, 'log', logger)

    result = getattr(profile_main.ProfilePlugin.__new__(profile_main.ProfilePlugin), method)(**kwargs)

    assert result == expected
    logger.error.assert_called_once()
    template, detail = logger.error.call_args.args
    assert template == 'Failed: %s'
    assert 'RuntimeError: database unavailable' in detail


@pytest.mark.parametrize('path', ['notify', 'version_legacy', 'version_current', 'version_error'])
def test_kodi_error_response_logs_rpc_fields(monkeypatch, path):
    logger = Mock()
    monkeypatch.setattr(xbmc_main, 'log', logger)
    kodi = xbmc_main.XBMC.__new__(xbmc_main.XBMC)
    kodi.default_title = 'Test'
    kodi.use_json_notifications = {'host': True}
    kodi.conf = Mock(return_value='host')
    kodi.getNotificationImage = Mock(return_value='')
    error = {'id': 7, 'error': {'message': 'invalid request', 'code': -32600}}

    if path == 'notify':
        kodi.request = Mock(return_value=[error])
        result = kodi.notify(message='Hello')
        assert result is False
    else:
        if path == 'version_legacy':
            version = {'result': {'version': 2}}
            kodi.request = Mock(return_value=[version])
            kodi.notifyXBMCnoJSON = Mock(return_value=[error])
        elif path == 'version_current':
            version = {'result': {'version': {'major': 6, 'minor': 0, 'patch': 0}}}
            kodi.request = Mock(side_effect=[[version], [error]])
        else:
            kodi.request = Mock(return_value=[error])
        result = kodi.getXBMCJSONversion('host', message='Hello')
        assert result is False

    logger.error.assert_called_once_with('Kodi error; %s: %s (%s)', 7, 'invalid request', -32600)


@pytest.mark.parametrize('failure_stage', ['movie_lookup', 'quality_cleanup'])
def test_profile_default_repair_logs_failure_and_continues(monkeypatch, failure_stage):
    logger = Mock()
    database = Mock()
    database.count.return_value = 1
    monkeypatch.setattr(profile_main, 'get_db', Mock(return_value=database))
    monkeypatch.setattr(profile_main, 'log', logger)
    plugin = profile_main.ProfilePlugin.__new__(profile_main.ProfilePlugin)

    if failure_stage == 'movie_lookup':
        monkeypatch.setattr(profile_main, 'fireEvent', Mock(side_effect=RuntimeError('movie lookup unavailable')))
        plugin.all = Mock(return_value=[])
    else:
        monkeypatch.setattr(profile_main, 'fireEvent', Mock(return_value=[]))
        plugin.all = Mock(side_effect=[
            [{'_id': 'default'}],
            [{'_id': 'default', 'qualities': ['']}],
        ])
        database.get.side_effect = RuntimeError('profile lookup unavailable')

    assert plugin.forceDefaults() is None
    logger.error.assert_called_once()
    template, detail = logger.error.call_args.args
    assert template == 'Failed: %s'
    assert 'RuntimeError:' in detail
