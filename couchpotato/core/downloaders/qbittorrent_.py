from base64 import b16encode, b32decode
from hashlib import sha1
from datetime import timedelta
import os
import re

import qbittorrentapi
from bencodepy import encode as bencode, decode as bdecode
from couchpotato.core._base.downloader.main import DownloaderBase, ReleaseDownloadList
from couchpotato.core.helpers.encoding import sp
from couchpotato.core.helpers.variable import cleanHost
from couchpotato.core.logger import CPLog


log = CPLog(__name__)

autoload = 'qBittorrent'


class qBittorrent(DownloaderBase):

    protocol = ['torrent', 'torrent_magnet']
    qb = None

    def __init__(self):
        super().__init__()

    def connect(self, reconnect = False):
        """ Create (or reuse) the qBittorrent client and make sure it's
        authenticated.

        The client/session is created once and reused across calls instead
        of reconnecting (logging in) for every single operation: modern
        qBittorrent bans an IP after repeated failed logins, so hammering the
        login endpoint on every download/status/pause/delete call is
        actively harmful. ``is_logged_in`` performs a cheap authenticated
        call to check whether the existing session cookie is still valid and
        only triggers a fresh ``auth_log_in()`` when it isn't (e.g. the
        session expired or this is the first call).

        :param reconnect: force a brand new client (and log out the old
            session first). Used by ``test()`` so a connection test always
            reflects the current host/username/password settings instead of
            a stale client from before the user last changed them.
        :return: bool
        """

        if reconnect and self.qb is not None:
            try:
                self.qb.auth_log_out()
            except qbittorrentapi.APIError:
                pass
            self.qb = None

        if self.qb is None:
            url = cleanHost(self.conf('host'), protocol = True, ssl = False)
            self.qb = qbittorrentapi.Client(
                host = url,
                username = self.conf('username') or None,
                password = self.conf('password') or None,
            )

        if self.qb.is_logged_in:
            return True

        try:
            self.qb.auth_log_in()
            return True
        except qbittorrentapi.APIError as e:
            log.error('Failed to authenticate with qBittorrent: %s', e)
            return False

    def test(self):
        """ Check if connection works
        :return: bool
        """
        return self.connect(reconnect = True)

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

        log.debug('Sending "%s" to qBittorrent.', data.get('name'))

        if not self.connect():
            return False

        if not filedata and data.get('protocol') == 'torrent':
            log.error('Failed sending torrent, no data')
            return False

        # Add the torrent paused if requested, honoring the 'paused' setting
        # (the old vendored v1 client had no way to do this at all - the
        # torrent was always added started).
        is_stopped = self.conf('paused')

        if data.get('protocol') == 'torrent_magnet':
            # Extract the info-hash from the magnet BEFORE the API call so a
            # malformed magnet (no urn:btih:) fails with a specific, logged
            # error rather than an uncaught IndexError bubbling up to
            # fireEvent's blanket handler.
            hash_match = re.findall(r'urn:btih:([\w]{32,40})', data.get('url') or '')
            if not hash_match:
                log.error('Failed to send torrent to qBittorrent: no info-hash in magnet URL "%s"', data.get('url'))
                return False
            torrent_hash = hash_match[0].upper()

            # Send request to qBittorrent directly as a magnet. A genuine add
            # failure surfaces as a typed qbittorrentapi.APIError (e.g.
            # Conflict409Error), caught below.
            try:
                self.qb.torrents_add(
                    urls = data.get('url'),
                    category = self.conf('label'),
                    is_stopped = is_stopped,
                )
                log.info('Torrent [magnet] sent to QBittorrent successfully.')
                return self.downloadReturnId(torrent_hash)

            except qbittorrentapi.APIError as e:
                log.error('Failed to send torrent to qBittorrent: %s', e)
                return False

        if data.get('protocol')  == 'torrent':
             info = bdecode(filedata)["info"]
             torrent_hash = sha1(bencode(info)).hexdigest()

             # Convert base 32 to hex
             if len(torrent_hash) == 32:
                torrent_hash = b16encode(b32decode(torrent_hash))

             # Send request to qBittorrent. A genuine add failure surfaces as
             # a typed qbittorrentapi.APIError, caught below.
             try:
                self.qb.torrents_add(
                    torrent_files = filedata,
                    category = self.conf('label'),
                    is_stopped = is_stopped,
                )
                log.info('Torrent [file] sent to QBittorrent successfully.')
                return self.downloadReturnId(torrent_hash)
             except qbittorrentapi.APIError as e:
                log.error('Failed to send torrent to qBittorrent: %s', e)
                return False

    def getTorrentStatus(self, torrent):

        # qBittorrent 5.0 (Web API v2.11.0) renamed the *UP states: pausedUP
        # became stoppedUP. Both are included here so this keeps working
        # whichever qBittorrent version is on the other end.
        if torrent['state'] in ('uploading', 'queuedUP', 'stalledUP', 'stoppedUP', 'forcedUP'):
            return 'seeding'

        if torrent['progress'] == 1:
            return 'completed'

        return 'busy'

    def getAllDownloadStatus(self, ids):
        """ Get status of all active downloads

        :param ids: list of (mixed) downloader ids
            Used to match the releases for this downloader as there could be
            other downloaders active that it should ignore
        :return: list of releases
        """

        log.debug('Checking qBittorrent download status.')

        if not self.connect():
            return []

        try:
            torrents = self.qb.torrents_info(status_filter = 'all', category = self.conf('label'))

            release_downloads = ReleaseDownloadList(self)

            for torrent in torrents:
                if torrent['hash'] in ids:
                    torrent_filelist = self.qb.torrents_files(torrent_hash = torrent['hash'])

                    torrent_files = []
                    torrent_dir = os.path.join(torrent['save_path'], torrent['name'])

                    if os.path.isdir(torrent_dir):
                        torrent['save_path'] = torrent_dir

                    if len(torrent_filelist) > 1 and os.path.isdir(torrent_dir): # multi file torrent, path.isdir check makes sure we're not in the root download folder
                        for root, _, files in os.walk(torrent['save_path']):
                            for f in files:
                                torrent_files.append(sp(os.path.join(root, f)))

                    else: # multi or single file placed directly in torrent.save_path
                        for f in torrent_filelist:
                            file_path = os.path.join(torrent['save_path'], f['name'])
                            if os.path.isfile(file_path):
                                torrent_files.append(sp(file_path))

                    release_downloads.append({
                        'id': torrent['hash'],
                        'name': torrent['name'],
                        'status': self.getTorrentStatus(torrent),
                        'seed_ratio': torrent['ratio'],
                        'original_status': torrent['state'],
                        'timeleft': str(timedelta(seconds = torrent['eta'])),
                        'folder': sp(torrent['save_path']),
                        'files': torrent_files
                    })

            return release_downloads

        except qbittorrentapi.APIError as e:
            log.error('Failed to get status from qBittorrent: %s', e)
            return []

    def _getTorrent(self, torrent_hash):
        """ Look up a single torrent by hash.
        :return: the torrent dict, or None if it doesn't exist (or on error)
        """
        try:
            torrents = self.qb.torrents_info(torrent_hashes = torrent_hash)
        except qbittorrentapi.APIError as e:
            log.error('Failed to look up torrent in qBittorrent: %s', e)
            return None

        return torrents[0] if torrents else None

    def pause(self, release_download, pause = True):
        if not self.connect():
            return False

        torrent = self._getTorrent(release_download['id'])
        if torrent is None:
            return False

        try:
            if pause:
                self.qb.torrents_pause(torrent_hashes = release_download['id'])
            else:
                self.qb.torrents_resume(torrent_hashes = release_download['id'])
            return True
        except qbittorrentapi.APIError as e:
            log.error('Failed to %s torrent in qBittorrent: %s', 'pause' if pause else 'resume', e)
            return False

    def removeFailed(self, release_download):
        log.info('%s failed downloading, deleting...', release_download['name'])
        return self.processComplete(release_download, delete_files = True)

    def processComplete(self, release_download, delete_files):
        log.debug('Requesting qBittorrent to remove the torrent %s%s.',
                  (release_download['name'], ' and cleanup the downloaded files' if delete_files else ''))

        if not self.connect():
            return False

        torrent = self._getTorrent(release_download['id'])

        if torrent is None:
            return False

        try:
            # delete_files=True also deletes the downloaded data; False just
            # removes the torrent from qBittorrent's list
            self.qb.torrents_delete(delete_files = delete_files, torrent_hashes = release_download['id'])
            return True
        except qbittorrentapi.APIError as e:
            log.error('Failed to remove torrent from qBittorrent: %s', e)
            return False


