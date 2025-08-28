from __future__ import absolute_import, division, print_function, unicode_literals
from base64 import b16encode, b32decode
from datetime import timedelta
from hashlib import sha1
from urllib.parse import urlparse
import os
import re

from couchpotato.core._base.downloader.main import DownloaderBase, ReleaseDownloadList
from couchpotato.core.event import addEvent
from couchpotato.core.helpers.encoding import sp
from couchpotato.core.helpers.variable import cleanHost, splitString
from couchpotato.core.logger import CPLog
try:
    import bencodepy as _bencode
    def bencode(obj):
        return _bencode.encode(obj)
    def bdecode(data):
        return _bencode.decode(data)
except Exception:
    from bencode import bencode, bdecode
import socket
try:
    import xmlrpc.client as xclient
except ImportError:  # pragma: no cover - legacy
    import xmlrpclib as xclient  # type: ignore
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from couchpotato.clients.rtorrent.adapter import RTorrentAdapter


log = CPLog(__name__)

autoload = 'rTorrent'


class rTorrent(DownloaderBase):

    protocol = ['torrent', 'torrent_magnet']
    rt = None
    _rt_adapter = None
    error_msg = ''

    # Migration url to host options
    def __init__(self):
        super(rTorrent, self).__init__()

        addEvent('app.load', self.migrate)
        addEvent('setting.save.rtorrent.*.after', self.settingsChanged)

    def migrate(self):

        url = self.conf('url')
        if url:
            host_split = splitString(url.split('://')[-1], split_on = '/')

            self.conf('ssl', value = url.startswith('https'))
            self.conf('host', value = host_split[0].strip())
            self.conf('rpc_url', value = '/'.join(host_split[1:]))

            self.deleteConf('url')

    def settingsChanged(self):
        # Reset active connection if settings have changed
        if self.rt:
            log.debug('Settings have changed, closing active connection')

        self.rt = None
        return True

    def getAuth(self):
        if not self.conf('username') or not self.conf('password'):
            # Missing username or password parameter
            return None

        # Build authentication tuple
        return (
            self.conf('authentication'),
            self.conf('username'),
            self.conf('password')
        )

    def getVerifySsl(self):
        # Ensure verification has been enabled
        if not self.conf('ssl_verify'):
            return False

        # Use ca bundle if defined
        ca_bundle = self.conf('ssl_ca_bundle')

        if ca_bundle and os.path.exists(ca_bundle):
            return ca_bundle

        # Use default ssl verification
        return True

    def connect(self, reconnect = False):
        # Already connected?
        if not reconnect and self._rt_adapter is not None:
            return True

        url = cleanHost(self.conf('host'), protocol = True, ssl = self.conf('ssl'))

        # Automatically add '+https' to 'httprpc' protocol if SSL is enabled
        if self.conf('ssl') and url.startswith('httprpc://'):
            url = url.replace('httprpc://', 'httprpc+https://')

        parsed = urlparse(url)
        scheme = parsed.scheme
        rpc_url = self.conf('rpc_url') or 'RPC2'

        # Build HTTP(S) endpoint when applicable
        if scheme.startswith('httprpc'):
            target_scheme = 'https' if '+' in scheme and 'https' in scheme else 'http'
            base = f"{target_scheme}://{parsed.netloc}"
            http_url = base + '/plugins/httprpc/action.php'
        elif scheme in ['http', 'https']:
            http_url = url + rpc_url
        else:
            http_url = None

        class _HTTPXMLRPCTransport(object):
            def __init__(self, url, auth_tuple, verify_ssl):
                self._url = url
                self._verify = verify_ssl
                self._session = requests.Session()
                if auth_tuple and isinstance(auth_tuple, tuple) and len(auth_tuple) == 3:
                    method, user, pwd = auth_tuple
                    if method == 'basic':
                        self._session.auth = HTTPBasicAuth(user, pwd)
                    elif method == 'digest':
                        self._session.auth = HTTPDigestAuth(user, pwd)
                self._headers = {'Content-Type': 'text/xml'}

            def call(self, method, *args):
                body = xclient.dumps(args, methodname=method, allow_none=True)
                r = self._session.post(self._url, data=body, headers=self._headers, verify=self._verify, timeout=15)
                r.raise_for_status()
                data = r.content
                if data.startswith(b'HTTP/'):
                    parts = data.split(b'\r\n\r\n', 1)
                    data = parts[1] if len(parts) > 1 else data
                return xclient.loads(data)[0][0]

        class _SCGITransport(object):
            def __init__(self, host, port):
                self._host = host
                self._port = int(port)

            def _build_netstring(self, headers: dict) -> bytes:
                items = []
                for k, v in headers.items():
                    items.append(k)
                    items.append(v)
                payload = ('\x00'.join(items) + '\x00').encode('utf-8')
                return str(len(payload)).encode('ascii') + b':' + payload + b','

            def call(self, method, *args):
                body_bytes = xclient.dumps(args, methodname=method, allow_none=True).encode('utf-8')
                headers = {
                    'CONTENT_LENGTH': str(len(body_bytes)),
                    'SCGI': '1',
                    'REQUEST_METHOD': 'POST',
                    'REQUEST_URI': '/RPC2'
                }
                netstr = self._build_netstring(headers)
                to_send = netstr + body_bytes
                s = socket.create_connection((self._host, self._port), timeout=15)
                try:
                    s.sendall(to_send)
                    chunks = []
                    while True:
                        data = s.recv(65536)
                        if not data:
                            break
                        chunks.append(data)
                    resp = b''.join(chunks)
                finally:
                    s.close()
                if resp.startswith(b'HTTP/'):
                    parts = resp.split(b'\r\n\r\n', 1)
                    resp = parts[1] if len(parts) > 1 else resp
                return xclient.loads(resp)[0][0]

        self.error_msg = ''
        try:
            if scheme == 'scgi':
                host = parsed.hostname or 'localhost'
                port = parsed.port or 5000
                transport = _SCGITransport(host, port)
            elif http_url:
                transport = _HTTPXMLRPCTransport(http_url, self.getAuth(), self.getVerifySsl())
            else:
                raise AssertionError('Unsupported rTorrent scheme: %s' % scheme)

            adapter = RTorrentAdapter(transport)
            _ = adapter.get_stats()
            self._rt_adapter = adapter
            return True
        except Exception as e:
            self.error_msg = str(e)
            self._rt_adapter = None
            return False

    def test(self):
        """ Check if connection works
        :return: bool
        """

        if self.connect(True):
            return True

        if self.error_msg:
            return False, 'Connection failed: ' + self.error_msg

        return False


    def download(self, data = None, media = None, filedata = None):
        """ Send a torrent/nzb file to the downloader

        :param data: dict returned from provider
            Contains the release information
        :param media: media dict with information
            Used for creating the filename when possible
        :param filedata: downloaded torrent/nzb filedata
            The file gets downloaded in the searcher and send to this function
            This is done to have failed checking before using the downloader, so the downloader
            doesn't need to worry about that
        :return: boolean
            One faile returns false, but the downloaded should log his own errors
        """

        if not media: media = {}
        if not data: data = {}

        log.debug('Sending "%s" to rTorrent.', (data.get('name')))

        if not self.connect():
            return False

        torrent_hash = 0
        torrent_params = {}
        if self.conf('label'):
            torrent_params['label'] = self.conf('label')

        if not filedata and data.get('protocol') == 'torrent':
            log.error('Failed sending torrent, no data')
            return False

        # Try download magnet torrents
        if data.get('protocol') == 'torrent_magnet':
            # Send magnet to rTorrent
            torrent_hash = re.findall('urn:btih:([\w]{32,40})', data.get('url'))[0].upper()
            # Send request to rTorrent
            try:
                if self._rt_adapter:
                    self._rt_adapter.add_torrent(data.get('url'), start=not self.conf('paused', default=0))
                else:
                    torrent = self.rt.load_magnet(data.get('url'), torrent_hash)
                    if not torrent:
                        log.error('Unable to find the torrent, did it fail to load?')
                        return False
            except Exception as err:
                log.error('Failed to send magnet to rTorrent: %s', err)
                return False

        if data.get('protocol') == 'torrent':
            decoded = bdecode(filedata)
            # Support both str and bytes keys from bencodepy/bencode
            if isinstance(decoded, dict):
                info = decoded.get('info') if 'info' in decoded else decoded.get(b'info')
            else:
                info = None
            if info is None:
                raise KeyError('info')
            torrent_hash = sha1(bencode(info)).hexdigest().upper()

            # Convert base 32 to hex
            if len(torrent_hash) == 32:
                torrent_hash = b16encode(b32decode(torrent_hash))

            # Send request to rTorrent
            try:
                # Send torrent to rTorrent
                if self._rt_adapter:
                    self._rt_adapter.add_torrent_file(filedata, start=not self.conf('paused', default=0))
                else:
                    torrent = self.rt.load_torrent(filedata, verify_retries=10)
                    if not torrent:
                        log.error('Unable to find the torrent, did it fail to load?')
                        return False
            except Exception as err:
                log.error('Failed to send torrent to rTorrent: %s', err)
                return False

        try:
            # Set label
            if self.conf('label'):
                # Prefer adapter call by hash when available
                if self._rt_adapter and torrent_hash:
                    self._rt_adapter.set_label(torrent_hash, self.conf('label'))
                else:
                    torrent.set_custom(1, self.conf('label'))

            if self.conf('directory'):
                if self._rt_adapter and torrent_hash:
                    self._rt_adapter.set_directory(torrent_hash, self.conf('directory'))
                else:
                    torrent.set_directory(self.conf('directory'))

            # Start torrent
            if not self.conf('paused', default = 0):
                # Adapter path already started via load.start/raw_start
                if not self._rt_adapter:
                    torrent.start()

            return self.downloadReturnId(torrent_hash)

        except Exception as err:
            log.error('Failed to send torrent to rTorrent: %s', err)
            return False


    def getTorrentStatus(self, torrent):
        if not torrent.complete:
            return 'busy'

        if torrent.open:
            return 'seeding'

        return 'completed'

    def getAllDownloadStatus(self, ids):
        """ Get status of all active downloads

        :param ids: list of (mixed) downloader ids
            Used to match the releases for this downloader as there could be
            other downloaders active that it should ignore
        :return: list of releases
        """

        log.debug('Checking rTorrent download status.')

        if not self.connect():
            return []

        release_downloads = ReleaseDownloadList(self)

        try:
            if self._rt_adapter:
                # Adapter path: use multicall to fetch details
                for t in self._rt_adapter.list_torrents_full():
                    if t['hash'] not in ids:
                        continue
                    torrent_directory = os.path.normpath(t['directory'])
                    torrent_files = []
                    for p in t['files']:
                        pnorm = os.path.normpath(p)
                        if not pnorm.startswith(torrent_directory):
                            file_path = os.path.join(torrent_directory, p.lstrip('/'))
                        else:
                            file_path = p
                        torrent_files.append(sp(file_path))

                    # Map status
                    if not t['complete']:
                        status = 'busy'
                    elif t['open']:
                        status = 'seeding'
                    else:
                        status = 'completed'

                    timeleft = -1
                    if t['down_rate'] > 0:
                        timeleft = str(timedelta(seconds=float(t['left_bytes']) / max(1.0, float(t['down_rate']))))

                    release_downloads.append({
                        'id': t['hash'],
                        'name': t['name'],
                        'status': status,
                        'seed_ratio': t['ratio'],
                        'original_status': t['state'],
                        'timeleft': timeleft,
                        'folder': sp(torrent_directory),
                        'files': torrent_files,
                    })
                return release_downloads
            else:
                # Vendored path
                torrents = self.rt.get_torrents()
                for torrent in torrents:
                    if torrent.info_hash in ids:
                        torrent_directory = os.path.normpath(torrent.directory)
                        torrent_files = []
                        for file in torrent.get_files():
                            if not os.path.normpath(file.path).startswith(torrent_directory):
                                file_path = os.path.join(torrent_directory, file.path.lstrip('/'))
                            else:
                                file_path = file.path
                            torrent_files.append(sp(file_path))

                        release_downloads.append({
                            'id': torrent.info_hash,
                            'name': torrent.name,
                            'status': self.getTorrentStatus(torrent),
                            'seed_ratio': torrent.ratio,
                            'original_status': torrent.state,
                            'timeleft': str(timedelta(seconds = float(torrent.left_bytes) / torrent.down_rate)) if torrent.down_rate > 0 else -1,
                            'folder': sp(torrent_directory),
                            'files': torrent_files
                        })
                return release_downloads
        except Exception as err:
            log.error('Failed to get status from rTorrent: %s', err)
            return []

    def pause(self, release_download, pause = True):
        if not self.connect():
            return False

        if self._rt_adapter:
            if pause:
                self._rt_adapter.pause_torrent(release_download['id'])
            else:
                self._rt_adapter.resume_torrent(release_download['id'])
            return True
        else:
            torrent = self.rt.find_torrent(release_download['id'])
            if torrent is None:
                return False
            if pause:
                return torrent.pause()
            return torrent.resume()

    def removeFailed(self, release_download):
        log.info('%s failed downloading, deleting...', release_download['name'])
        return self.processComplete(release_download, delete_files = True)

    def processComplete(self, release_download, delete_files):
        log.debug('Requesting rTorrent to remove the torrent %s%s.',
                  (release_download['name'], ' and cleanup the downloaded files' if delete_files else ''))

        if not self.connect():
            return False

        torrent = self.rt.find_torrent(release_download['id'])

        if torrent is None:
            return False

        if delete_files:
            for file_item in torrent.get_files(): # will only delete files, not dir/sub-dir
                os.unlink(os.path.join(torrent.directory, file_item.path))

            if torrent.is_multi_file() and torrent.directory.endswith(torrent.name):
                # Remove empty directories bottom up
                try:
                    for path, _, _ in os.walk(sp(torrent.directory), topdown = False):
                        os.rmdir(path)
                except OSError:
                    log.info('Directory "%s" contains extra files, unable to remove', torrent.directory)

        # Prefer adapter removal by hash when available
        if self._rt_adapter:
            self._rt_adapter.remove_torrent(release_download['id'])
        else:
            torrent.erase() # just removes the torrent, doesn't delete data

        return True


