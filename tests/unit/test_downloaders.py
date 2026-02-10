"""Task 18: Downloader tests — Transmission RPC and SABnzbd.

Uses unittest.mock to avoid real network calls.
"""
import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from base64 import b64encode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ===========================================================================
# Transmission RPC
# ===========================================================================

class TestTransmissionRPC:
    """Tests for the TransmissionRPC helper class."""

    def _make_rpc(self):
        """Create TransmissionRPC with mocked urllib."""
        with patch('urllib.request.build_opener'), \
             patch('urllib.request.install_opener'), \
             patch('urllib.request.urlopen') as mock_urlopen:
            from couchpotato.core.downloaders.transmission import TransmissionRPC
            # Don't call __init__ which does get_session
            rpc = TransmissionRPC.__new__(TransmissionRPC)
            rpc.url = 'http://localhost:9091/transmission/rpc'
            rpc.tag = 0
            rpc.session_id = 0
            rpc.session = {}
            return rpc

    def test_add_torrent_uri_success(self):
        rpc = self._make_rpc()
        response = {'result': 'success', 'arguments': {
            'torrent-added': {'hashString': 'abc123', 'id': 1, 'name': 'Test'}
        }}

        with patch('urllib.request.urlopen') as mock_open:
            mock_open.return_value.read.return_value = json.dumps(response).encode()
            result = rpc.add_torrent_uri('magnet:?xt=urn:btih:abc123', {'paused': False})

        assert result['torrent-added']['hashString'] == 'abc123'

    def test_add_torrent_file_success(self):
        rpc = self._make_rpc()
        response = {'result': 'success', 'arguments': {
            'torrent-added': {'hashString': 'def456', 'id': 2, 'name': 'Test2'}
        }}

        with patch('urllib.request.urlopen') as mock_open:
            mock_open.return_value.read.return_value = json.dumps(response).encode()
            result = rpc.add_torrent_file(b64encode(b'torrentdata').decode(), {})

        assert result['torrent-added']['hashString'] == 'def456'

    def test_get_session(self):
        rpc = self._make_rpc()
        response = {'result': 'success', 'arguments': {
            'download-dir': '/downloads', 'incomplete-dir': '/incomplete',
            'incomplete-dir-enabled': True
        }}

        with patch('urllib.request.urlopen') as mock_open:
            mock_open.return_value.read.return_value = json.dumps(response).encode()
            result = rpc.get_session()

        assert result['download-dir'] == '/downloads'

    def test_get_alltorrents(self):
        rpc = self._make_rpc()
        response = {'result': 'success', 'arguments': {
            'torrents': [
                {'id': 1, 'name': 'Movie.mkv', 'hashString': 'abc', 'percentDone': 1.0,
                 'status': 6, 'eta': 0, 'isFinished': True, 'downloadDir': '/dl',
                 'uploadRatio': 2.0, 'isStalled': False, 'files': []}
            ]
        }}

        with patch('urllib.request.urlopen') as mock_open:
            mock_open.return_value.read.return_value = json.dumps(response).encode()
            result = rpc.get_alltorrents({'fields': ['id', 'name']})

        assert len(result['torrents']) == 1
        assert result['torrents'][0]['name'] == 'Movie.mkv'

    def test_remove_torrent(self):
        rpc = self._make_rpc()
        response = {'result': 'success', 'arguments': {}}

        with patch('urllib.request.urlopen') as mock_open:
            mock_open.return_value.read.return_value = json.dumps(response).encode()
            result = rpc.remove_torrent('abc123', True)

        assert result == {}

    def test_request_failure(self):
        rpc = self._make_rpc()
        response = {'result': 'error', 'arguments': {}}

        with patch('urllib.request.urlopen') as mock_open:
            mock_open.return_value.read.return_value = json.dumps(response).encode()
            result = rpc._request({'method': 'test'})

        assert result is False

    def test_connection_error(self):
        rpc = self._make_rpc()
        import urllib.error
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('Connection refused')):
            result = rpc._request({'method': 'session-get'})
        assert result is None

    def test_auth_error_401(self):
        rpc = self._make_rpc()
        import urllib.error
        err = urllib.error.HTTPError('http://localhost', 401, 'Unauthorized', {}, None)
        with patch('urllib.request.urlopen', side_effect=err):
            result = rpc._request({'method': 'session-get'})
        assert result is False

    def test_session_id_update_on_409(self):
        rpc = self._make_rpc()
        import urllib.error
        import io

        # First call: 409 with session ID in body
        body = b'<h1>409: Conflict</h1><p>X-Transmission-Session-Id: newsessionid123</p>'
        err = urllib.error.HTTPError('http://localhost', 409, 'Conflict', {},
                                     io.BytesIO(body))

        call_count = [0]
        original_urlopen = None

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise err
            # Second call succeeds
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({'result': 'success', 'arguments': {}}).encode()
            return mock_resp

        with patch('urllib.request.urlopen', side_effect=side_effect):
            result = rpc._request({'method': 'session-get'})

        assert rpc.session_id == 'newsessionid123'


    def test_session_id_str_in_headers(self):
        """Session ID must be str in headers (regression for int vs str bug)."""
        rpc = self._make_rpc()
        rpc.session_id = 0  # int initially

        response = {'result': 'success', 'arguments': {}}
        with patch('urllib.request.urlopen') as mock_open:
            mock_open.return_value.read.return_value = json.dumps(response).encode()
            rpc._request({'method': 'test'})

        # Check the Request was created with str session_id
        call_args = mock_open.call_args[0][0]
        header_val = call_args.get_header('X-transmission-session-id')
        assert isinstance(header_val, str)


