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
# rTorrent (VENDORED-04: rtorrent-rpc based adapter, replacing the vendored
# couchpotato/lib/rtorrent client that crashed under Python 3)
# ===========================================================================

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
        adapter = MagicMock()
        mock_torrent = MagicMock()
        adapter.load_torrent.return_value = mock_torrent

        rt = self._make_downloader(adapter)
        data = {'protocol': 'torrent', 'name': 'Movie.torrent'}

        # bdecode/bencode are stubbed here: the hash computed from a real
        # torrent's "info" dict is unrelated to what VENDORED-04 changed
        # (the load_torrent call-site wiring), so this isolates that.
        with patch.object(rt, 'conf', side_effect = self._conf(label = 'movies')), \
             patch.object(rtorrent_module, 'bdecode', return_value = {'info': {'name': 'Movie'}}), \
             patch.object(rtorrent_module, 'bencode', return_value = b'encoded-info'):
            result = rt.download(data = data, filedata = b'd...e')

        assert adapter.load_torrent.call_count == 1
        call_args = adapter.load_torrent.call_args[0]
        assert call_args[0] == b'd...e'  # filedata passed through unchanged
        # info_hash (2nd positional arg) is now passed to load_torrent
        # directly, instead of load_torrent re-deriving it internally.
        assert isinstance(call_args[1], str) and len(call_args[1]) == 40
        mock_torrent.set_custom.assert_called_once_with(1, 'movies')
        mock_torrent.start.assert_called_once()
        assert result['id']
