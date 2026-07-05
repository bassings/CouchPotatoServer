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
        # id is normalized to lowercase hex to match qBit's reported hash.
        assert result['id'] == 'aabbccddeeff00112233445566778899aabbccdd'
        assert result['downloader'] == 'qBittorrent'

    def test_download_magnet_uppercase_hex_hash_is_lowercased(self):
        """A 40-char UPPER hex btih must be stored lowercase so it matches
        qBittorrent's lowercase-hex torrent['hash'] in getAllDownloadStatus."""
        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': False,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            result = qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet',
                'url': 'magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD',
            })

        assert result['id'] == 'aabbccddeeff00112233445566778899aabbccdd'

    def test_download_magnet_base32_hash_converted_to_lowercase_hex(self):
        """A 32-char BASE32 btih must be converted to 40-char lowercase hex
        (qBittorrent only knows the hex form), otherwise it can never match."""
        from base64 import b16encode, b32decode

        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': False,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        # A real 32-char base32 info-hash and its expected 40-char lowercase hex.
        b32_hash = 'MFRGGZDFMZTWQ2LKNNWG23TPOBYXE43U'  # 32 base32 chars
        expected_hex = b16encode(b32decode(b32_hash)).decode().lower()

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            result = qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet',
                'url': 'magnet:?xt=urn:btih:%s' % b32_hash,
            })

        assert len(result['id']) == 40
        assert result['id'] == expected_hex
        assert result['id'] == result['id'].lower()

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

    def test_download_magnet_invalid_base32_hash_returns_false_with_specific_error(self):
        """A 32-char btih that matches [\\w] but isn't valid base32 (\\w allows
        0/1/8/9/_) must fail with a specific, logged error and a falsy return --
        NOT an uncaught binascii.Error from b32decode escaping to fireEvent."""
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls, \
             patch.object(qbt_main.log, 'error') as mock_log_error:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            # 32 chars, all valid \w, but '0' and '1' are not in the base32
            # alphabet (A-Z2-7), so b32decode raises binascii.Error.
            result = qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet',
                'url': 'magnet:?xt=urn:btih:00000000000000000000000000000000&dn=Some.Movie',
            })

        assert result is False
        # A bad hash is a handled failure -- the torrent is never sent.
        mock_client.torrents_add.assert_not_called()
        assert mock_log_error.call_count == 1
        assert 'invalid info-hash in magnet URL' in mock_log_error.call_args[0][0]

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

    def test_download_torrent_file_non_dict_bencode_returns_false(self):
        """A truthy but non-dict bencoded payload (e.g. b'i5e' -> the tuple
        (5,)) decodes to a non-subscriptable value, so bdecode(filedata)[b"info"]
        raises TypeError. The guard must catch it (b'' can't be used here -- it
        is falsy and bails out earlier on the `not filedata` guard). Fails
        today with an uncaught TypeError."""
        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': False,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls, \
             patch.object(qbt_main.log, 'error') as mock_log_error:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True

            # b'i5e' is a bencoded integer; bdecode returns (5,), and
            # (5,)[b"info"] raises TypeError.
            result = qbt.download(data={'name': 'Some.Movie', 'protocol': 'torrent'}, filedata=b'i5e')

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

    def test_getAllDownloadStatus_matches_magnet_hash_case_insensitively(self, tmp_path):
        """The actual bug: a magnet-added torrent's stored id could be UPPER
        hex while qBittorrent reports torrent['hash'] in LOWER hex. The old
        case-sensitive `torrent['hash'] in ids` compare never matched, so CP
        never saw magnet torrents complete/seed. The compare must be
        case-insensitive."""
        qbt = self._make_qbittorrent({'label': 'couchpotato'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        save_path = str(tmp_path)
        (tmp_path / 'Movie.mkv').write_bytes(b'data')

        # qBittorrent reports the hash in LOWERCASE hex.
        torrent = {
            'hash': 'aabbccddeeff00112233445566778899aabbccdd',
            'name': 'Movie.mkv', 'state': 'uploading',
            'progress': 1, 'ratio': 2.0, 'eta': 0, 'save_path': save_path,
        }

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_info.return_value = [torrent]
            mock_client.torrents_files.return_value = [{'name': 'Movie.mkv'}]

            # CP asks about the same hash but in UPPERCASE (as an old magnet
            # add would have stored it) -- must still match.
            result = qbt.getAllDownloadStatus(['AABBCCDDEEFF00112233445566778899AABBCCDD'])

        assert len(result) == 1
        assert result[0]['id'] == 'aabbccddeeff00112233445566778899aabbccdd'
        assert result[0]['status'] == 'seeding'

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



import xmlrpc.client as _xmlrpc_client
import requests.auth as _requests_auth

from couchpotato.core.downloaders import rtorrent_ as rtorrent_module


class TestRTorrentAdapter:
    """Tests for the internal rTorrent RPC adapter (no real sockets)."""

    def _make_adapter(self):
        adapter = rtorrent_module._RTorrentAdapter.__new__(rtorrent_module._RTorrentAdapter)
        adapter.rpc = MagicMock()
        return adapter

    def test_get_torrents_converts_ratio_from_per_mille(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = [
            ('abc123', 'Movie.mkv', 1, 1, 1500, 1, 0, 1000, '/downloads/Movie'),
        ]

        torrents = adapter.get_torrents()

        assert len(torrents) == 1
        assert torrents[0].ratio == 1.5

    def test_get_torrents_converts_booleans_and_upcases_hash(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = [
            ('abc123def', 'Movie.mkv', 0, 1, 0, 1, 500, 0, '/downloads/Movie'),
        ]

        torrent = adapter.get_torrents()[0]

        assert torrent.complete is False
        assert torrent.open is True
        assert torrent.info_hash == 'ABC123DEF'
        assert torrent.name == 'Movie.mkv'
        assert torrent.state == 1
        assert torrent.left_bytes == 500
        assert torrent.down_rate == 0
        assert torrent.directory == '/downloads/Movie'

    def test_get_torrents_issues_expected_multicall(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = []

        adapter.get_torrents()

        adapter.rpc.d.multicall2.assert_called_once_with(
            '', 'main',
            'd.hash=', 'd.name=', 'd.complete=', 'd.is_open=', 'd.ratio=',
            'd.state=', 'd.left_bytes=', 'd.down.rate=', 'd.directory=',
        )

    def test_find_torrent_matches_case_insensitively(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = [
            ('abc123', 'Movie.mkv', 1, 0, 0, 1, 0, 0, '/downloads/Movie'),
        ]

        torrent = adapter.find_torrent('abc123')

        assert torrent is not None
        assert torrent.info_hash == 'ABC123'

    def test_find_torrent_returns_none_when_missing(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = []

        assert adapter.find_torrent('deadbeef') is None

    def test_load_magnet_found_immediately(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = [
            ('ABC123', 'Movie.mkv', 1, 0, 0, 1, 0, 0, '/downloads/Movie'),
        ]

        with patch('couchpotato.core.downloaders.rtorrent_.time.sleep') as mock_sleep:
            torrent = adapter.load_magnet('magnet:?xt=urn:btih:ABC123', 'ABC123')

        adapter.rpc.load.start.assert_called_once_with('', 'magnet:?xt=urn:btih:ABC123')
        assert torrent is not None
        assert torrent.info_hash == 'ABC123'
        mock_sleep.assert_not_called()

    def test_load_magnet_found_after_a_couple_of_polls(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.side_effect = [
            [],
            [],
            [('ABC123', 'Movie.mkv', 1, 0, 0, 1, 0, 0, '/downloads/Movie')],
        ]

        with patch('couchpotato.core.downloaders.rtorrent_.time.sleep') as mock_sleep:
            torrent = adapter.load_magnet('magnet:?xt=urn:btih:ABC123', 'ABC123', verify_retries=10)

        assert torrent is not None
        assert torrent.info_hash == 'ABC123'
        assert mock_sleep.call_count == 2

    def test_load_magnet_never_found_returns_none(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = []

        with patch('couchpotato.core.downloaders.rtorrent_.time.sleep') as mock_sleep:
            torrent = adapter.load_magnet('magnet:?xt=urn:btih:ABC123', 'ABC123', verify_retries=3)

        assert torrent is None
        # No sleep after the final (futile) attempt.
        assert mock_sleep.call_count == 2

    def test_load_magnet_waits_for_name_to_resolve(self):
        # rTorrent initially reports a magnet's name AS the info-hash until
        # metadata is fetched from peers. load_magnet must keep polling until
        # the name resolves to real metadata, not return the placeholder.
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.side_effect = [
            # Present, but name is still the raw info-hash placeholder.
            [('ABC123', 'ABC123', 0, 0, 0, 1, 0, 0, '/downloads')],
            # Name now resolved.
            [('ABC123', 'Real.Movie.mkv', 0, 0, 0, 1, 0, 0, '/downloads/Real.Movie')],
        ]

        with patch('couchpotato.core.downloaders.rtorrent_.time.sleep') as mock_sleep:
            torrent = adapter.load_magnet('magnet:?xt=urn:btih:ABC123', 'ABC123')

        assert torrent is not None
        assert torrent.name == 'Real.Movie.mkv'
        # Slept once between the placeholder poll and the resolved poll.
        assert mock_sleep.call_count == 1

    def test_load_magnet_returns_none_if_name_never_resolves(self):
        adapter = self._make_adapter()
        # Always present but name stays as the raw info-hash placeholder.
        adapter.rpc.d.multicall2.return_value = [
            ('ABC123', 'abc123', 0, 0, 0, 1, 0, 0, '/downloads'),
        ]

        with patch('couchpotato.core.downloaders.rtorrent_.time.sleep'):
            torrent = adapter.load_magnet('magnet:?xt=urn:btih:ABC123', 'ABC123', verify_retries=3)

        assert torrent is None

    def test_load_torrent_accepts_name_equal_to_hash(self):
        # For torrent-FILE loads the metadata is already known, so we must NOT
        # apply the magnet name-resolution wait -- a name that happens to equal
        # the hash must still be accepted immediately.
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = [
            ('ABC123', 'ABC123', 1, 0, 0, 1, 0, 0, '/downloads'),
        ]

        with patch('couchpotato.core.downloaders.rtorrent_.time.sleep') as mock_sleep:
            torrent = adapter.load_torrent(b'irrelevant', 'ABC123', verify_retries=3)

        assert torrent is not None
        mock_sleep.assert_not_called()

    def test_load_torrent_issues_load_raw_with_binary_and_polls(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.side_effect = [
            [],
            [('ABC123', 'Movie.mkv', 1, 0, 0, 1, 0, 0, '/downloads/Movie')],
        ]
        filedata = b'd8:announce...e'

        with patch('couchpotato.core.downloaders.rtorrent_.time.sleep'):
            torrent = adapter.load_torrent(filedata, 'ABC123', verify_retries=10)

        assert adapter.rpc.load.raw.call_count == 1
        call_args = adapter.rpc.load.raw.call_args[0]
        assert call_args[0] == ''
        assert isinstance(call_args[1], _xmlrpc_client.Binary)
        assert call_args[1].data == filedata
        assert torrent is not None

    def test_load_torrent_never_found_returns_none(self):
        adapter = self._make_adapter()
        adapter.rpc.d.multicall2.return_value = []

        with patch('couchpotato.core.downloaders.rtorrent_.time.sleep'):
            torrent = adapter.load_torrent(b'irrelevant', 'ABC123', verify_retries=2)

        assert torrent is None

    def test_unsupported_scheme_raises(self):
        with pytest.raises(ValueError):
            rtorrent_module._RTorrentAdapter('ftp://localhost')


class TestRTorrentTorrentOperations:
    """Tests for the per-torrent _RTorrentTorrent RPC dispatch."""

    def _make_torrent(self, **overrides):
        rpc = MagicMock()
        kwargs = dict(
            rpc = rpc, info_hash = 'ABC123', name = 'Movie.mkv', complete = True,
            open_ = False, ratio = 1.5, state = 1, left_bytes = 0, down_rate = 0,
            directory = '/downloads/Movie',
        )
        kwargs.update(overrides)
        return rpc, rtorrent_module._RTorrentTorrent(**kwargs)

    def test_get_files_returns_path_objects(self):
        rpc, torrent = self._make_torrent()
        rpc.f.multicall.return_value = [('Movie.mkv',), ('Movie.nfo',)]

        files = torrent.get_files()

        rpc.f.multicall.assert_called_once_with('ABC123', '', 'f.path=')
        assert [f.path for f in files] == ['Movie.mkv', 'Movie.nfo']

    def test_set_custom_dispatches_to_custom1(self):
        rpc, torrent = self._make_torrent()

        torrent.set_custom(1, 'my-label')

        rpc.d.custom1.set.assert_called_once_with('ABC123', 'my-label')

    def test_set_directory_dispatches_correctly(self):
        rpc, torrent = self._make_torrent()

        torrent.set_directory('/new/path')

        rpc.d.directory.set.assert_called_once_with('ABC123', '/new/path')

    def test_start_calls_d_start(self):
        rpc, torrent = self._make_torrent()

        torrent.start()

        rpc.d.start.assert_called_once_with('ABC123')

    def test_pause_calls_d_stop(self):
        rpc, torrent = self._make_torrent()

        torrent.pause()

        rpc.d.stop.assert_called_once_with('ABC123')

    def test_resume_calls_d_start(self):
        rpc, torrent = self._make_torrent()

        torrent.resume()

        rpc.d.start.assert_called_once_with('ABC123')

    def test_erase_calls_d_erase_and_touches_no_filesystem(self):
        rpc, torrent = self._make_torrent()

        with patch('os.unlink') as mock_unlink, patch('os.rmdir') as mock_rmdir:
            torrent.erase()

        rpc.d.erase.assert_called_once_with('ABC123')
        mock_unlink.assert_not_called()
        mock_rmdir.assert_not_called()

    def test_is_multi_file_converts_to_bool(self):
        rpc, torrent = self._make_torrent()
        rpc.d.is_multi_file.return_value = '1'

        assert torrent.is_multi_file() is True

        rpc.d.is_multi_file.return_value = 0

        assert torrent.is_multi_file() is False


class TestRTorrentUrlRewrite:
    """Tests for the httprpc(+https) -> ruTorrent action.php rewrite."""

    def test_httprpc_rewrites_to_fixed_action_php(self):
        result = rtorrent_module._rewrite_httprpc_url('httprpc://myhost:80/')

        assert result == 'http://myhost:80/plugins/httprpc/action.php'

    def test_httprpc_preserves_existing_path_prefix(self):
        result = rtorrent_module._rewrite_httprpc_url('httprpc://myhost/rutorrent/')

        assert result == 'http://myhost/rutorrent/plugins/httprpc/action.php'

    def test_httprpc_https_variant_rewrites_to_https(self):
        result = rtorrent_module._rewrite_httprpc_url('httprpc+https://myhost/')

        assert result == 'https://myhost/plugins/httprpc/action.php'

    def test_non_httprpc_urls_are_passed_through_unchanged(self):
        assert rtorrent_module._rewrite_httprpc_url('http://myhost:80/RPC2') == 'http://myhost:80/RPC2'
        assert rtorrent_module._rewrite_httprpc_url('scgi://myhost:5000') == 'scgi://myhost:5000'


class TestRTorrentAuthTransport:
    """Tests for the requests-backed XML-RPC transport used for http(s)."""

    def test_digest_auth_sets_http_digest_auth(self):
        transport = rtorrent_module._RTorrentAuthTransport(
            secure = False, auth = ('digest', 'user', 'pass'), verify_ssl = True,
        )

        assert isinstance(transport.session.auth, _requests_auth.HTTPDigestAuth)

    def test_basic_auth_sets_http_basic_auth(self):
        transport = rtorrent_module._RTorrentAuthTransport(
            secure = False, auth = ('basic', 'user', 'pass'), verify_ssl = True,
        )

        assert isinstance(transport.session.auth, _requests_auth.HTTPBasicAuth)

    def test_no_auth_leaves_session_anonymous(self):
        transport = rtorrent_module._RTorrentAuthTransport(
            secure = False, auth = None, verify_ssl = True,
        )

        assert transport.session.auth is None

    def test_verify_ssl_false_disables_verification(self):
        transport = rtorrent_module._RTorrentAuthTransport(secure = True, verify_ssl = False)

        assert transport.session.verify is False

    def test_verify_ssl_true_enables_verification(self):
        transport = rtorrent_module._RTorrentAuthTransport(secure = True, verify_ssl = True)

        assert transport.session.verify is True

    def test_verify_ssl_ca_bundle_path_passed_through(self):
        transport = rtorrent_module._RTorrentAuthTransport(secure = True, verify_ssl = '/etc/ssl/mycerts')

        assert transport.session.verify == '/etc/ssl/mycerts'

    def _mock_response(self, status_code, body, reason = 'OK'):
        resp = MagicMock()
        resp.status_code = status_code
        resp.reason = reason
        resp.headers = {}
        # xmlrpc.client's Transport.getparser() feeds via iter_content chunks.
        resp.iter_content.return_value = [body]
        return resp

    def test_single_request_parses_200_xmlrpc_response(self):
        # A valid XML-RPC methodResponse carrying a single string value.
        body = (
            b"<?xml version='1.0'?><methodResponse><params><param>"
            b"<value><string>0.9.8</string></value>"
            b"</param></params></methodResponse>"
        )
        transport = rtorrent_module._RTorrentAuthTransport(secure = False)
        response = self._mock_response(200, body)

        with patch.object(transport.session, 'post', return_value = response) as mock_post:
            result = transport.single_request('host:80', '/RPC2', b'<methodCall/>')

        # xmlrpc unmarshals a single-value response into that bare value.
        assert result == ('0.9.8',)
        args, kwargs = mock_post.call_args
        assert args[0] == 'http://host:80/RPC2'
        assert kwargs['data'] == b'<methodCall/>'
        assert kwargs['headers']['Content-Type'] == 'text/xml'
        # A timeout MUST be set so a black-holed/hung endpoint fails over to
        # the caller's except-handler instead of blocking the thread forever.
        assert kwargs['timeout'] == rtorrent_module._RPC_TIMEOUT
        # stream=True: the response MUST be closed to return the connection to
        # urllib3's pool (success path).
        response.close.assert_called_once()

    def test_single_request_uses_https_when_secure(self):
        body = (
            b"<?xml version='1.0'?><methodResponse><params><param>"
            b"<value><i4>1</i4></value></param></params></methodResponse>"
        )
        transport = rtorrent_module._RTorrentAuthTransport(secure = True)

        with patch.object(transport.session, 'post', return_value = self._mock_response(200, body)) as mock_post:
            result = transport.single_request('host:443', '/RPC2', b'<methodCall/>')

        assert result == (1,)
        assert mock_post.call_args[0][0] == 'https://host:443/RPC2'
        assert mock_post.call_args.kwargs['timeout'] == rtorrent_module._RPC_TIMEOUT

    def test_single_request_raises_protocol_error_on_non_200(self):
        transport = rtorrent_module._RTorrentAuthTransport(secure = False)
        response = self._mock_response(401, b'nope', reason = 'Unauthorized')

        with patch.object(transport.session, 'post', return_value = response):
            with pytest.raises(_xmlrpc_client.ProtocolError) as exc_info:
                transport.single_request('host:80', '/RPC2', b'<methodCall/>')

        assert exc_info.value.errcode == 401
        assert exc_info.value.url == 'host:80/RPC2'
        # The error path must still close the response -- otherwise a WAF/401
        # loop leaks a pooled connection on every call.
        response.close.assert_called_once()

    def test_single_request_raises_fault_on_xmlrpc_fault_body(self):
        # A 200 response whose body is an XML-RPC <fault> must still raise Fault.
        body = (
            b"<?xml version='1.0'?><methodResponse><fault><value><struct>"
            b"<member><name>faultCode</name><value><int>-506</int></value></member>"
            b"<member><name>faultString</name><value><string>Method not found</string></value></member>"
            b"</struct></value></fault></methodResponse>"
        )
        transport = rtorrent_module._RTorrentAuthTransport(secure = False)

        with patch.object(transport.session, 'post', return_value = self._mock_response(200, body)):
            with pytest.raises(_xmlrpc_client.Fault) as exc_info:
                transport.single_request('host:80', '/RPC2', b'<methodCall/>')

        assert exc_info.value.faultCode == -506


class TestRTorrentRpcSignatureGuard:
    """Guard against silent rtorrent_rpc API drift on upgrade (mirrors the
    putio/qbittorrent precedent). If a future rtorrent-rpc release changes the
    RTorrent constructor or drops the public .rpc attribute CP relies on, this
    turns the break into a caught CI failure instead of a runtime surprise."""

    def test_rtorrent_constructor_accepts_url_and_timeout(self):
        rtorrent_rpc = pytest.importorskip('rtorrent_rpc')
        import inspect

        sig = inspect.signature(rtorrent_rpc.RTorrent.__init__)
        params = sig.parameters

        # CP constructs rtorrent_rpc.RTorrent(url, timeout=<int>).
        assert 'timeout' in params
        # The first positional (after self) is the address/url.
        positional = [p for p in params.values() if p.name != 'self']
        assert positional, 'RTorrent.__init__ takes no positional args'
        # Binding the exact call CP makes must not raise.
        sig.bind(None, 'scgi://localhost:5000', timeout = 30)

    def test_rtorrent_exposes_rpc_attribute(self):
        rtorrent_rpc = pytest.importorskip('rtorrent_rpc')

        # Constructing against an scgi URL does not touch the network (lazy
        # XML-RPC proxy), so this is safe and offline.
        rt = rtorrent_rpc.RTorrent('scgi://localhost:5000', timeout = 30)
        assert hasattr(rt, 'rpc')

    def test_rtorrent_supports_unix_socket_url(self):
        # CP's scgi branch forwards both scgi://host:port (TCP) and the
        # triple-slash unix-socket form scgi:///path.sock to the same
        # rtorrent_rpc.RTorrent(url, timeout=...) call. Guard the unix-socket
        # form too, so a future rtorrent_rpc that drops unix-socket support
        # fails loudly in CI instead of breaking unix-socket users at runtime.
        # Construction is lazy (no socket touched), so this is offline.
        rtorrent_rpc = pytest.importorskip('rtorrent_rpc')

        rt = rtorrent_rpc.RTorrent('scgi:///tmp/rtorrent.sock', timeout = 30)
        assert hasattr(rt, 'rpc')


class TestRTorrentDownloaderConnect:
    """Tests for rTorrent.connect()/test() -- the connectivity check that
    replaces the vendored lib's now-nonexistent connection.verify()."""

    def _make_downloader(self):
        rt = rtorrent_module.rTorrent.__new__(rtorrent_module.rTorrent)
        rt.rt = None
        rt.error_msg = ''
        return rt

    def _conf(self, **overrides):
        values = {
            'host': 'localhost:80', 'ssl': False, 'ssl_verify': True,
            'ssl_ca_bundle': '', 'username': '', 'password': '',
            'authentication': 'basic', 'rpc_url': 'RPC2',
        }
        values.update(overrides)
        return lambda k, **kw: values.get(k, kw.get('default', ''))

    def test_connect_succeeds_when_client_version_call_works(self):
        rt = self._make_downloader()
        mock_adapter = MagicMock()
        mock_adapter.rpc.system.client_version.return_value = '0.9.8'

        with patch.object(rt, 'conf', side_effect = self._conf()), \
             patch.object(rtorrent_module, '_RTorrentAdapter', return_value = mock_adapter) as mock_cls:
            result = rt.connect(True)

        assert result is mock_adapter
        assert rt.error_msg == ''
        mock_adapter.rpc.system.client_version.assert_called_once()
        # Default host + default rpc_url is appended for a plain http(s) URL.
        called_url = mock_cls.call_args[0][0]
        assert called_url == 'http://localhost:80/RPC2'

    def test_connect_fails_and_sets_error_msg_when_rpc_call_raises(self):
        rt = self._make_downloader()
        mock_adapter = MagicMock()
        mock_adapter.rpc.system.client_version.side_effect = Exception('no route to host')

        with patch.object(rt, 'conf', side_effect = self._conf()), \
             patch.object(rtorrent_module, '_RTorrentAdapter', return_value = mock_adapter):
            result = rt.connect(True)

        assert result is None
        assert rt.rt is None
        assert rt.error_msg == 'no route to host'

    def test_test_returns_true_on_success(self):
        rt = self._make_downloader()
        mock_adapter = MagicMock()

        with patch.object(rt, 'conf', side_effect = self._conf()), \
             patch.object(rtorrent_module, '_RTorrentAdapter', return_value = mock_adapter):
            assert rt.test() is True

    def test_test_returns_failure_tuple_with_message_on_error(self):
        rt = self._make_downloader()
        mock_adapter = MagicMock()
        mock_adapter.rpc.system.client_version.side_effect = Exception('timed out')

        with patch.object(rt, 'conf', side_effect = self._conf()), \
             patch.object(rtorrent_module, '_RTorrentAdapter', return_value = mock_adapter):
            result = rt.test()

        assert result == (False, 'Connection failed: timed out')

    def test_connect_httprpc_url_rewritten_and_rpc_url_not_appended(self):
        rt = self._make_downloader()
        mock_adapter = MagicMock()

        with patch.object(rt, 'conf', side_effect = self._conf(host = 'httprpc://myhost/rutorrent')), \
             patch.object(rtorrent_module, '_RTorrentAdapter', return_value = mock_adapter) as mock_cls:
            rt.connect(True)

        called_url = mock_cls.call_args[0][0]
        assert called_url == 'http://myhost/rutorrent/plugins/httprpc/action.php'

    def test_connect_httprpc_becomes_https_when_ssl_enabled(self):
        rt = self._make_downloader()
        mock_adapter = MagicMock()

        with patch.object(rt, 'conf', side_effect = self._conf(host = 'httprpc://myhost', ssl = True)), \
             patch.object(rtorrent_module, '_RTorrentAdapter', return_value = mock_adapter) as mock_cls:
            rt.connect(True)

        called_url = mock_cls.call_args[0][0]
        assert called_url == 'https://myhost/plugins/httprpc/action.php'


class TestRTorrentDownload:
    """Tests for rTorrent.download() -- magnet and torrent-file add paths."""

    def _make_downloader(self, adapter):
        rt = rtorrent_module.rTorrent.__new__(rtorrent_module.rTorrent)
        rt.rt = adapter  # already "connected"
        rt.error_msg = ''
        return rt

    def _conf(self, **overrides):
        values = {'label': '', 'directory': '', 'paused': 0}
        values.update(overrides)
        return lambda k, **kw: values.get(k, kw.get('default', ''))

    def test_download_magnet_loads_and_starts_torrent(self):
        adapter = MagicMock()
        mock_torrent = MagicMock()
        adapter.load_magnet.return_value = mock_torrent

        rt = self._make_downloader(adapter)
        data = {'protocol': 'torrent_magnet', 'url': 'magnet:?xt=urn:btih:ABCDEF0123456789ABCDEF0123456789ABCDEF01'}

        with patch.object(rt, 'conf', side_effect = self._conf()):
            result = rt.download(data = data)

        adapter.load_magnet.assert_called_once_with(data['url'], 'ABCDEF0123456789ABCDEF0123456789ABCDEF01')
        mock_torrent.start.assert_called_once()
        assert result['id'] == 'ABCDEF0123456789ABCDEF0123456789ABCDEF01'

    def test_download_magnet_returns_false_when_never_found(self):
        adapter = MagicMock()
        adapter.load_magnet.return_value = None

        rt = self._make_downloader(adapter)
        data = {'protocol': 'torrent_magnet', 'url': 'magnet:?xt=urn:btih:ABCDEF0123456789ABCDEF0123456789ABCDEF01'}

        with patch.object(rt, 'conf', side_effect = self._conf()):
            result = rt.download(data = data)

        assert result is False

    def test_download_torrent_file_loads_raw_and_sets_label(self):
        """Real bencode round-trip: NO mocking of bdecode/bencode.

        A previous version of this test mocked bdecode to return a
        STRING-keyed {'info': ...} dict, which is not what bencodepy.decode()
        actually returns (it returns BYTES keys, b'info'). That masked a real
        KeyError-on-every-torrent-file bug in download(). This test feeds a
        genuine bencoded torrent so the b"info" lookup and sha1 info-hash are
        exercised for real, and asserts the hash matches an independent
        computation. It FAILS against `bdecode(filedata)["info"]` (KeyError)
        and passes against `bdecode(filedata)[b"info"]`.
        """
        import bencodepy
        from hashlib import sha1

        info_dict = {
            b'name': b'Movie.mkv',
            b'piece length': 32768,
            b'pieces': b'0' * 20,
            b'length': 1024,
        }
        torrent_dict = {b'announce': b'http://tracker.example/announce', b'info': info_dict}
        filedata = bencodepy.encode(torrent_dict)

        # Independent expected info-hash (re-encode the decoded info dict, as
        # download() does, to normalise key ordering).
        expected_hash = sha1(
            bencodepy.encode(bencodepy.decode(filedata)[b'info'])
        ).hexdigest().upper()

        adapter = MagicMock()
        mock_torrent = MagicMock()
        adapter.load_torrent.return_value = mock_torrent

        rt = self._make_downloader(adapter)
        data = {'protocol': 'torrent', 'name': 'Movie.torrent'}

        with patch.object(rt, 'conf', side_effect = self._conf(label = 'movies')):
            result = rt.download(data = data, filedata = filedata)

        assert adapter.load_torrent.call_count == 1
        call_args = adapter.load_torrent.call_args[0]
        assert call_args[0] == filedata  # filedata passed through unchanged
        # info_hash (2nd positional arg) is now passed to load_torrent
        # directly, instead of load_torrent re-deriving it internally.
        assert call_args[1] == expected_hash
        assert isinstance(call_args[1], str) and len(call_args[1]) == 40
        mock_torrent.set_custom.assert_called_once_with(1, 'movies')
        mock_torrent.start.assert_called_once()
        assert result['id'] == expected_hash


class _FakeTorrent:
    """A stand-in for the _RTorrentTorrent objects get_torrents() yields, with
    just the fields/methods the downloader status/cleanup methods read. Fields
    mirror _RTorrentTorrent exactly (booleans already coerced, ratio already
    divided by 1000.0) so these tests exercise the real downstream derivation,
    not the adapter's parsing (which TestRTorrentAdapter covers)."""

    def __init__(self, info_hash = 'ABC123', name = 'Movie', complete = True,
                 open_ = True, ratio = 1.5, state = 1, left_bytes = 0,
                 down_rate = 0, directory = '/downloads/Movie', files = None,
                 multi_file = False):
        self.info_hash = info_hash
        self.name = name
        self.complete = complete
        self.open = open_
        self.ratio = ratio
        self.state = state
        self.left_bytes = left_bytes
        self.down_rate = down_rate
        self.directory = directory
        self._files = files if files is not None else []
        self._multi_file = multi_file
        self.erased = False

    def get_files(self):
        return [_FakeFile(p) for p in self._files]

    def is_multi_file(self):
        return self._multi_file

    def erase(self):
        self.erased = True

    def pause(self):
        return 'paused'

    def resume(self):
        return 'resumed'


class _FakeFile:
    def __init__(self, path):
        self.path = path


class TestRTorrentDownloaderStatus:
    """Integration seam: rTorrent.getAllDownloadStatus/getTorrentStatus/pause/
    processComplete/removeFailed consuming adapter (_RTorrentTorrent) output.
    A _MULTICALL_FIELDS reorder or _RTorrentTorrent constructor typo would
    corrupt these; these tests assert the real derived values."""

    def _make_downloader(self, adapter):
        rt = rtorrent_module.rTorrent.__new__(rtorrent_module.rTorrent)
        rt.rt = adapter  # already "connected"; connect() returns it as-is
        rt.error_msg = ''
        return rt

    # -- getTorrentStatus derivation ----------------------------------------

    def test_status_busy_when_not_complete(self):
        rt = self._make_downloader(MagicMock())
        assert rt.getTorrentStatus(_FakeTorrent(complete = False, open_ = True)) == 'busy'

    def test_status_seeding_when_complete_and_open(self):
        rt = self._make_downloader(MagicMock())
        assert rt.getTorrentStatus(_FakeTorrent(complete = True, open_ = True)) == 'seeding'

    def test_status_completed_when_complete_and_not_open(self):
        rt = self._make_downloader(MagicMock())
        assert rt.getTorrentStatus(_FakeTorrent(complete = True, open_ = False)) == 'completed'

    # -- getAllDownloadStatus -----------------------------------------------

    def test_getAllDownloadStatus_derives_full_release_dict(self):
        torrent = _FakeTorrent(
            info_hash = 'ABC123', name = 'Movie', complete = True, open_ = True,
            ratio = 2.5, state = 3, directory = '/downloads/Movie',
            files = ['/downloads/Movie/Movie.mkv'],
        )
        adapter = MagicMock()
        adapter.get_torrents.return_value = [torrent]
        rt = self._make_downloader(adapter)

        result = rt.getAllDownloadStatus(['ABC123'])

        assert len(result) == 1
        entry = result[0]
        assert entry['id'] == 'ABC123'
        assert entry['name'] == 'Movie'
        assert entry['status'] == 'seeding'
        assert entry['seed_ratio'] == 2.5
        assert entry['original_status'] == 3
        assert entry['folder'] == '/downloads/Movie'
        assert entry['files'] == ['/downloads/Movie/Movie.mkv']

    def test_getAllDownloadStatus_ignores_torrents_not_in_ids(self):
        adapter = MagicMock()
        adapter.get_torrents.return_value = [_FakeTorrent(info_hash = 'OTHER999')]
        rt = self._make_downloader(adapter)

        result = rt.getAllDownloadStatus(['ABC123'])

        assert list(result) == []

    def test_getAllDownloadStatus_joins_relative_file_path_to_directory(self):
        # A file path that is NOT already under the torrent directory gets
        # joined onto it (leading slash stripped).
        torrent = _FakeTorrent(
            info_hash = 'ABC123', directory = '/downloads/Movie',
            files = ['/Movie.mkv'],
        )
        adapter = MagicMock()
        adapter.get_torrents.return_value = [torrent]
        rt = self._make_downloader(adapter)

        result = rt.getAllDownloadStatus(['ABC123'])

        assert result[0]['files'] == [os.path.join('/downloads/Movie', 'Movie.mkv')]

    def test_getAllDownloadStatus_keeps_absolute_file_path_under_directory(self):
        # A file path already under the torrent directory is used as-is.
        torrent = _FakeTorrent(
            info_hash = 'ABC123', directory = '/downloads/Movie',
            files = ['/downloads/Movie/sub/Movie.mkv'],
        )
        adapter = MagicMock()
        adapter.get_torrents.return_value = [torrent]
        rt = self._make_downloader(adapter)

        result = rt.getAllDownloadStatus(['ABC123'])

        assert result[0]['files'] == ['/downloads/Movie/sub/Movie.mkv']

    def test_getAllDownloadStatus_timeleft_minus_one_when_no_download_rate(self):
        torrent = _FakeTorrent(info_hash = 'ABC123', left_bytes = 1000, down_rate = 0)
        adapter = MagicMock()
        adapter.get_torrents.return_value = [torrent]
        rt = self._make_downloader(adapter)

        result = rt.getAllDownloadStatus(['ABC123'])

        assert result[0]['timeleft'] == -1

    def test_getAllDownloadStatus_timeleft_computed_from_rate(self):
        # 200 bytes left at 100 bytes/s -> 2 seconds.
        from datetime import timedelta
        torrent = _FakeTorrent(info_hash = 'ABC123', left_bytes = 200, down_rate = 100)
        adapter = MagicMock()
        adapter.get_torrents.return_value = [torrent]
        rt = self._make_downloader(adapter)

        result = rt.getAllDownloadStatus(['ABC123'])

        assert result[0]['timeleft'] == str(timedelta(seconds = 2))

    # -- pause / resume -----------------------------------------------------

    def test_pause_calls_torrent_pause(self):
        torrent = _FakeTorrent(info_hash = 'ABC123')
        adapter = MagicMock()
        adapter.find_torrent.return_value = torrent
        rt = self._make_downloader(adapter)

        assert rt.pause({'id': 'ABC123'}, pause = True) == 'paused'
        adapter.find_torrent.assert_called_once_with('ABC123')

    def test_pause_false_calls_torrent_resume(self):
        torrent = _FakeTorrent(info_hash = 'ABC123')
        adapter = MagicMock()
        adapter.find_torrent.return_value = torrent
        rt = self._make_downloader(adapter)

        assert rt.pause({'id': 'ABC123'}, pause = False) == 'resumed'

    def test_pause_returns_false_when_torrent_missing(self):
        adapter = MagicMock()
        adapter.find_torrent.return_value = None
        rt = self._make_downloader(adapter)

        assert rt.pause({'id': 'MISSING'}) is False

    # -- processComplete / removeFailed -------------------------------------

    def test_processComplete_without_delete_erases_but_keeps_files(self):
        torrent = _FakeTorrent(info_hash = 'ABC123', files = ['/downloads/Movie/Movie.mkv'])
        adapter = MagicMock()
        adapter.find_torrent.return_value = torrent
        rt = self._make_downloader(adapter)

        with patch('os.unlink') as mock_unlink, patch('os.rmdir') as mock_rmdir:
            result = rt.processComplete({'id': 'ABC123', 'name': 'Movie'}, delete_files = False)

        assert result is True
        assert torrent.erased is True
        mock_unlink.assert_not_called()
        mock_rmdir.assert_not_called()

    def test_processComplete_with_delete_unlinks_files_and_erases(self):
        torrent = _FakeTorrent(
            info_hash = 'ABC123', name = 'Movie', directory = '/downloads/Movie',
            files = ['file1.mkv', 'file2.nfo'], multi_file = False,
        )
        adapter = MagicMock()
        adapter.find_torrent.return_value = torrent
        rt = self._make_downloader(adapter)

        with patch('os.unlink') as mock_unlink, patch('os.rmdir') as mock_rmdir:
            result = rt.processComplete({'id': 'ABC123', 'name': 'Movie'}, delete_files = True)

        assert result is True
        assert torrent.erased is True
        assert mock_unlink.call_count == 2
        mock_unlink.assert_any_call(os.path.join('/downloads/Movie', 'file1.mkv'))
        mock_unlink.assert_any_call(os.path.join('/downloads/Movie', 'file2.nfo'))
        # Single-file torrent -> no directory teardown.
        mock_rmdir.assert_not_called()

    def test_processComplete_multi_file_removes_directory_tree(self):
        # Multi-file torrent whose directory ends with its name triggers the
        # bottom-up rmdir walk.
        torrent = _FakeTorrent(
            info_hash = 'ABC123', name = 'Movie', directory = '/downloads/Movie',
            files = ['Movie/a.mkv'], multi_file = True,
        )
        adapter = MagicMock()
        adapter.find_torrent.return_value = torrent
        rt = self._make_downloader(adapter)

        with patch('os.unlink'), \
             patch('os.walk', return_value = [('/downloads/Movie', [], [])]) as mock_walk, \
             patch('os.rmdir') as mock_rmdir:
            result = rt.processComplete({'id': 'ABC123', 'name': 'Movie'}, delete_files = True)

        assert result is True
        mock_walk.assert_called_once()
        mock_rmdir.assert_called_once_with('/downloads/Movie')

    def test_processComplete_returns_false_when_torrent_missing(self):
        adapter = MagicMock()
        adapter.find_torrent.return_value = None
        rt = self._make_downloader(adapter)

        assert rt.processComplete({'id': 'MISSING', 'name': 'x'}, delete_files = True) is False

    def test_removeFailed_delegates_to_processComplete_with_delete(self):
        rt = self._make_downloader(MagicMock())

        with patch.object(rt, 'processComplete', return_value = True) as mock_pc:
            result = rt.removeFailed({'id': 'ABC123', 'name': 'Movie'})

        assert result is True
        mock_pc.assert_called_once_with({'id': 'ABC123', 'name': 'Movie'}, delete_files = True)
