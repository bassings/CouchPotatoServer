"""Task 18: Downloader tests — Transmission RPC and SABnzbd.

VENDORED-02: Put.io downloader tests (maintained putiopy client).

Uses unittest.mock to avoid real network calls.
"""
import datetime
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
        import importlib
        api_module = importlib.import_module('couchpotato.api')
        with patch('couchpotato.core.event.addEvent'), \
             patch.object(api_module, 'addApiView'), \
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


# ===========================================================================
# Put.io (VENDORED-02: maintained putiopy client, replacing vendored pio/tus)
# ===========================================================================

class TestPutIO:
    """Tests for the PutIO downloader, mocking putiopy.Client so no network
    calls are made and no real put.io credentials are needed.
    """

    def _make_putio(self, conf_values=None):
        """Create a PutIO instance without running __init__.

        Using ``PutIO.__new__(PutIO)`` skips ``__init__`` entirely, so the
        real ``addApiView`` / ``addEvent`` registrations it would perform
        against the running app never happen — no need to patch them here.
        """
        conf_values = conf_values or {}
        from couchpotato.core.downloaders.putio.main import PutIO
        putio = PutIO.__new__(PutIO)
        putio.downloading_list = []

        def conf(key, **kw):
            return conf_values.get(key, kw.get('default', ''))

        putio.conf = conf
        return putio

    @staticmethod
    def _resource(**attrs):
        """Build a MagicMock standing in for a putiopy _BaseResource (File or
        Transfer). Passing `name=` to MagicMock()'s constructor configures
        the mock's own repr instead of a `.name` attribute, so attributes
        are set afterwards instead."""
        mock = MagicMock()
        for key, value in attrs.items():
            setattr(mock, key, value)
        return mock

    # -- Client construction -------------------------------------------------

    def test_download_constructs_client_with_oauth_token(self):
        putio = self._make_putio({'oauth_token': 'my-token', 'folder': 0})
        from couchpotato.core.downloaders.putio import main as putio_main

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.Transfer.add_url.return_value = MagicMock(id=555)

            putio.download(data={'name': 'Some.Movie', 'url': 'magnet:?xt=urn:btih:abc'})

        mock_client_cls.assert_called_once_with('my-token')

    # -- download() -> Transfer.add_url --------------------------------------

    def test_download_sends_transfer_add_url_and_returns_download_id(self):
        putio = self._make_putio({'oauth_token': 'tok', 'folder': 0, 'download': False})
        from couchpotato.core.downloaders.putio import main as putio_main

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.Transfer.add_url.return_value = MagicMock(id=1234)

            result = putio.download(data={'name': 'Some.Movie', 'url': 'http://example.com/x.torrent'})

        mock_client.Transfer.add_url.assert_called_once_with(
            'http://example.com/x.torrent', callback_url=None, parent_id=0
        )
        assert result['id'] == 1234
        assert result['downloader'] == 'PutIO'

    def test_download_builds_callback_url_when_download_enabled(self):
        putio = self._make_putio({
            'oauth_token': 'tok', 'folder': 0, 'download': True,
            'https': False, 'callback_host': 'example.com:5050',
        })
        from couchpotato.core.downloaders.putio import main as putio_main

        with patch.object(putio_main.pio, 'Client') as mock_client_cls, \
             patch.object(putio_main.Env, 'get', return_value='/api/somekey/'):
            mock_client = mock_client_cls.return_value
            mock_client.Transfer.add_url.return_value = MagicMock(id=42)

            putio.download(data={'name': 'Some.Movie', 'url': 'http://example.com/x.torrent'})

        # Assert the FULL callback URL with exact equality rather than a
        # substring/startswith check: the latter trips CodeQL's "Incomplete URL
        # substring sanitization" query (it can't tell a test assertion from a
        # security check) and is a weaker assertion anyway. Expected value is
        # deterministic from the mocked inputs:
        #   pre ('http://', since https=False)
        #   + callback_host ('example.com:5050')
        #   + '%sdownloader.putio.getfrom/' % Env.get(...)  (Env.get -> '/api/somekey/')
        _, kwargs = mock_client.Transfer.add_url.call_args
        assert kwargs['callback_url'] == (
            'http://example.com:5050/api/somekey/downloader.putio.getfrom/'
        )

    # -- test() ---------------------------------------------------------------

    def test_test_returns_true_when_file_list_succeeds(self):
        putio = self._make_putio({'oauth_token': 'tok'})
        from couchpotato.core.downloaders.putio import main as putio_main

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.File.list.return_value = [MagicMock()]

            result = putio.test()

        assert result is True

    def test_test_returns_false_on_client_error(self):
        putio = self._make_putio({'oauth_token': 'bad-token'})
        from couchpotato.core.downloaders.putio import main as putio_main

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.File.list.side_effect = Exception('401 Unauthorized')

            result = putio.test()

        assert result is False

    # -- getAllDownloadStatus() -> Transfer.list() -----------------------------

    def test_getAllDownloadStatus_marks_completed_when_not_downloading(self):
        putio = self._make_putio({'oauth_token': 'tok', 'download': False})
        from couchpotato.core.downloaders.putio import main as putio_main

        transfer = self._resource(id=99, name='Some.Movie', status='COMPLETED',
                                   estimated_time=0, file_id=1, finished_at=None)

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client_cls.return_value.Transfer.list.return_value = [transfer]

            result = putio.getAllDownloadStatus([99])

        assert len(result) == 1
        assert result[0]['id'] == 99
        assert result[0]['status'] == 'completed'
        assert result[0]['timeleft'] == 0

    def test_getAllDownloadStatus_ignores_transfers_not_in_ids(self):
        putio = self._make_putio({'oauth_token': 'tok', 'download': False})
        from couchpotato.core.downloaders.putio import main as putio_main

        transfer = self._resource(id=1, name='Other', status='COMPLETED', estimated_time=0)

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client_cls.return_value.Transfer.list.return_value = [transfer]

            result = putio.getAllDownloadStatus([999])

        assert len(result) == 0

    def test_getAllDownloadStatus_parses_finished_at_as_raw_string(self):
        """putiopy's _BaseResource only rewrites `created_at`; `finished_at`
        stays a raw API string, so CP's own datetime.strptime parsing must
        keep working unmodified against the new client."""
        putio = self._make_putio({'oauth_token': 'tok', 'download': True})
        from couchpotato.core.downloaders.putio import main as putio_main

        # finished 10 minutes ago -> past the 5 minute race-condition window
        finished = (datetime.datetime.utcnow() - datetime.timedelta(minutes=10))
        finished_at_str = finished.strftime('%Y-%m-%dT%H:%M:%S')

        transfer = self._resource(id=7, name='Some.Movie', status='COMPLETED',
                                   estimated_time=0, file_id=55, finished_at=finished_at_str)

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client_cls.return_value.Transfer.list.return_value = [transfer]

            result = putio.getAllDownloadStatus([7])

        assert result[0]['status'] == 'completed'

    def test_getAllDownloadStatus_busy_within_race_condition_window(self):
        putio = self._make_putio({'oauth_token': 'tok', 'download': True})
        from couchpotato.core.downloaders.putio import main as putio_main

        # finished 10 seconds ago -> still inside the 5 minute window
        finished = (datetime.datetime.utcnow() - datetime.timedelta(seconds=10))
        finished_at_str = finished.strftime('%Y-%m-%dT%H:%M:%S')

        transfer = self._resource(id=8, name='Some.Movie', status='COMPLETED',
                                   estimated_time=0, file_id=56, finished_at=finished_at_str)

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client_cls.return_value.Transfer.list.return_value = [transfer]

            result = putio.getAllDownloadStatus([8])

        assert result[0]['status'] == 'busy'

    def test_getAllDownloadStatus_busy_when_still_transferring(self):
        putio = self._make_putio({'oauth_token': 'tok', 'download': False})
        from couchpotato.core.downloaders.putio import main as putio_main

        transfer = self._resource(id=3, name='Some.Movie', status='DOWNLOADING', estimated_time=120)

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client_cls.return_value.Transfer.list.return_value = [transfer]

            result = putio.getAllDownloadStatus([3])

        assert result[0]['status'] == 'busy'
        assert result[0]['timeleft'] == 120

    # -- putioDownloader() -> File.list()/File.download() ---------------------

    def test_putioDownloader_downloads_matching_file(self):
        putio = self._make_putio({
            'oauth_token': 'tok', 'folder': 0,
            'download_dir': '/downloads', 'delete_file': True,
        })
        putio.downloading_list = ['123']
        from couchpotato.core.downloaders.putio import main as putio_main

        matching_file = MagicMock(id=123)
        other_file = MagicMock(id=456)

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.File.list.return_value = [other_file, matching_file]

            result = putio.putioDownloader('123')

        mock_client.File.download.assert_called_once_with(
            matching_file, dest='/downloads', delete_after_download=True
        )
        assert result is True
        assert '123' not in putio.downloading_list

    def test_putioDownloader_skips_non_matching_files(self):
        putio = self._make_putio({
            'oauth_token': 'tok', 'folder': 0,
            'download_dir': '/downloads', 'delete_file': False,
        })
        putio.downloading_list = ['123']
        from couchpotato.core.downloaders.putio import main as putio_main

        other_file = MagicMock(id=456)

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.File.list.return_value = [other_file]

            putio.putioDownloader('123')

        mock_client.File.download.assert_not_called()

    def test_putioDownloader_uses_generous_timeout_for_streaming_download(self):
        """The streaming File.download() reuses the Client's timeout for each
        chunk read, so putiopy's 5s default would raise ReadTimeout on a >5s
        put.io-side stall mid-download. putioDownloader() must build its client
        with a generous per-chunk-read timeout (30s), unlike the light metadata
        calls elsewhere which keep the default.
        """
        putio = self._make_putio({
            'oauth_token': 'tok', 'folder': 0,
            'download_dir': '/downloads', 'delete_file': False,
        })
        putio.downloading_list = ['123']
        from couchpotato.core.downloaders.putio import main as putio_main

        matching_file = MagicMock(id=123)

        with patch.object(putio_main.pio, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.File.list.return_value = [matching_file]

            putio.putioDownloader('123')

        mock_client_cls.assert_called_once_with('tok', timeout=30)

    # -- convertFolder()/recursionFolder() -------------------------------------

    def test_convertFolder_returns_zero_for_root(self):
        putio = self._make_putio()
        assert putio.convertFolder(MagicMock(), 0) == 0

    def test_recursionFolder_finds_matching_named_folder(self):
        putio = self._make_putio()

        root_dir = self._resource(id=10, name='Movies', content_type='application/x-directory')
        plain_file = self._resource(id=11, name='readme.txt', content_type='text/plain')
        client = MagicMock()
        client.File.list.return_value = [plain_file, root_dir]

        result = putio.recursionFolder(client, folder=0, tfolder='Movies')

        assert result == 10

    def test_recursionFolder_descends_into_subfolders(self):
        """The target folder lives one level down, so a first-level name-match
        can't find it — only the recursive ``recursionFolder(client, f.id, ...)``
        descent does. The mock returns a *different* listing depending on the
        folder id it is called with, so this genuinely exercises the recursion
        rather than re-matching the same top-level result.
        """
        putio = self._make_putio()

        top_dir = self._resource(id=10, name='Media', content_type='application/x-directory')
        target_dir = self._resource(id=20, name='Movies', content_type='application/x-directory')
        stray_file = self._resource(id=30, name='notes.txt', content_type='text/plain')

        listings = {
            0: [stray_file, top_dir],   # root: no 'Movies' here, only 'Media'/
            10: [target_dir],           # inside 'Media/': the 'Movies' target
            20: [],                     # inside 'Movies/': nothing further
        }

        client = MagicMock()
        client.File.list.side_effect = lambda folder: listings[folder]

        result = putio.recursionFolder(client, folder=0, tfolder='Movies')

        assert result == 20
        # Proof the recursion actually descended: File.list was called for the
        # root AND for the first-level 'Media' folder (id 10).
        called_folders = [call.args[0] for call in client.File.list.call_args_list]
        assert 0 in called_folders
        assert 10 in called_folders

    # -- putiopy signature guard ----------------------------------------------

    def test_putiopy_signatures_match_what_cp_passes(self):
        """Guard against silent breakage when putiopy is upgraded.

        Every other TestPutIO test patches ``pio.Client`` wholesale, so none
        would notice if a future ``putio.py`` release renamed or dropped a
        keyword CP actually passes. This test imports the REAL putiopy and
        checks (via ``inspect.signature``) that each parameter CP relies on
        still exists, turning a would-be production breakage into a caught CI
        failure. Skips cleanly if putiopy isn't installed.
        """
        putiopy = pytest.importorskip('putiopy')
        import inspect

        # Client.__init__ must accept `timeout` — putioDownloader() passes
        # timeout=30 for the streaming download.
        client_params = inspect.signature(putiopy.Client.__init__).parameters
        assert 'timeout' in client_params, (
            'putiopy.Client.__init__ lost the `timeout` kwarg CP depends on: '
            f'{list(client_params)}'
        )

        # The file-download method CP calls as `client.File.download(f, dest=...,
        # delete_after_download=...)` (bound off the `_File` resource class in
        # 8.8.0) must still accept `dest` and `delete_after_download`.
        file_cls = getattr(putiopy, '_File', None) or getattr(putiopy, 'File', None)
        assert file_cls is not None and hasattr(file_cls, 'download'), (
            'putiopy no longer exposes a File resource class with a download() '
            'method'
        )
        download_params = inspect.signature(file_cls.download).parameters
        for kw in ('dest', 'delete_after_download'):
            assert kw in download_params, (
                f'putiopy File.download lost the `{kw}` kwarg CP depends on: '
                f'{list(download_params)}'
            )

        # Transfer.add_url, called as
        # `client.Transfer.add_url(url, callback_url=..., parent_id=...)`.
        transfer_cls = getattr(putiopy, '_Transfer', None) or getattr(putiopy, 'Transfer', None)
        assert transfer_cls is not None and hasattr(transfer_cls, 'add_url'), (
            'putiopy no longer exposes a Transfer resource class with an '
            'add_url() method'
        )
        add_url_params = inspect.signature(transfer_cls.add_url).parameters
        for kw in ('callback_url', 'parent_id'):
            assert kw in add_url_params, (
                f'putiopy Transfer.add_url lost the `{kw}` kwarg CP depends on: '
                f'{list(add_url_params)}'
            )


# ===========================================================================
# qBittorrent (VENDORED-03: replaced the vendored WebUI-v1 client with the
# PyPI qbittorrent-api package, which talks the modern WebUI v2 API)
# ===========================================================================

class TestQBittorrent:
    """Tests for the qBittorrent downloader, mocking qbittorrentapi.Client so
    no network calls are made and no real qBittorrent instance is needed.
    """

    def _make_qbittorrent(self, conf_values=None):
        """Create a qBittorrent instance without running __init__.

        Using ``qBittorrent.__new__(qBittorrent)`` skips ``__init__``
        entirely, so the real ``addApiView``/``addEvent`` registrations it
        would perform against the running app never happen — no need to
        patch them here.
        """
        conf_values = conf_values or {}
        from couchpotato.core.downloaders.qbittorrent_ import qBittorrent
        qbt = qBittorrent.__new__(qBittorrent)
        qbt.qb = None

        def conf(key, **kw):
            return conf_values.get(key, kw.get('default', ''))

        qbt.conf = conf
        return qbt

    # -- connect() / client construction --------------------------------------

    def test_connect_constructs_client_with_host_username_password(self):
        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'username': 'admin', 'password': 'secret',
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            result = qbt.connect()

        assert result is True
        mock_client_cls.assert_called_once_with(
            host='http://localhost:8080/', username='admin', password='secret',
        )

    def test_connect_passes_none_for_missing_credentials(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = True

            qbt.connect()

        mock_client_cls.assert_called_once_with(
            host='http://localhost:8080/', username=None, password=None,
        )

    def test_connect_reuses_client_and_skips_relogin_when_session_still_valid(self):
        """Improvement (b): the client is created once and its session reused
        instead of reconnecting (logging in) on every operation — modern
        qBittorrent bans an IP after repeated failed logins."""
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            assert qbt.connect() is True
            assert qbt.connect() is True
            assert qbt.connect() is True

        mock_client_cls.assert_called_once()
        mock_client.auth_log_in.assert_not_called()

    def test_connect_logs_in_when_session_not_valid(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = False

            result = qbt.connect()

        assert result is True
        mock_client.auth_log_in.assert_called_once()

    def test_connect_returns_false_when_login_fails(self):
        """Uses qbittorrent-api's TYPED exception (LoginFailed) rather than a
        falsy return value or a bare except."""
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = False
            mock_client.auth_log_in.side_effect = qbt_main.qbittorrentapi.LoginFailed('bad creds')

            result = qbt.connect()

        assert result is False

    def test_connect_returns_false_on_forbidden_banned_ip(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = False
            mock_client.auth_log_in.side_effect = qbt_main.qbittorrentapi.Forbidden403Error('banned')

            result = qbt.connect()

        assert result is False

    def test_connect_returns_false_when_session_check_raises_api_error(self):
        """is_logged_in is a live authenticated call, so a transient blip
        (connection/timeout/SSL, all APIError subclasses) at re-validation
        must return False cleanly rather than escape as an unhandled
        traceback — same guarantee as a failed auth_log_in."""
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            type(mock_client).is_logged_in = PropertyMock(
                side_effect = qbt_main.qbittorrentapi.APIConnectionError('unreachable'))

            result = qbt.connect()

        assert result is False
        # never reached login — the guard caught the session-check failure
        mock_client.auth_log_in.assert_not_called()

    def test_test_logs_out_old_session_and_builds_fresh_client(self):
        """test() always reflects the current settings, so it forces a brand
        new client rather than reusing whatever was connected before."""
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        old_client = MagicMock()
        qbt.qb = old_client

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            new_client = mock_client_cls.return_value
            new_client.is_logged_in = True

            result = qbt.test()

        assert result is True
        old_client.auth_log_out.assert_called_once()
        mock_client_cls.assert_called_once()
        assert qbt.qb is new_client

    def test_test_tolerates_logout_failure_on_already_dead_session(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        old_client = MagicMock()
        old_client.auth_log_out.side_effect = qbt_main.qbittorrentapi.APIConnectionError('gone')
        qbt.qb = old_client

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = True

            result = qbt.test()

        assert result is True

    # -- download() -> torrents_add() -----------------------------------------

    def test_download_magnet_sends_category_and_honours_paused_setting(self):
        """Improvement (a): the 'paused' setting is honoured via is_stopped=
        (the old v1 vendored client couldn't do this at all)."""
        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': True,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_add.return_value = 'Ok.'

            result = qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet',
                'url': 'magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD',
            })

        mock_client.torrents_add.assert_called_once_with(
            urls='magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD',
            category='couchpotato', is_stopped=True,
        )
        assert result['id'] == 'AABBCCDDEEFF00112233445566778899AABBCCDD'
        assert result['downloader'] == 'qBittorrent'

    def test_download_magnet_defaults_to_started_when_not_paused(self):
        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': False,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_add.return_value = 'Ok.'

            qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet',
                'url': 'magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD',
            })

        _, kwargs = mock_client.torrents_add.call_args
        assert kwargs['is_stopped'] is False

    def test_download_magnet_without_info_hash_returns_false_with_specific_error(self):
        """A magnet URL with no urn:btih: info-hash must fail with a specific,
        logged error and a falsy return -- NOT an uncaught IndexError from
        re.findall(...)[0]. The hash is extracted before the API-error try
        block, so this path never reaches (or is masked by) torrents_add()."""
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls, \
             patch.object(qbt_main.log, 'error') as mock_log_error:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            # No IndexError should escape -- a bad magnet is a handled failure.
            result = qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet',
                'url': 'magnet:?xt=urn:sha1:notabtihhash&dn=Some.Movie',
            })

        assert result is False
        # The torrent is never sent to qBittorrent when the hash can't be read.
        mock_client.torrents_add.assert_not_called()
        # The specific no-info-hash message is logged (not a generic traceback).
        assert mock_log_error.call_count == 1
        assert 'no info-hash in magnet URL' in mock_log_error.call_args[0][0]

    def test_download_magnet_returns_false_on_api_error(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_add.side_effect = qbt_main.qbittorrentapi.Conflict409Error('already added')

            result = qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet',
                'url': 'magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD',
            })

        assert result is False

    def test_download_file_sends_torrent_files_and_computes_info_hash(self):
        """A torrent-FILE add uses a REAL bencodepy round-trip: build a
        torrent dict, bencode() it to bytes, feed it as filedata, and assert
        the add is sent and the info-hash is the sha1 of the re-bencoded info
        dict.

        bdecode/bencode are NOT mocked here on purpose: bencodepy.decode()
        returns a dict keyed by BYTES (b'info'), so accessing it with the
        string key 'info' raises KeyError on every real .torrent file. This
        test fails against `bdecode(filedata)["info"]` and passes against
        `bdecode(filedata)[b"info"]`.
        """
        from bencodepy import encode as bencode, decode as bdecode
        from hashlib import sha1

        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': False,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        info = {
            b'name': b'Some.Movie.mkv',
            b'piece length': 16384,
            b'length': 12345,
            b'pieces': b'\x01' * 20,
        }
        filedata = bencode({
            b'announce': b'http://tracker.example.com/announce',
            b'info': info,
        })

        # The info-hash CP must compute: sha1 of the re-bencoded info dict.
        expected_hash = sha1(bencode(bdecode(filedata)[b'info'])).hexdigest()

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            result = qbt.download(data={'name': 'Some.Movie', 'protocol': 'torrent'}, filedata=filedata)

        mock_client.torrents_add.assert_called_once_with(
            torrent_files=filedata, category='couchpotato', is_stopped=False,
        )
        assert result['downloader'] == 'qBittorrent'
        assert result['id'] == expected_hash

    def test_download_corrupt_torrent_file_returns_false_with_specific_error(self):
        """A genuinely corrupt/malformed .torrent (invalid bencoding) must fail
        with a specific, logged error and a falsy return — NOT an uncaught
        BencodeDecodingError bubbling up to fireEvent's blanket handler. The
        decode/hash-computation block is guarded, mirroring the magnet no-hash
        guard, so torrents_add() is never reached."""
        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': False,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls, \
             patch.object(qbt_main.log, 'error') as mock_log_error:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            # No BencodeDecodingError should escape — a corrupt file is a
            # handled failure.
            result = qbt.download(
                data={'name': 'Some.Movie', 'protocol': 'torrent'},
                filedata=b'not-a-torrent',
            )

        assert result is False
        # The torrent is never sent to qBittorrent when the file can't be decoded.
        mock_client.torrents_add.assert_not_called()
        # The specific corrupt-file message is logged (not a generic traceback).
        assert mock_log_error.call_count == 1
        assert 'Invalid/corrupt torrent file' in mock_log_error.call_args[0][0]

    def test_download_torrent_file_missing_info_dict_returns_false(self):
        """A validly-bencoded file that lacks the b'info' key raises KeyError
        in the decode block; the guard must turn that into a clean False +
        specific log rather than an uncaught KeyError."""
        from bencodepy import encode as bencode

        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': False,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        # Valid bencoding, but no b'info' key.
        filedata = bencode({b'announce': b'http://tracker.example.com/announce'})

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls, \
             patch.object(qbt_main.log, 'error') as mock_log_error:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            result = qbt.download(data={'name': 'Some.Movie', 'protocol': 'torrent'}, filedata=filedata)

        assert result is False
        mock_client.torrents_add.assert_not_called()
        assert mock_log_error.call_count == 1
        assert 'Invalid/corrupt torrent file' in mock_log_error.call_args[0][0]

    def test_download_file_without_filedata_returns_false(self):
        # download() calls self.connect() BEFORE checking filedata, so a
        # missing filedata fails AFTER connecting, not before — the missing
        # data is caught by the `not filedata and protocol == 'torrent'` guard.
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = True

            result = qbt.download(data={'name': 'Some.Movie', 'protocol': 'torrent'}, filedata=None)

        assert result is False
        # never attempted the add — bailed on the missing-filedata guard
        mock_client_cls.return_value.torrents_add.assert_not_called()

    def test_download_returns_false_when_connect_fails(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = False
            mock_client_cls.return_value.auth_log_in.side_effect = qbt_main.qbittorrentapi.LoginFailed()

            result = qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet', 'url': 'magnet:?xt=urn:btih:aa',
            })

        assert result is False

    # -- getTorrentStatus() ----------------------------------------------------

    @pytest.mark.parametrize('state', [
        'uploading', 'queuedUP', 'stalledUP', 'stoppedUP', 'forcedUP',
    ])
    def test_getTorrentStatus_seeding_states(self, state):
        """stoppedUP/forcedUP must be included: qBittorrent 5 (Web API
        v2.11.0) renamed pausedUP -> stoppedUP."""
        qbt = self._make_qbittorrent()
        assert qbt.getTorrentStatus({'state': state, 'progress': 1}) == 'seeding'

    def test_getTorrentStatus_completed_when_fully_downloaded(self):
        qbt = self._make_qbittorrent()
        assert qbt.getTorrentStatus({'state': 'downloading', 'progress': 1}) == 'completed'

    def test_getTorrentStatus_busy_otherwise(self):
        qbt = self._make_qbittorrent()
        assert qbt.getTorrentStatus({'state': 'downloading', 'progress': 0.4}) == 'busy'

    # -- getAllDownloadStatus() -> torrents_info()/torrents_files() ----------

    def test_getAllDownloadStatus_single_file_torrent(self, tmp_path):
        qbt = self._make_qbittorrent({'label': 'couchpotato'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        save_path = str(tmp_path)
        (tmp_path / 'Movie.mkv').write_bytes(b'data')

        torrent = {
            'hash': 'ABC123', 'name': 'Movie.mkv', 'state': 'uploading',
            'progress': 1, 'ratio': 1.5, 'eta': 0, 'save_path': save_path,
        }

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [torrent]
            mock_client.torrents_files.return_value = [{'name': 'Movie.mkv'}]

            result = qbt.getAllDownloadStatus(['ABC123'])

        mock_client.torrents_info.assert_called_once_with(status_filter='all', category='couchpotato')
        assert len(result) == 1
        assert result[0]['id'] == 'ABC123'
        assert result[0]['status'] == 'seeding'
        assert result[0]['seed_ratio'] == 1.5
        assert result[0]['files'] == [os.path.join(save_path, 'Movie.mkv')]

    def test_getAllDownloadStatus_walks_multi_file_torrent_subfolder(self, tmp_path):
        qbt = self._make_qbittorrent({'label': 'couchpotato'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        save_path = str(tmp_path)
        torrent_dir = tmp_path / 'MovieSet'
        torrent_dir.mkdir()
        (torrent_dir / 'a.mkv').write_bytes(b'a')
        (torrent_dir / 'b.srt').write_bytes(b'b')

        torrent = {
            'hash': 'DEF456', 'name': 'MovieSet', 'state': 'downloading',
            'progress': 0.5, 'ratio': 0.0, 'eta': 120, 'save_path': save_path,
        }

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [torrent]
            mock_client.torrents_files.return_value = [{'name': 'a.mkv'}, {'name': 'b.srt'}]

            result = qbt.getAllDownloadStatus(['DEF456'])

        assert len(result) == 1
        assert result[0]['status'] == 'busy'
        assert sorted(os.path.basename(f) for f in result[0]['files']) == ['a.mkv', 'b.srt']
        assert result[0]['folder'] == str(torrent_dir)

    def test_getAllDownloadStatus_ignores_torrents_not_in_ids(self, tmp_path):
        qbt = self._make_qbittorrent({'label': 'couchpotato'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        torrent = {
            'hash': 'OTHER999', 'name': 'Other.Movie', 'state': 'downloading',
            'progress': 0.1, 'ratio': 0.0, 'eta': 300, 'save_path': str(tmp_path),
        }

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [torrent]

            result = qbt.getAllDownloadStatus(['ABC123'])

        assert len(result) == 0
        mock_client.torrents_files.assert_not_called()

    def test_getAllDownloadStatus_returns_empty_list_on_api_error(self):
        qbt = self._make_qbittorrent({'label': 'couchpotato'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.side_effect = qbt_main.qbittorrentapi.APIConnectionError('down')

            result = qbt.getAllDownloadStatus(['ABC123'])

        assert result == []

    def test_getAllDownloadStatus_returns_empty_list_when_connect_fails(self):
        qbt = self._make_qbittorrent({'label': 'couchpotato'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = False
            mock_client_cls.return_value.auth_log_in.side_effect = qbt_main.qbittorrentapi.LoginFailed()

            result = qbt.getAllDownloadStatus(['ABC123'])

        assert result == []

    # -- pause()/resume() -------------------------------------------------------

    def test_pause_stops_torrent_when_it_exists(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [{'hash': 'ABC123'}]

            result = qbt.pause({'id': 'ABC123'}, pause=True)

        assert result is True
        # _getTorrent must look up ONLY this hash (torrent_hashes= filter), not
        # fetch every torrent and grab [0] -- guard against that regression.
        mock_client.torrents_info.assert_called_once_with(torrent_hashes='ABC123')
        mock_client.torrents_pause.assert_called_once_with(torrent_hashes='ABC123')
        mock_client.torrents_resume.assert_not_called()

    def test_resume_starts_torrent_when_it_exists(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [{'hash': 'ABC123'}]

            result = qbt.pause({'id': 'ABC123'}, pause=False)

        assert result is True
        mock_client.torrents_resume.assert_called_once_with(torrent_hashes='ABC123')
        mock_client.torrents_pause.assert_not_called()

    def test_pause_returns_false_when_torrent_missing(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = []

            result = qbt.pause({'id': 'NOPE'})

        assert result is False
        mock_client.torrents_pause.assert_not_called()

    def test_pause_returns_false_on_api_error(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [{'hash': 'ABC123'}]
            mock_client.torrents_pause.side_effect = qbt_main.qbittorrentapi.APIConnectionError('down')

            result = qbt.pause({'id': 'ABC123'})

        assert result is False

    def test_pause_returns_false_when_connect_fails(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = False
            mock_client_cls.return_value.auth_log_in.side_effect = qbt_main.qbittorrentapi.LoginFailed()

            result = qbt.pause({'id': 'ABC123'})

        assert result is False

    # -- processComplete()/removeFailed() ---------------------------------------

    def test_processComplete_removes_torrent_keeping_files(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [{'hash': 'ABC123'}]

            result = qbt.processComplete({'id': 'ABC123', 'name': 'Some.Movie'}, delete_files=False)

        assert result is True
        # _getTorrent must look up ONLY this hash (torrent_hashes= filter), not
        # fetch every torrent and grab [0] -- guard against that regression.
        mock_client.torrents_info.assert_called_once_with(torrent_hashes='ABC123')
        mock_client.torrents_delete.assert_called_once_with(delete_files=False, torrent_hashes='ABC123')

    def test_processComplete_removes_torrent_and_data(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [{'hash': 'ABC123'}]

            result = qbt.processComplete({'id': 'ABC123', 'name': 'Some.Movie'}, delete_files=True)

        assert result is True
        mock_client.torrents_delete.assert_called_once_with(delete_files=True, torrent_hashes='ABC123')

    def test_processComplete_returns_false_when_torrent_missing(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = []

            result = qbt.processComplete({'id': 'ABC123', 'name': 'Some.Movie'}, delete_files=True)

        assert result is False
        mock_client.torrents_delete.assert_not_called()

    def test_processComplete_returns_false_on_api_error(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [{'hash': 'ABC123'}]
            mock_client.torrents_delete.side_effect = qbt_main.qbittorrentapi.APIConnectionError('down')

            result = qbt.processComplete({'id': 'ABC123', 'name': 'Some.Movie'}, delete_files=True)

        assert result is False

    def test_removeFailed_delegates_to_processComplete_with_delete_files(self):
        qbt = self._make_qbittorrent()

        with patch.object(qbt, 'processComplete', return_value=True) as mock_process:
            result = qbt.removeFailed({'id': 'ABC123', 'name': 'Some.Movie'})

        assert result is True
        mock_process.assert_called_once_with({'id': 'ABC123', 'name': 'Some.Movie'}, delete_files=True)

    # -- qbittorrent-api signature guard -----------------------------------------

    def test_qbittorrentapi_signatures_match_what_cp_passes(self):
        """Guard against silent breakage when qbittorrent-api is upgraded.

        Every other test in this class patches ``qbittorrentapi.Client``
        wholesale, so none would notice if a future release renamed or
        dropped a keyword CP actually passes. This imports the REAL
        qbittorrentapi and checks (via inspect.signature) that each
        parameter CP relies on still exists.
        """
        qbt_api = pytest.importorskip('qbittorrentapi')
        import inspect

        client_params = inspect.signature(qbt_api.Client.__init__).parameters
        for kw in ('host', 'username', 'password'):
            assert kw in client_params, (
                f'qbittorrentapi.Client.__init__ lost the `{kw}` kwarg CP depends on: '
                f'{list(client_params)}'
            )

        assert isinstance(qbt_api.Client.is_logged_in, property), (
            'qbittorrentapi.Client.is_logged_in is no longer a property CP can read'
        )

        add_params = inspect.signature(qbt_api.Client.torrents_add).parameters
        for kw in ('urls', 'torrent_files', 'category', 'is_stopped'):
            assert kw in add_params, (
                f'qbittorrentapi.Client.torrents_add lost the `{kw}` kwarg CP depends on: '
                f'{list(add_params)}'
            )

        info_params = inspect.signature(qbt_api.Client.torrents_info).parameters
        for kw in ('status_filter', 'category', 'torrent_hashes'):
            assert kw in info_params, (
                f'qbittorrentapi.Client.torrents_info lost the `{kw}` kwarg CP depends on: '
                f'{list(info_params)}'
            )

        files_params = inspect.signature(qbt_api.Client.torrents_files).parameters
        assert 'torrent_hash' in files_params, (
            f'qbittorrentapi.Client.torrents_files lost the `torrent_hash` kwarg CP '
            f'depends on: {list(files_params)}'
        )

        for method in ('torrents_pause', 'torrents_resume', 'torrents_stop', 'torrents_start'):
            assert hasattr(qbt_api.Client, method), (
                f'qbittorrentapi.Client no longer exposes {method}()'
            )

        delete_params = inspect.signature(qbt_api.Client.torrents_delete).parameters
        for kw in ('delete_files', 'torrent_hashes'):
            assert kw in delete_params, (
                f'qbittorrentapi.Client.torrents_delete lost the `{kw}` kwarg CP '
                f'depends on: {list(delete_params)}'
            )

        assert hasattr(qbt_api, 'APIError'), 'qbittorrentapi lost its APIError base exception'
        assert issubclass(qbt_api.LoginFailed, qbt_api.APIError)
        assert issubclass(qbt_api.Forbidden403Error, qbt_api.APIError)
