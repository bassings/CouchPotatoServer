import os
import threading
import time
import traceback

from couchpotato import get_db
from couchpotato.api import addApiView
from couchpotato.core.event import fireEvent, addEvent, fireEventAsync
from couchpotato.core.helpers.encoding import sp
from couchpotato.core.helpers.variable import splitString, getTitle, tryInt, getIdentifier, getFreeSpace
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.environment import Env


log = CPLog(__name__)

autoload = 'Manage'


class Manage(Plugin):

    in_progress = False
    _progress_lock = None  # initialized in __init__

    def __init__(self):
        self._progress_lock = threading.Lock()

        # A fireEvent('scheduler.interval', ...) call used to sit here. The
        # event is 'schedule.interval' (singular), so it scheduled nothing.
        # Removed rather than corrected: setCrons() below already registers
        # this job with the user's configured library_refresh_interval, and
        # only when it is > 0. Fixing the typo would have forced a hardcoded
        # 2-hour rescan that overrides the user's ability to turn it off.
        addEvent('manage.update', self.updateLibrary)
        addEvent('manage.diskspace', self.getDiskSpace)

        # Add files after renaming
        def after_rename(message = None, group = None):
            if not group: group = {}
            return self.scanFilesToLibrary(folder = group['destination_dir'], files = group['renamed_files'], release_download = group['release_download'])
        addEvent('renamer.after', after_rename, priority = 110)

        addApiView('manage.update', self.updateLibraryView, docs = {
            'desc': 'Update the library by scanning for new movies',
            'params': {
                'full': {'desc': 'Do a full update or just recently changed/added movies.'},
            }
        })

        addApiView('manage.progress', self.getProgress, docs = {
            'desc': 'Get the progress of current manage update',
            'return': {'type': 'object', 'example': """{
    'progress': False || object, total & to_go,
}"""},
        })

        if not Env.get('dev') and self.conf('startup_scan'):
            addEvent('app.load', self.updateLibraryQuick)

        addEvent('app.load', self.setCrons)

        # Enable / disable interval
        addEvent('setting.save.manage.library_refresh_interval.after', self.setCrons)

    def setCrons(self):

        fireEvent('schedule.remove', 'manage.update_library')
        refresh = tryInt(self.conf('library_refresh_interval'))
        if refresh > 0:
            fireEvent('schedule.interval', 'manage.update_library', self.updateLibrary, hours = refresh, single = True)

        return True

    def getProgress(self, **kwargs):
        return {
            'progress': self.in_progress
        }

    def updateLibraryView(self, full = 1, **kwargs):

        fireEventAsync('manage.update', full = True if full == '1' else False)

        return {
            'progress': self.in_progress,
            'success': True
        }

    def updateLibraryQuick(self):
        return self.updateLibrary(full = False)

    def updateLibrary(self, full = True):
        last_update_key = 'manage.last_update%s' % ('_full' if full else '')
        last_update = float(Env.prop(last_update_key, default = 0))

        with self._progress_lock:
            if self.in_progress:
                log.info('Already updating library: %s', self.in_progress)
                return
            elif self.isDisabled() or (last_update > time.time() - 20):
                return
            self.in_progress = {}
        fireEvent('notify.frontend', type = 'manage.updating', data = True)

        try:

            directories = self.directories()
            directories.sort()
            added_identifiers = []

            # Did this scan actually SEE the whole library?
            #
            # The cleanup pass below deletes every terminal movie that is not in
            # `added_identifiers`, with delete_from='all' -- media document,
            # every release document, library entry, watch state, tags, profile
            # and review state. It infers "this movie is gone" from "this scan
            # did not find it", and that inference is only sound if the scan
            # could see everywhere the movie might be.
            #
            # A directory that fails os.path.isdir below is logged and skipped,
            # and nothing recorded that. So an unmounted NAS at scan time made
            # `added_identifiers` empty and the cleanup purged the library. Not
            # hypothetical on the hardware this runs on: the library sits on an
            # NFS mount known to stall and drop, and full scans are scheduled,
            # so the two coincide unattended and nobody is watching.
            #
            # Starts False for an EMPTY directory list: no configured library
            # means nothing to compare against, so every movie looks missing.
            library_fully_scanned = bool(directories)
            # Directories that EXISTED and scanned cleanly but yielded nothing.
            empty_directories = []

            # Add some progress
            for directory in directories:
                self.in_progress[os.path.normpath(directory)] = {
                    'started': False,
                    'eta': -1,
                    'total': None,
                    'to_go': None,
                }

            for directory in directories:
                folder = os.path.normpath(directory)
                self.in_progress[os.path.normpath(directory)]['started'] = tryInt(time.time())

                if not os.path.isdir(folder):
                    # NOT just a skip: this is what disarms the cleanup below.
                    library_fully_scanned = False
                    if len(directory) > 0:
                        log.error('Directory doesn\'t exist: %s', folder)
                    continue

                log.info('Updating manage library: %s', folder)
                fireEvent('notify.frontend', type = 'manage.update', data = True, message = 'Scanning for movies in "%s"' % folder)

                before = len(added_identifiers)
                onFound = self.createAddToLibrary(folder, added_identifiers)
                fireEvent('scanner.scan', folder = folder, simple = True, newer_than = last_update if not full else 0, check_file_date = False, on_found = onFound, single = True)

                # PER DIRECTORY, not across the library as a whole.
                #
                # `library` is explicitly a multi-folder setting ("You can add
                # multiple folders separated by ::"), and a single global
                # "did we find anything" boolean does not cover it. With
                # `/mnt/nas/movies :: /srv/kids`, the NAS dropping to an empty
                # mountpoint while /srv/kids scans fine leaves the global flag
                # TRUE -- so the cleanup ran and deleted every done movie on the
                # NAS half of the library. The guard was measured and fixed for
                # the single-directory case only.
                if len(added_identifiers) == before:
                    empty_directories.append(folder)

                # Break if CP wants to shut down
                if self.shuttingDown():
                    break

            # A scan that FOUND NOTHING is not evidence that nothing is there.
            #
            # `library_fully_scanned` only disarms when `os.path.isdir` fails,
            # and that misses the dominant mount-failure shape: an unmounted NFS
            # mountpoint, a failed automount and a Docker bind mount with a
            # missing host path all present as a directory that EXISTS and is
            # EMPTY. `isdir` returns True, the scan finds nothing,
            # `added_identifiers` is empty, and the cleanup below then reads
            # "every movie is missing" and deletes all of them.
            #
            # Measured against this exact function: directory missing deleted
            # nothing; directory existing-but-empty deleted every done movie.
            # That is the scenario the guard was added for, in its most likely
            # form, and the guard did not cover it.
            #
            # The cost of this check is real and accepted: a library whose files
            # were all genuinely deleted stops being cleaned up automatically,
            # leaving stale rows the user removes by hand. Weighed against
            # `media.delete(delete_from='all')` destroying watch history, tags,
            # profile and review state for every done movie -- unrecoverable
            # without a backup, and nobody takes one before a scheduled scan --
            # the inconvenient failure is the correct one to choose.
            # EVERY configured directory must have contributed something.
            #
            # `not empty_directories`, not `len(added_identifiers) > 0`: one
            # healthy folder must not vouch for a sibling that came back empty,
            # because the cleanup deletes across the WHOLE library and cannot
            # tell which folder a missing movie belonged to.
            #
            # KNOWN LIMIT, recorded rather than implied: this detects a
            # directory that yielded NOTHING. It cannot see a PARTIAL scan --
            # `scanner.scan` exceptions are swallowed by the event dispatcher,
            # and an unreadable subtree or a nested unmounted sub-mount returns
            # a truncated list that still looks like a successful scan. Closing
            # that needs the scanner to report completeness, which is its own
            # change.
            found_everywhere = not empty_directories
            if self.conf('cleanup') and full and not self.shuttingDown() \
                    and library_fully_scanned and not found_everywhere:
                # NOT silent. The safety catch previously disarmed with no log
                # line at all, so an operator could not tell that cleanup had
                # stopped running, or why -- and a cleanup that quietly never
                # runs looks identical to one with nothing to do. Name the
                # directories: with several configured, "something was empty" is
                # not actionable.
                log.warning('Skipping library cleanup: %s of %s configured '
                            'director%s scanned but contained no movies (%s). '
                            'That is what an unmounted or empty library folder '
                            'looks like, and deleting movies on that basis is '
                            'not recoverable. Nothing was removed. If that '
                            'folder is meant to be empty, remove it from '
                            'Settings > Library > Library Folders and cleanup '
                            'will resume; otherwise check the mount.',
                            len(empty_directories), len(directories),
                            'y' if len(directories) == 1 else 'ies',
                            ', '.join(empty_directories))

            # If cleanup option is enabled, remove offline files from database
            if self.conf('cleanup') and full and not self.shuttingDown() \
                    and library_fully_scanned and found_everywhere:

                # Get movies with done status
                total_movies, done_movies = fireEvent('media.list', types = 'movie', status = 'done', release_status = 'done', status_or = True, single = True)

                deleted_releases = []
                for done_movie in done_movies:
                    # Only a movie whose MEDIA status is genuinely terminal is
                    # this scan's to delete.
                    #
                    # The query above is a status_or union: status='done' OR
                    # release_status='done'. The second half admits movies whose
                    # media status is something else entirely:
                    #
                    #   'downloaded' -- the workflow phase 2 review gate, still
                    #                   awaiting manual review.
                    #   'active'     -- the ordinary upgrade-hunt state. A movie
                    #                   holding a finished release that does not
                    #                   satisfy quality.isFinish (grabbed the
                    #                   720p, still hunting the 1080p) stays
                    #                   'active' indefinitely.
                    #
                    # Neither is offline or missing. This exempted only
                    # 'downloaded', which was survivable purely because the
                    # release_status half of the union returned NOTHING:
                    # Release.withStatus dropped with_doc, so media_id was always
                    # None and the filter set was {None}. T1.9 fixed that lookup,
                    # made this half live for the first time, and turned the
                    # missing 'active' exemption into a real delete.
                    #
                    # media.delete(delete_from='all') removes every release
                    # document and the media document: library entry, watch
                    # state, tags, profile and review state. Unrecoverable
                    # without a backup, and nobody takes one before a scheduled
                    # library scan.
                    if done_movie.get('status') != 'done':
                        continue

                    if getIdentifier(done_movie) not in added_identifiers:
                        fireEvent('media.delete', media_id = done_movie['_id'], delete_from = 'all')
                    else:

                        releases = done_movie.get('releases', [])

                        for release in releases:
                            if release.get('files'):
                                brk = False
                                for file_type in release.get('files', {}):
                                    for release_file in release['files'][file_type]:
                                        # Remove release not available anymore
                                        if not os.path.isfile(sp(release_file)):
                                            fireEvent('release.clean', release['_id'])
                                            brk = True
                                            break
                                    if brk:
                                        break

                        # Check if there are duplicate releases (different quality) use the last one, delete the rest
                        if len(releases) > 1:
                            used_files = {}
                            for release in releases:
                                for file_type in release.get('files', {}):
                                    for release_file in release['files'][file_type]:
                                        already_used = used_files.get(release_file)

                                        if already_used:
                                            release_id = release['_id'] if already_used.get('last_edit', 0) > release.get('last_edit', 0) else already_used['_id']
                                            if release_id not in deleted_releases:
                                                fireEvent('release.delete', release_id, single = True)
                                                deleted_releases.append(release_id)
                                            break
                                        else:
                                            used_files[release_file] = release
                            del used_files

                    # Break if CP wants to shut down
                    if self.shuttingDown():
                        break

            # No reindex here any more. `db.reindex()` took a required
            # `index_name` nobody passed, so it raised TypeError -- caught by
            # the `except` below, which logged "Failed updating library" and
            # skipped the line immediately after it. That line is the
            # COMPLETION TIMESTAMP, so every full scan reported failure and
            # recorded nothing, and the next scan repeated the entire library
            # walk. SQLite maintains its indexes itself; there was never any
            # work to do here.
            Env.prop(last_update_key, time.time())
        except Exception:
            log.error('Failed updating library: %s', traceback.format_exc())

        while self.in_progress and len(self.in_progress) > 0 and not self.shuttingDown():

            delete_me = {}

            # noinspection PyTypeChecker
            for folder in self.in_progress:
                if (self.in_progress[folder]['to_go'] or 0) <= 0:
                    delete_me[folder] = True

            for delete in delete_me:
                del self.in_progress[delete]

            time.sleep(1)

        fireEvent('notify.frontend', type = 'manage.updating', data = False)
        self.in_progress = False

    def createAddToLibrary(self, folder, added_identifiers = None):
        if added_identifiers is None:
            added_identifiers = []

        def addToLibrary(group, total_found, to_go):
            if self.in_progress[folder]['total'] is None:
                self.in_progress[folder].update({
                    'total': total_found,
                    'to_go': total_found,
                })

            self.updateProgress(folder, to_go)

            if group['media'] and group['identifier']:
                added_identifiers.append(group['identifier'])

                # Add it to release and update the info
                fireEvent('release.add', group = group, update_info = False)
                fireEvent('movie.update', identifier = group['identifier'], on_complete = self.createAfterUpdate(folder, group['identifier']))

        return addToLibrary

    def createAfterUpdate(self, folder, identifier):

        # Notify frontend
        def afterUpdate():
            if not self.in_progress or self.shuttingDown():
                return

            total = self.in_progress[folder]['total']
            movie_dict = fireEvent('media.get', identifier, single = True)

            if movie_dict:
                fireEvent('notify.frontend', type = 'movie.added', data = movie_dict, message = None if total > 5 else 'Added "%s" to manage.' % getTitle(movie_dict))

        return afterUpdate

    def updateProgress(self, folder, to_go):

        pr = self.in_progress[folder]
        if to_go < pr['to_go']:
            pr['to_go'] = to_go

        avg = (time.time() - pr['started']) / (pr['total'] - pr['to_go'])
        pr['eta'] = tryInt(avg * pr['to_go'])


    def directories(self):
        try:
            return self.conf('library', default = [])
        except Exception:
            pass

        return []

    def scanFilesToLibrary(self, folder = None, files = None, release_download = None):

        folder = os.path.normpath(folder)

        groups = fireEvent('scanner.scan', folder = folder, files = files, single = True)

        if groups:
            for group in groups.values():
                if group.get('media'):
                    if release_download and release_download.get('release_id'):
                        fireEvent('release.add', group = group, update_id = release_download.get('release_id'))
                    else:
                        fireEvent('release.add', group = group)

    def getDiskSpace(self):
        return getFreeSpace(self.directories())


config = [{
    'name': 'manage',
    'groups': [
        {
            'tab': 'manage',
            'label': 'Movie Library',
            'description': 'Tell CouchPotato where your movie collection lives.',
            'options': [
                {
                    'name': 'enabled',
                    'default': False,
                    'type': 'enabler',
                },
                {
                    'name': 'library',
                    'type': 'directories',
                    'label': 'Library Folders',
                    'description': 'Folders containing your movie files. You can add multiple folders separated by :: (double colon).',
                },
                {
                    'label': 'Scan Interval (hours)',
                    'name': 'library_refresh_interval',
                    'type': 'int',
                    'default': 0,
                    'description': 'Automatically scan your library every X hours. Set to 0 to disable.',
                },
                {
                    'label': 'Scan at Startup',
                    'name': 'startup_scan',
                    'type': 'bool',
                    'default': True,
                    'description': 'Run a quick scan when CouchPotato starts.',
                },
                {
                    'label': 'Remove Missing Movies',
                    'name': 'cleanup',
                    'type': 'bool',
                    'description': 'Remove movies from the database if their files can no longer be found.',
                    'default': True,
                },
            ],
        },
    ],
}]
