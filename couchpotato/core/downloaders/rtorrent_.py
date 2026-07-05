import time
import xmlrpc.client
from base64 import b16encode, b32decode
from datetime import timedelta
from hashlib import sha1
from urllib.parse import urlparse, urlunparse
import os
import re

import requests
import requests.auth
import rtorrent_rpc

from couchpotato.core._base.downloader.main import DownloaderBase, ReleaseDownloadList
from couchpotato.core.event import addEvent
from couchpotato.core.helpers.encoding import sp
from couchpotato.core.helpers.variable import cleanHost, splitString
from couchpotato.core.logger import CPLog
from bencodepy import encode as bencode, decode as bdecode


log = CPLog(__name__)

autoload = 'rTorrent'

# Fields fetched (in this exact order) for every torrent by get_torrents().
# Matches what getAllDownloadStatus()/getTorrentStatus() below read off each
# returned torrent object.
_MULTICALL_FIELDS = (
    'd.hash=',
    'd.name=',
    'd.complete=',
    'd.is_open=',
    'd.ratio=',
    'd.state=',
    'd.left_bytes=',
    'd.down.rate=',
    'd.directory=',
)

# Poll settings used while waiting for a just-added magnet/torrent to show
# up in rTorrent's download list.
_LOAD_POLL_INTERVAL = 1
_SCGI_TIMEOUT = 30


def _rewrite_httprpc_url(url):
    """ Rewrite CouchPotato's 'httprpc(+https)' pseudo-scheme to ruTorrent's
    httprpc plugin's fixed mount point, preserving host/port and any existing
    path prefix (e.g. a ruTorrent install mounted under a sub-path).

    httprpc://host       -> http://host/plugins/httprpc/action.php
    httprpc://host/path  -> http://host/path/plugins/httprpc/action.php
    httprpc+https://host -> https://host/plugins/httprpc/action.php
    """

    parsed = urlparse(url)

    if parsed.scheme == 'httprpc':
        transport_scheme = 'http'
    elif parsed.scheme == 'httprpc+https':
        transport_scheme = 'https'
    else:
        return url

    path = parsed.path.rstrip('/')
    new_path = (path + '/plugins/httprpc/action.php') if path else '/plugins/httprpc/action.php'

    return urlunparse((transport_scheme, parsed.netloc, new_path, parsed.params, parsed.query, parsed.fragment))


class _RTorrentAuthTransport(xmlrpc.client.Transport):
    """ XML-RPC transport for http(s) rTorrent endpoints, backed by
    ``requests``.

    rtorrent_rpc's public API (RTorrent/_HTTPTransport) has no way to
    configure per-instance basic/digest authentication or per-instance TLS
    verification (its only option is a process-wide environment variable
    that disables cert checking globally) so we drive our own
    ``requests.Session``-backed transport for every http(s) connection.
    """

    def __init__(self, secure, auth = None, verify_ssl = True):
        super().__init__()

        self.secure = secure
        self.session = requests.Session()

        if auth:
            auth_method, username, password = auth
            if auth_method == 'digest':
                self.session.auth = requests.auth.HTTPDigestAuth(username, password)
            else:
                self.session.auth = requests.auth.HTTPBasicAuth(username, password)

        self.session.verify = verify_ssl

    def single_request(self, host, handler, request_body, verbose = 0):
        url = '%s://%s%s' % ('https' if self.secure else 'http', host, handler)

        response = self.session.post(
            url,
            data = request_body,
            headers = {'Content-Type': 'text/xml'},
            stream = True,
        )

        if response.status_code != 200:
            raise xmlrpc.client.ProtocolError(
                host + handler, response.status_code, response.reason, response.headers
            )

        p, u = self.getparser()
        for chunk in response.iter_content(1024):
            p.feed(chunk)
        p.close()

        return u.close()


class _RTorrentFile:
    """ A single file belonging to a torrent (only what CP reads: `.path`). """

    def __init__(self, path):
        self.path = path


class _RTorrentTorrent:
    """ Lightweight view over a single rTorrent download, backed by direct
    ``d.*``/``f.*`` RPC calls keyed on `info_hash`. """

    def __init__(self, rpc, info_hash, name, complete, open_, ratio, state,
                 left_bytes, down_rate, directory):
        self._rpc = rpc

        self.info_hash = info_hash
        self.name = name
        self.complete = complete
        self.open = open_
        self.ratio = ratio
        self.state = state
        self.left_bytes = left_bytes
        self.down_rate = down_rate
        self.directory = directory

    def get_files(self):
        rows = self._rpc.f.multicall(self.info_hash, '', 'f.path=')
        return [_RTorrentFile(row[0]) for row in rows]

    def set_custom(self, key, value):
        return getattr(self._rpc.d, 'custom%s' % key).set(self.info_hash, value)

    def set_directory(self, directory):
        return self._rpc.d.directory.set(self.info_hash, directory)

    def start(self):
        return self._rpc.d.start(self.info_hash)

    def pause(self):
        # CP's "pause" maps to rTorrent's "stop" (mirrors the vendored lib's
        # naming, which is confusing, but is the existing contract).
        return self._rpc.d.stop(self.info_hash)

    def resume(self):
        return self._rpc.d.start(self.info_hash)

    def erase(self):
        # Only removes rTorrent's internal tracking; CP deletes files itself.
        return self._rpc.d.erase(self.info_hash)

    def is_multi_file(self):
        return bool(int(self._rpc.d.is_multi_file(self.info_hash)))