config = [{
    'name': 'qbittorrent',
    'groups': [
        {
            'tab': 'downloaders',
            'list': 'download_providers',
            'name': 'qbittorrent',
            'label': 'qBittorrent',
            'description': 'Use <a href="http://www.qbittorrent.org/" target="_blank">qBittorrent</a> to download torrents.',
            'wizard': True,
            'options': [
                {
                    'name': 'enabled',
                    'default': 0,
                    'type': 'enabler',
                    'radio_group': 'torrent',
                },
                {
                    'name': 'host',
                    'default': 'http://localhost:8080/',
                    'description': 'RPC Communication URI. Usually <strong>http://localhost:8080/</strong>'
                },
                {
                    'name': 'username',
                },
                {
                    'name': 'password',
                    'type': 'password',
                },
                {
                    'name': 'label',
                    'label': 'Torrent Label',
                    'default': 'couchpotato',
                },
                {
                    'name': 'remove_complete',
                    'label': 'Remove torrent',
                    'default': False,
                    'advanced': True,
                    'type': 'bool',
                    'description': 'Remove the torrent after it finishes seeding.',
                },
                {
                    'name': 'delete_files',
                    'label': 'Remove files',
                    'default': True,
                    'type': 'bool',
                    'advanced': True,
                    'description': 'Also remove the leftover files.',
                },
                {
                    'name': 'paused',
                    'type': 'bool',
                    'advanced': True,
                    'default': False,
                    'description': 'Add the torrent paused.',
                },
                {
                    'name': 'manual',
                    'default': 0,
                    'type': 'bool',
                    'advanced': True,
                    'description': 'Disable this downloader for automated searches, but use it when I manually send a release.',
                },
            ],
        }
    ],
}]