# ===========================================================================
# SABnzbd
# ===========================================================================

class TestSabnzbd:
    """Tests for SABnzbd downloader."""

    def _make_sab(self):
        """Create SABnzbd instance with mocked dependencies."""
        with patch('couchpotato.core.event.addEvent'), \
             patch('couchpotato.api.addApiView', create=True), \
             patch('couchpotato.core._base.downloader.main.addApiView', create=True), \
             patch('couchpotato.core.notifications.base.addApiView', create=True):
            from couchpotato.core.downloaders.sabnzbd import Sabnzbd
            sab = Sabnzbd.__new__(Sabnzbd)
            sab._running = []
            sab._running_lock = __import__('threading').Lock()
            sab._locks = {}
            sab._http_client = None
            sab._needs_shutdown = False
            sab.http_time_between_calls = 0
            sab.ssl_verify = True
            return sab

    def test_call_parses_json_response(self):
        sab = self._make_sab()
        response_data = {'queue': {'slots': [], 'paused': False}}

        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'testapikey'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'urlopen', return_value=json.dumps(response_data).encode()):
            result = sab.call({'mode': 'queue'})

        assert 'slots' in result

    def test_call_error_response(self):
        sab = self._make_sab()
        response_data = {'status': False, 'error': 'API key incorrect'}

        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'wrongkey'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'urlopen', return_value=json.dumps(response_data).encode()):
            result = sab.call({'mode': 'queue'})

        assert result == {}

    def test_call_non_json_mode(self):
        sab = self._make_sab()

        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'key'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'urlopen', return_value=b'ok'):
            result = sab.call({'mode': 'queue', 'name': 'delete'}, use_json=False)

        assert result == b'ok'

    def test_download_addurl(self):
        sab = self._make_sab()
        sab_response = {'mode': 'addurl', 'status': True, 'nzo_ids': ['SABnzbd_nzo_abc123']}

        data = {'name': 'Test.Movie.nzb', 'url': 'http://example.com/nzb/123'}
        media = {'info': {'titles': ['Test Movie']}}

        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'key',
            'category': 'movies', 'priority': '0'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'call', return_value=sab_response), \
             patch.object(sab, 'createNzbName', return_value='Test.Movie.nzb'):
            result = sab.download(data=data, media=media)

        # Returns True for URL-based adds (no filedata)
        assert result is True

    def test_download_addfile_with_filedata(self):
        sab = self._make_sab()
        sab_response = {'mode': 'addfile', 'status': True, 'nzo_ids': ['SABnzbd_nzo_def456']}

        data = {'name': 'Test.Movie.nzb', 'url': 'http://example.com/nzb/456'}
        media = {}
        filedata = b'<nzb>...</nzb>' * 10  # > 50 bytes

        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'key',
            'category': 'movies', 'priority': '0'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'call', return_value=sab_response), \
             patch.object(sab, 'createNzbName', return_value='Test.Movie.nzb'), \
             patch.object(sab, 'createFileName', return_value='Test.Movie.nzb'), \
             patch.object(sab, 'downloadReturnId', return_value='SABnzbd_nzo_def456'):
            result = sab.download(data=data, media=media, filedata=filedata)

        assert result == 'SABnzbd_nzo_def456'

    def test_download_too_small_filedata(self):
        sab = self._make_sab()
        data = {'name': 'Test.nzb'}

        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'key',
            'category': 'movies', 'priority': '0'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'createNzbName', return_value='Test.nzb'), \
             patch.object(sab, 'createFileName', return_value='Test.nzb'):
            result = sab.download(data=data, media={}, filedata=b'small')

        assert result is False

    def test_download_connection_failure(self):
        sab = self._make_sab()
        data = {'name': 'Test.nzb', 'url': 'http://example.com/nzb'}

        from urllib.request import URLError
        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'key',
            'category': 'movies', 'priority': '0'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'call', side_effect=Exception('Connection refused')), \
             patch.object(sab, 'createNzbName', return_value='Test.nzb'):
            result = sab.download(data=data, media={})

        assert result is False

    def test_removeFailed(self):
        sab = self._make_sab()
        release = {'id': 'nzo_abc', 'name': 'Test.Movie'}

        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'key'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'call', return_value='ok'):
            result = sab.removeFailed(release)

        assert result is True

    def test_removeFailed_error(self):
        sab = self._make_sab()
        release = {'id': 'nzo_abc', 'name': 'Test.Movie'}

        with patch.object(sab, 'conf', side_effect=lambda k, **kw: {
            'host': 'localhost:8080', 'ssl': False, 'api_key': 'key'
        }.get(k, kw.get('default', ''))), \
             patch.object(sab, 'call', side_effect=Exception('error')):
            result = sab.removeFailed(release)

        assert result is False
