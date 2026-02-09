"""Snatched release checking for the renamer."""
import time
import traceback

from couchpotato import get_db
from couchpotato.core.event import fireEvent
from couchpotato.core.helpers.encoding import ss
from couchpotato.core.helpers.variable import sp, getImdb, getIdentifier, isSubFolder
from couchpotato.core.logger import CPLog

log = CPLog(__name__)


class ScannerMixin:
    """Mixin providing snatched-checking methods for the Renamer class."""

    def checkSnatched(self, fire_scan=True):
        if self.checking_snatched:
            log.debug('Already checking snatched')
            return False

        self.checking_snatched = True

        try:
            db = get_db()

            rels = list(fireEvent('release.with_status', ['snatched', 'seeding', 'missing'], single=True))

            if not rels:
                self.checking_snatched = False
                return True

            download_ids = []
            no_status_support = []
            try:
                for rel in rels:
                    if not rel.get('download_info'):
                        continue
                    if rel['download_info'].get('id') and rel['download_info'].get('downloader'):
                        download_ids.append(rel['download_info'])
                    ds = rel['download_info'].get('status_support')
                    if ds is False or ds == 'False':
                        no_status_support.append(ss(rel['download_info'].get('downloader')))
            except Exception:
                log.error('Error getting download IDs from database')
                self.checking_snatched = False
                return False

            release_downloads = fireEvent('download.status', download_ids, merge=True) if download_ids else []

            if len(no_status_support) > 0:
                log.debug('Download status functionality is not implemented for one of the active downloaders: %s', list(set(no_status_support)))

            if not release_downloads:
                if fire_scan:
                    self.scan()
                self.checking_snatched = False
                return True

            scan_releases = []
            scan_required = False

            log.debug('Checking status snatched releases...')

            try:
                for rel in rels:
                    if not rel.get('media_id'):
                        continue
                    movie_dict = db.get('id', rel.get('media_id'))
                    download_info = rel.get('download_info')

                    if not isinstance(download_info, dict):
                        log.error('Faulty release found without any info, ignoring.')
                        fireEvent('release.update_status', rel.get('_id'), status='ignored', single=True)
                        continue

                    if not download_info.get('id') or not download_info.get('downloader'):
                        log.debug('Download status functionality is not implemented for downloader (%s) of release %s.', download_info.get('downloader', 'unknown'), rel['info']['name'])
                        scan_required = True
                        continue

                    nzbname = self.createNzbName(rel['info'], movie_dict)

                    found_release = False
                    for release_download in release_downloads:
                        found_release = False
                        if download_info.get('id'):
                            if release_download['id'] == download_info['id'] and release_download['downloader'] == download_info['downloader']:
                                log.debug('Found release by id: %s', release_download['id'])
                                found_release = True
                                break
                        else:
                            if release_download['name'] == nzbname or rel['info']['name'] in release_download['name'] or getImdb(release_download['name']) == getIdentifier(movie_dict):
                                log.debug('Found release by release name or imdb ID: %s', release_download['name'])
                                found_release = True
                                break

                    if not found_release:
                        if rel.get('status') == 'missing':
                            if rel.get('last_edit') < int(time.time()) - 7 * 24 * 60 * 60:
                                log.info('%s not found in downloaders after 7 days, setting status to ignored', nzbname)
                                fireEvent('release.update_status', rel.get('_id'), status='ignored', single=True)
                        else:
                            log.info('%s not found in downloaders, setting status to missing', nzbname)
                            fireEvent('release.update_status', rel.get('_id'), status='missing', single=True)
                        continue

                    timeleft = 'N/A' if release_download['timeleft'] == -1 else release_download['timeleft']
                    log.debug('Found %s: %s, time to go: %s', release_download['name'], release_download['status'].upper(), timeleft)

                    if release_download['status'] == 'busy':
                        fireEvent('release.update_status', rel.get('_id'), status='snatched', single=True)
                        if self.movieInFromFolder(release_download['folder']):
                            self.tagRelease(release_download=release_download, tag='downloading')

                    elif release_download['status'] == 'seeding':
                        if self.conf('file_action') != 'move' and not rel.get('status') == 'seeding' and self.statusInfoComplete(release_download):
                            log.info('Download of %s completed! It is now being processed while leaving the original files alone for seeding. Current ratio: %s.', release_download['name'], release_download['seed_ratio'])
                            self.untagRelease(release_download=release_download, tag='downloading')
                            release_download.update({'pause': True, 'scan': True, 'process_complete': False})
                            scan_releases.append(release_download)
                        else:
                            log.debug('%s is seeding with ratio: %s', release_download['name'], release_download['seed_ratio'])
                            fireEvent('release.update_status', rel.get('_id'), status='seeding', single=True)

                    elif release_download['status'] == 'failed':
                        fireEvent('release.update_status', rel.get('_id'), status='failed', single=True)
                        fireEvent('download.remove_failed', release_download, single=True)
                        if self.conf('next_on_failed'):
                            fireEvent('movie.searcher.try_next_release', media_id=rel.get('media_id'))

                    elif release_download['status'] == 'completed':
                        log.info('Download of %s completed!', release_download['name'])
                        if self.statusInfoComplete(release_download):
                            if rel.get('status') == 'seeding':
                                if self.conf('file_action') != 'move':
                                    fireEvent('release.update_status', rel.get('_id'), status='downloaded', single=True)
                                    release_download.update({'pause': False, 'scan': False, 'process_complete': True})
                                    scan_releases.append(release_download)
                                else:
                                    release_download.update({'pause': False, 'scan': True, 'process_complete': True})
                                    scan_releases.append(release_download)
                            else:
                                fireEvent('release.update_status', rel.get('_id'), status='snatched', single=True)
                                self.untagRelease(release_download=release_download, tag='downloading')
                                release_download.update({'pause': False, 'scan': True, 'process_complete': True})
                                scan_releases.append(release_download)
                        else:
                            scan_required = True

            except Exception:
                log.error('Failed checking for release in downloader: %s', traceback.format_exc())

            for release_download in scan_releases:
                if release_download['scan']:
                    if release_download['pause'] and self.conf('file_action') in ['link', 'symlink_reversed']:
                        fireEvent('download.pause', release_download=release_download, pause=True, single=True)
                    self.scan(release_download=release_download)
                    if release_download['pause'] and self.conf('file_action') in ['link', 'symlink_reversed']:
                        fireEvent('download.pause', release_download=release_download, pause=False, single=True)
                if release_download['process_complete']:
                    if not self.hastagRelease(release_download=release_download, tag='failed_rename'):
                        self.untagRelease(release_download=release_download, tag='renamed_already')
                        fireEvent('download.process_complete', release_download=release_download, single=True)

            if fire_scan and (scan_required or len(no_status_support) > 0):
                self.scan()

            self.checking_snatched = False
            return True
        except Exception:
            log.error('Failed checking snatched: %s', traceback.format_exc())

        self.checking_snatched = False
        return False

    def extendReleaseDownload(self, release_download):
        rls = None
        db = get_db()

        if release_download and release_download.get('id'):
            try:
                rls = db.get('release_download', '%s-%s' % (release_download.get('downloader'), release_download.get('id')), with_doc=True)['doc']
            except Exception:
                log.error('Download ID %s from downloader %s not found in releases', release_download.get('id'), release_download.get('downloader'))

        if rls:
            media = db.get('id', rls['media_id'])
            release_download.update({
                'imdb_id': getIdentifier(media),
                'quality': rls['quality'],
                'is_3d': rls['is_3d'],
                'protocol': rls.get('info', {}).get('protocol') or rls.get('info', {}).get('type'),
                'release_id': rls['_id'],
            })

        return release_download

    def downloadIsTorrent(self, release_download):
        return release_download and release_download.get('protocol') in ['torrent', 'torrent_magnet']

    def statusInfoComplete(self, release_download):
        return release_download.get('id') and release_download.get('downloader') and release_download.get('folder')

    def movieInFromFolder(self, media_folder):
        return media_folder and isSubFolder(media_folder, sp(self.conf('from'))) or not media_folder

    @property
    def ignored_in_path(self):
        return self.conf('ignored_in_path').split(':') if self.conf('ignored_in_path') else []

    def filesAfterIgnoring(self, original_file_list):
        kept_files = []
        for path in original_file_list:
            if self.keepFile(path):
                kept_files.append(path)
            else:
                log.debug('Ignored "%s" during renaming', path)
        return kept_files
