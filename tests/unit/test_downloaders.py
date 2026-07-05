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

        _, kwargs = mock_client.Transfer.add_url.call_args
        assert kwargs['callback_url'].startswith('http://example.com:5050')
        assert 'downloader.putio.getfrom' in kwargs['callback_url']

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