config = [{
    'name': 'rtorrent',
    'groups': [
        {
            'tab': 'downloaders',
            'list': 'download_providers',
            'name': 'rtorrent',
            'label': 'rTorrent',
            'description': 'Use <a href="https://rakshasa.github.io/rtorrent/" target="_blank">rTorrent</a> to download torrents.',
            'wizard': True,
            'options': [
                {
                    'name': 'enabled',
                    'default': 0,
                    'type': 'enabler',
                    'radio_group': 'torrent',
                },
                {
                    'name': 'ssl',
                    'label': 'SSL Enabled',
                    'order': 1,
                    'default': 0,
                    'type': 'bool',
                    'advanced': True,
                    'description': 'Use HyperText Transfer Protocol Secure, or <strong>https</strong>',
                },
                {
                    'name': 'ssl_verify',
                    'label': 'SSL Verify',
                    'order': 2,
                    'default': 1,
                    'type': 'bool',
                    'advanced': True,
                    'description': 'Verify SSL certificate on https connections',
                },
                {
                    'name': 'ssl_ca_bundle',
                    'label': 'SSL CA Bundle',
                    'order': 3,
                    'type': 'string',
                    'advanced': True,
                    'description': 'Path to a directory (or file) containing trusted certificate authorities',
                },
                {
                    'name': 'host',
                    'order': 4,
                    'default': 'localhost:80',
                    'description': 'RPC Communication URI. Usually <strong>scgi://localhost:5000</strong>, '
                                   '<strong>httprpc://localhost/rutorrent</strong> or <strong>localhost:80</strong>',
                },
                {
                    'name': 'rpc_url',
                    'order': 5,
                    'default': 'RPC2',
                    'type': 'string',
                    'advanced': True,
                    'description': 'Change if your RPC mount is at a different path.',
                },
                {
                    'name': 'authentication',
                    'order': 6,
                    'default': 'basic',
                    'type': 'dropdown',
                    'advanced': True,
                    'values': [('Basic', 'basic'), ('Digest', 'digest')],
                    'description': 'Authentication method used for http(s) connections',
                },
                {
                    'name': 'username',
                    'order': 7,
                },
                {
                    'name': 'password',
                    'order': 8,
                    'type': 'password',
                },
                {
                    'name': 'label',
                    'order': 9,
                    'description': 'Label to apply on added torrents.',
                },
                {
                    'name': 'directory',
                    'order': 10,
                    'type': 'directory',
                    'description': 'Download to this directory. Keep empty for default rTorrent download directory.',
                },
                {
                    'name': 'remove_complete',
                    'label': 'Remove torrent',
                    'order': 11,
                    'default': False,
                    'type': 'bool',
                    'advanced': True,
                    'description': 'Remove the torrent after it finishes seeding.',
                },
                {
                    'name': 'delete_files',
                    'label': 'Remove files',
                    'order': 12,
                    'default': True,
                    'type': 'bool',
                    'advanced': True,
                    'description': 'Also remove the leftover files.',
                },
                {
                    'name': 'paused',
                    'order': 13,
                    'type': 'bool',
                    'advanced': True,
                    'default': False,
                    'description': 'Add the torrent paused.',
                },
                {
                    'name': 'manual',
                    'order': 14,
                    'default': 0,
                    'type': 'bool',
                    'advanced': True,
                    'description': 'Disable this downloader for automated searches, but use it when I manually send a release.',
                },
            ],
        }
    ],
}]
