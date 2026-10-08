"""NZBGet's four operations share one connection result contract."""

import socket
import xmlrpc.client
from unittest.mock import MagicMock, patch

import pytest

from couchpotato.core.downloaders.nzbget import NZBGet
import couchpotato.core.downloaders.nzbget as nzbget_module


CALLS = (
    ('download', 'INFO', "CouchPotato connected to drop off b'Movie.nzb'."),
    ('test', 'INFO', 'CouchPotato connected to test connection'),
    ('getAllDownloadStatus', 'DETAIL', 'CouchPotato connected to check status'),
    ('removeFailed', 'INFO', 'CouchPotato connected to delete some history'),
)


def invoke(downloader, method):
    if method == 'download':
        return downloader.download(data={'name': 'Movie', 'url': 'https://example.invalid/movie.nzb'}, filedata=b'nzb')
    if method == 'getAllDownloadStatus':
        return downloader.getAllDownloadStatus([])
    if method == 'removeFailed':
        return downloader.removeFailed({'name': 'Movie', 'id': 'movie-id'})
    return downloader.test()


@pytest.fixture
def downloader():
    instance = NZBGet.__new__(NZBGet)
    instance.getRPC = MagicMock()
    instance.createNzbName = MagicMock(return_value='Movie')
    instance.conf = MagicMock(return_value='Movies')
    rpc = instance.getRPC.return_value
    rpc.version.return_value = '1.0'
    rpc.append.return_value = False
    rpc.status.return_value = {}
    rpc.listgroups.return_value = []
    rpc.postqueue.return_value = []
    rpc.history.return_value = []
    return instance


@pytest.mark.parametrize('method,level,message', CALLS)
@pytest.mark.parametrize('writelog_result', [True, False])
def test_connection_result_preserves_rpc_message_and_log_level(
    downloader, method, level, message, writelog_result,
):
    rpc = downloader.getRPC.return_value
    rpc.writelog.return_value = writelog_result
    with patch.object(nzbget_module.log, 'debug') as debug, \
         patch.object(nzbget_module.log, 'info') as info:
        result = invoke(downloader, method)

    rpc.writelog.assert_called_once_with(level, message)
    if writelog_result:
        debug.assert_any_call('Successfully connected to NZBGet')
    else:
        info.assert_any_call('Successfully connected to NZBGet, but unable to send a message')
    assert result == {
        'download': False,
        'test': True,
        'getAllDownloadStatus': [],
        'removeFailed': True,
    }[method]
    if method == 'download':
        rpc.append.assert_called_once()
    elif method == 'getAllDownloadStatus':
        rpc.status.assert_called_once_with()
    elif method == 'removeFailed':
        rpc.history.assert_called_once_with()


@pytest.mark.parametrize('method,level,message', CALLS)
@pytest.mark.parametrize('failure,expected_log', [
    (socket.error('offline'), 'NZBGet is not responding. Please ensure that NZBGet is running and host setting is correct.'),
    (xmlrpc.client.ProtocolError('https://example.invalid/rpc', 401, 'Denied', {}), 'Password is incorrect.'),
    (xmlrpc.client.ProtocolError('https://nzbuser:nzbpass@example.invalid/rpc', 503, 'Unavailable', {}), 'NZBGet protocol error (HTTP %s)'),
])
def test_connection_failure_stops_operation_and_reports_reason(
    downloader, method, level, message, failure, expected_log,
):
    rpc = downloader.getRPC.return_value
    rpc.writelog.side_effect = failure
    with patch.object(nzbget_module.log, 'error') as error, \
         patch.object(nzbget_module.shutil, 'rmtree') as remove_tree:
        result = invoke(downloader, method)

    rpc.writelog.assert_called_once_with(level, message)
    if isinstance(failure, xmlrpc.client.ProtocolError) and failure.errcode != 401:
        error.assert_called_once_with(expected_log, failure.errcode)
        assert 'nzbuser' not in error.call_args.args[0] % error.call_args.args[1:]
        assert 'nzbpass' not in error.call_args.args[0] % error.call_args.args[1:]
    else:
        error.assert_called_once_with(expected_log)
    assert result == ([] if method == 'getAllDownloadStatus' else False)
    rpc.append.assert_not_called()
    rpc.status.assert_not_called()
    rpc.history.assert_not_called()
    rpc.editqueue.assert_not_called()
    remove_tree.assert_not_called()
