"""Task 18: Downloader tests — Transmission RPC and SABnzbd.

Uses unittest.mock to avoid real network calls.
"""
import json
import os
import sys
import pytest
import qbittorrentapi
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
            mock_client.auth_log_in.side_effect = qbittorrentapi.LoginFailed('bad creds')

            result = qbt.connect()

        assert result is False

    def test_connect_returns_false_on_forbidden_banned_ip(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = False
            mock_client.auth_log_in.side_effect = qbittorrentapi.Forbidden403Error('banned')

            result = qbt.connect()

        assert result is False

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
        old_client.auth_log_out.side_effect = qbittorrentapi.APIConnectionError('gone')
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
            mock_client.torrents_add.side_effect = qbittorrentapi.Conflict409Error('already added')

            result = qbt.download(data={
                'name': 'Some.Movie', 'protocol': 'torrent_magnet',
                'url': 'magnet:?xt=urn:btih:AABBCCDDEEFF00112233445566778899AABBCCDD',
            })

        assert result is False

    def test_download_file_sends_torrent_files_and_category(self):
        """The torrent-hash computation from the raw .torrent bytes
        (bdecode/bencode/sha1) is pre-existing logic untouched by the
        qbittorrent-api migration; it's stubbed out here so this test stays
        focused on what changed: the torrents_add() call itself."""
        qbt = self._make_qbittorrent({
            'host': 'http://localhost:8080/', 'label': 'couchpotato', 'paused': False,
        })
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        filedata = b'd8:announce...e'  # opaque bytes; bdecode is stubbed below

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls, \
             patch.object(qbt_main, 'bdecode', return_value={'info': {'name': 'Some.Movie'}}):
            mock_client = mock_client_cls.return_value
            mock_client.is_logged_in = True
            mock_client.torrents_add.return_value = 'Ok.'

            result = qbt.download(data={'name': 'Some.Movie', 'protocol': 'torrent'}, filedata=filedata)

        mock_client.torrents_add.assert_called_once_with(
            torrent_files=filedata, category='couchpotato', is_stopped=False,
        )
        assert result['downloader'] == 'qBittorrent'
        assert result['id']  # sha1 hash of the (stubbed) bencoded info dict

    def test_download_file_without_filedata_fails_before_connecting(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = True

            result = qbt.download(data={'name': 'Some.Movie', 'protocol': 'torrent'}, filedata=None)

        assert result is False

    def test_download_returns_false_when_connect_fails(self):
        qbt = self._make_qbittorrent({'host': 'http://localhost:8080/'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = False
            mock_client_cls.return_value.auth_log_in.side_effect = qbittorrentapi.LoginFailed()

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
            mock_client.torrents_info.side_effect = qbittorrentapi.APIConnectionError('down')

            result = qbt.getAllDownloadStatus(['ABC123'])

        assert result == []

    def test_getAllDownloadStatus_returns_empty_list_when_connect_fails(self):
        qbt = self._make_qbittorrent({'label': 'couchpotato'})
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = False
            mock_client_cls.return_value.auth_log_in.side_effect = qbittorrentapi.LoginFailed()

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
            mock_client.torrents_pause.side_effect = qbittorrentapi.APIConnectionError('down')

            result = qbt.pause({'id': 'ABC123'})

        assert result is False

    def test_pause_returns_false_when_connect_fails(self):
        qbt = self._make_qbittorrent()
        import couchpotato.core.downloaders.qbittorrent_ as qbt_main

        with patch.object(qbt_main.qbittorrentapi, 'Client') as mock_client_cls:
            mock_client_cls.return_value.is_logged_in = False
            mock_client_cls.return_value.auth_log_in.side_effect = qbittorrentapi.LoginFailed()

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
            mock_client.torrents_delete.side_effect = qbittorrentapi.APIConnectionError('down')

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