class _RTorrentAdapter:
    """ Thin wrapper around an rTorrent XML-RPC endpoint, built on top of
    `rtorrent_rpc` (scgi://, scgi:///path) or a custom requests-backed
    transport (http://, https://) -- exposing only the operations
    CouchPotato's rTorrent downloader plugin needs. This insulates CP from
    churn in the small library's ruTorrent-flavoured convenience API, which
    CP doesn't use. """

    def __init__(self, url, auth = None, verify_ssl = True):
        parsed = urlparse(url)

        if parsed.scheme == 'scgi':
            self.rpc = rtorrent_rpc.RTorrent(url, timeout = _SCGI_TIMEOUT).rpc
        elif parsed.scheme in ('http', 'https'):
            transport = _RTorrentAuthTransport(
                secure = parsed.scheme == 'https',
                auth = auth,
                verify_ssl = verify_ssl,
            )
            self.rpc = xmlrpc.client.ServerProxy(url, transport = transport)
        else:
            raise ValueError('Unsupported rTorrent RPC scheme: %r' % parsed.scheme)

    def get_torrents(self):
        rows = self.rpc.d.multicall2('', 'main', *_MULTICALL_FIELDS)

        torrents = []
        for info_hash, name, complete, is_open, ratio, state, left_bytes, down_rate, directory in rows:
            torrents.append(_RTorrentTorrent(
                self.rpc,
                info_hash = str(info_hash).upper(),
                name = name,
                complete = bool(int(complete)),
                open_ = bool(int(is_open)),
                ratio = int(ratio) / 1000.0,
                state = state,
                left_bytes = left_bytes,
                down_rate = down_rate,
                directory = directory,
            ))

        return torrents

    def find_torrent(self, info_hash):
        info_hash = str(info_hash).upper()
        for torrent in self.get_torrents():
            if torrent.info_hash == info_hash:
                return torrent

        return None

    def _poll_for_torrent(self, info_hash, retries):
        for attempt in range(retries):
            torrent = self.find_torrent(info_hash)
            if torrent:
                return torrent
            if attempt < retries - 1:
                time.sleep(_LOAD_POLL_INTERVAL)

        return None

    def load_magnet(self, magnet_url, info_hash, verify_retries = 10):
        self.rpc.load.start('', magnet_url)
        return self._poll_for_torrent(info_hash, verify_retries)

    def load_torrent(self, filedata, info_hash, verify_retries = 10):
        self.rpc.load.raw('', xmlrpc.client.Binary(filedata))
        return self._poll_for_torrent(info_hash, verify_retries)


class rTorrent(DownloaderBase):

    protocol = ['torrent', 'torrent_magnet']
    rt = None
    error_msg = ''

    # Migration url to host options
    def __init__(self):
        super().__init__()

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
        if not reconnect and self.rt is not None:
            return self.rt

        url = cleanHost(self.conf('host'), protocol = True, ssl = self.conf('ssl'))

        # Automatically add '+https' to 'httprpc' protocol if SSL is enabled
        if self.conf('ssl') and url.startswith('httprpc://'):
            url = url.replace('httprpc://', 'httprpc+https://')

        is_httprpc = url.startswith('httprpc://') or url.startswith('httprpc+https://')
        url = _rewrite_httprpc_url(url)

        parsed = urlparse(url)

        # rpc_url is only used on the plain http/https scgi pass-through
        # case, not httprpc (ruTorrent's fixed mount point) or scgi (no
        # concept of an RPC path).
        if parsed.scheme in ('http', 'https') and not is_httprpc:
            url += self.conf('rpc_url')

        # Construct client
        self.error_msg = ''
        try:
            self.rt = _RTorrentAdapter(
                url,
                auth = self.getAuth(),
                verify_ssl = self.getVerifySsl(),
            )

            # XML-RPC proxy construction never touches the network, so this
            # is the only way to actually confirm the endpoint is a working
            # rTorrent instance.
            self.rt.rpc.system.client_version()
        except Exception as e:
            self.error_msg = str(e)
            self.rt = None

        return self.rt

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

        log.debug('Sending "%s" to rTorrent.', data.get('name'))

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
            torrent_hash = re.findall(r'urn:btih:([\w]{32,40})', data.get('url'))[0].upper()
            # Send request to rTorrent
            try:
                torrent = self.rt.load_magnet(data.get('url'), torrent_hash)

                if not torrent:
                    log.error('Unable to find the torrent, did it fail to load?')
                    return False

            except Exception as err:
                log.error('Failed to send magnet to rTorrent: %s', err)
                return False

        if data.get('protocol') == 'torrent':
            info = bdecode(filedata)["info"]
            torrent_hash = sha1(bencode(info)).hexdigest().upper()

            # Convert base 32 to hex
            if len(torrent_hash) == 32:
                torrent_hash = b16encode(b32decode(torrent_hash))

            # Send request to rTorrent
            try:
                # Send torrent to rTorrent
                torrent = self.rt.load_torrent(filedata, torrent_hash, verify_retries = 10)

                if not torrent:
                    log.error('Unable to find the torrent, did it fail to load?')
                    return False

            except Exception as err:
                log.error('Failed to send torrent to rTorrent: %s', err)
                return False

        try:
            # Set label
            if self.conf('label'):
                torrent.set_custom(1, self.conf('label'))

            if self.conf('directory'):
                torrent.set_directory(self.conf('directory'))

            # Start torrent
            if not self.conf('paused', default = 0):
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

        try:
            torrents = self.rt.get_torrents()

            release_downloads = ReleaseDownloadList(self)

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
                        'folder': sp(torrent.directory),
                        'files': torrent_files
                    })

            return release_downloads

        except Exception as err:
            log.error('Failed to get status from rTorrent: %s', err)
            return []

    def pause(self, release_download, pause = True):
        if not self.connect():
            return False

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
