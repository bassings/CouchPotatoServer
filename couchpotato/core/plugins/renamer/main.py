"""Main Renamer class combining all mixin functionality."""
import os
import traceback

from couchpotato.api import addApiView
from couchpotato import get_db
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.variable import sp
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.core.plugins.renamer.cleanup import CleanupMixin
from couchpotato.core.plugins.renamer.extractor import ExtractorMixin
from couchpotato.core.plugins.renamer.mover import MoverMixin
from couchpotato.core.plugins.renamer.namer import NamerMixin
from couchpotato.core.plugins.renamer.scanner import ScannerMixin

log = CPLog(__name__)


class Renamer(Plugin, ScannerMixin, MoverMixin, NamerMixin, ExtractorMixin, CleanupMixin):
    """Core renamer plugin that scans download folders and renames/moves completed movies."""

    renaming_started = False
    checking_snatched = False

    def __init__(self):

        addApiView('renamer.scan', self.scanView, docs={
            'desc': 'Trigger a renamer scan for the download folder',
            'params': {
                'base_folder': {'desc': 'Optional folder to scan instead of the configured from-folder'},
                'media_folder': {'desc': 'Optional specific media folder'},
            },
            'return': {'type': 'object: {"success": true}'},
        })

        addEvent('renamer.scan', self.scan)
        addEvent('renamer.check_snatched', self.checkSnatched)

        addEvent('app.load', self.startCrons)

    def startCrons(self):
        """Set up periodic scanning cron jobs."""
        run_every = self.conf('run_every', default=1)
        force_every = self.conf('force_every', default=2)

        fireEvent('schedule.interval', 'renamer.check_snatched', self.checkSnatched,
                  minutes=run_every)
        fireEvent('schedule.interval', 'renamer.force_scan', self.scan,
                  hours=force_every)

    def scanView(self, **kwargs):
        """API handler for renamer.scan."""
        base_folder = kwargs.get('base_folder')
        media_folder = kwargs.get('media_folder')

        fireEvent('renamer.scan', base_folder=base_folder,
                  media_folder=media_folder, async_call=True)

        return {
            'success': True
        }

    def scan(self, base_folder=None, media_folder=None, release_download=None, async_call=False):
        """Scan the from-folder and rename/move completed downloads.

        Args:
            base_folder: Override the configured from-folder
            media_folder: Specific media subfolder to process
            release_download: Specific release download dict to process
            async_call: Whether this was called asynchronously
        """
        if self.renaming_started:
            log.info('Renamer is already running, skipping')
            return

        if not self.conf('from') and not base_folder:
            return

        self.renaming_started = True
        # Reset per-scan state: the "no RAR extractor tool" warning is emitted
        # at most once across the whole scan, not once per group (scan may call
        # extractFiles once per movie folder via _processGroup).
        self._warned_no_tool = False
        scan_folder = base_folder or sp(self.conf('from'))

        try:
            if not os.path.isdir(scan_folder):
                log.warning('Scan folder %s does not exist', scan_folder)
                return

            groups = fireEvent('scanner.scan', folder=scan_folder,
                              simple=not bool(release_download),
                              single=True) or {}

            log.info('Renamer found %d groups to process in %s', len(groups), scan_folder)
            for group_identifier, group in groups.items():
                if self.shuttingDown():
                    break

                try:
                    self._processGroup(group, media_folder, release_download)
                except Exception:
                    log.error('Error processing group %s: %s',
                             group_identifier, traceback.format_exc())

        except Exception:
            log.error('Failed during renamer scan: %s', traceback.format_exc())
        finally:
            self.renaming_started = False



    def _mayReplace(self, dst, group):
        """May the incoming file overwrite what is already at `dst`?

        Only when it is at least as good. The setting is "Remove LOWER/EQUAL
        quality copies of a release after downloading" -- the comparison is the
        whole point of it, and an earlier version of this method ignored it,
        which turned an upgrade into data destruction: measured, a 720p
        download overwrote a 2160p remux, unrecoverably.

        That is reachable straight from FEAT-008. Restoring a movie marks the
        held release 'ignored', so single()'s has_better_quality gate is 0 on
        EVERY profile rung; the searcher walks the profile best-first, and if
        the top rung finds nothing a lower rung downloads. The default naming
        template carries no quality token, so it lands on exactly the path the
        better copy occupies.

        Fails SAFE: if the existing copy's quality cannot be determined, the
        file on disk is kept. The caller then treats this as a skip, so the
        download is left in place rather than deleted by cleanup -- the user
        keeps both and can decide.
        """
        if not self.conf('remove_lower_quality_copies', default = True):
            log.warning('Destination already exists and "Delete Others" is off, keeping it: %s', dst)
            return False

        incoming = (group.get('meta_data') or {}).get('quality') or {}
        if not incoming.get('identifier'):
            log.warning('Incoming quality unknown, keeping the existing file: %s', dst)
            return False

        media_info = group.get('media') or {}
        existing = None
        for release in media_info.get('releases') or []:
            files = (release.get('files') or {}).get('movie') or []
            if dst in files:
                existing = release
                break

        if not existing or not existing.get('quality'):
            log.warning('Cannot tell what quality %s is, keeping it', dst)
            return False

        try:
            profile = fireEvent('profile.default', single = True)
            if media_info.get('profile_id'):
                profile = get_db().get('id', media_info['profile_id'])
        except Exception:
            profile = None

        comparison = fireEvent(
            'quality.ishigher',
            {'identifier': incoming['identifier'], 'is_3d': incoming.get('is_3d', False)},
            {'identifier': existing['quality'], 'is_3d': existing.get('is_3d', False)},
            profile, single = True)

        if comparison in ('higher', 'equal'):
            return True

        log.warning('Keeping the better copy at %s: incoming %s is %s than %s',
                    dst, incoming['identifier'], comparison, existing['quality'])
        return False

    def _moveRenamedFiles(self, rename_files, group):
        """Move each renamed file into the library, then clean up -- but only
        if there is nothing left behind.

        Two defects this replaces:

        1. `if os.path.exists(dst): continue` meant a replacement copy was
           never moved in while the old file was there. With the default naming
           template (`<namethe> (<year>)` / `<thename><cd>.<ext>`, no
           quality/group/source token) EVERY copy of a movie renames to the
           same path, so an upgrade essentially never landed.

        2. `cleanup` then deleted the source folder regardless -- so the file
           the user had just downloaded was skipped AND destroyed. Data loss on
           the happy path of every upgrade.

        Replacement is gated on `remove_lower_quality_copies` ("Delete Others",
        default True), which renamer/api.py has always declared and nothing has
        ever read.
        """
        skipped = False
        moved_any = False

        for src, dst in rename_files.items():
            if not os.path.exists(src):
                log.warning('Source file does not exist: %s', src)
                skipped = True
                continue

            replacing = os.path.exists(dst)
            if replacing and not self._mayReplace(dst, group):
                skipped = True
                continue

            try:
                if replacing:
                    # Follow a symlinked destination to the file it points at.
                    # Split libraries (small SSD + NAS) symlink library entries
                    # at the real storage; os.replace on the LINK would swap in
                    # a real file, orphaning the target and filling the small
                    # volume. Replace what the user actually stores.
                    target = os.path.realpath(dst) if os.path.islink(dst) else dst

                    # Stage beside the destination and swap atomically. The
                    # existing copy must not be destroyed until the incoming
                    # one is fully in place, or a failure mid-way leaves the
                    # user with neither. A sibling path keeps os.replace on one
                    # filesystem; the cross-device work is inside moveFile.
                    staged = '%s.cp_incoming' % target
                    try:
                        # Clear any staging file left by an interrupted run.
                        # moveFile refuses to write over an existing
                        # destination, so without this ONE interrupted
                        # replacement wedged this movie forever: every later
                        # scan failed identically, and a full-size orphan the
                        # scanner cannot see sat in the library folder.
                        if os.path.exists(staged):
                            log.warning('Removing a staging file left by an earlier run: %s', staged)
                            os.remove(staged)
                        self.moveFile(src, staged, use_default = True)
                        os.replace(staged, target)

                        # moveFile's `symlink_reversed` and hardlink-fallback
                        # actions point the DOWNLOAD back at whatever `dest`
                        # they were handed -- here the staging path, which the
                        # swap above has just renamed away. Re-point it at the
                        # real file so a seeding torrent is not left with a
                        # broken link.
                        if os.path.islink(src) and not os.path.exists(src):
                            os.unlink(src)
                            os.symlink(target, src)
                    finally:
                        if os.path.exists(staged):
                            try:
                                os.remove(staged)
                            except OSError:
                                log.error('Failed removing staging file %s', staged)
                    log.info('Replaced: %s -> %s', os.path.basename(src), dst)
                else:
                    self.moveFile(src, dst, use_default = True)
                    log.info('Moved: %s -> %s', os.path.basename(src), dst)
                moved_any = True
            except Exception as e:
                log.error('Failed to move %s: %s', src, e)
                skipped = True

        # Never delete the source folder when anything was left behind -- that
        # is how a download the user just made gets discarded.
        if skipped:
            log.info('Leaving source folder in place: not every file was moved')
            return

        if moved_any and self.conf('cleanup', default = True):
            source_folder = group.get('parentdir')
            if source_folder and os.path.isdir(source_folder):
                self.deleteFolder(source_folder)

    def _processGroup(self, group, media_folder=None, release_download=None):
        """Process a single scanner group (rename/move files)."""
        from couchpotato.core.helpers.variable import getExt, getTitle, getIdentifier
        from couchpotato.core.helpers.encoding import toUnicode

        # Get the media info from the group
        media_info = group.get('media', {})
        if not media_info:
            log.debug('No media_info in group, skipping (identifiers: %s)', group.get('identifiers', []))
            return

        # Get title from media info (movie details from TMDB)
        library = media_info.get('info', {})
        media_title = getTitle(library) or library.get('original_title') or group.get('dirname', 'Unknown')
        log.debug('Processing group: %s', media_title)

        # Build the destination path
        destination = media_folder or sp(self.conf('to'))
        if not destination:
            log.warning('No destination folder configured')
            return

        # Extract if needed
        if self.conf('unrar', default=False):
            group_folder = group.get('parentdir') or group.get('dirname')
            if isinstance(group_folder, dict):
                log.warning('Group folder is a dict instead of a path, skipping extraction: %s', group_folder)
                group_folder = None
            if group_folder and isinstance(group_folder, str):
                self.extractFiles(folder=group_folder, media_folder=media_folder)

        # Get movie files from group
        movie_files = group.get('files', {}).get('movie', [])
        if not movie_files:
            log.debug('No movie files in group for %s, skipping', media_title)
            return

        # Build replacements dict for naming
        library = media_info.get('info', {})
        replacements = {
            'ext': 'mkv',
            'namethe': getTitle(library) or media_title,
            'thename': getTitle(library) or media_title,
            'year': library.get('year', ''),
            'first': (getTitle(library) or media_title)[0].upper(),
            'quality': group.get('meta_data', {}).get('quality', {}).get('label', ''),
            'quality_type': group.get('meta_data', {}).get('quality', {}).get('type', ''),
            'video': '',
            'audio': '',
            'group': group.get('meta_data', {}).get('group', ''),
            'source': group.get('meta_data', {}).get('source', ''),
            'resolution_width': library.get('resolution_width', ''),
            'resolution_height': library.get('resolution_height', ''),
            'imdb_id': getIdentifier(media_info) or '',
            'cd': '',
            'cd_nr': '',
            'mpaa': library.get('mpaa', ''),
            'category': '',
        }

        # Get naming patterns from config
        folder_name = self.conf('folder_name', default='<namethe> (<year>)')
        file_name = self.conf('file_name', default='<thename><cd>.<ext>')

        # Build rename_files mapping
        rename_files = {}

        for idx, current_file in enumerate(movie_files):
            replacements['ext'] = getExt(current_file)

            # Handle multi-part files
            if len(movie_files) > 1:
                replacements['cd'] = ' cd%d' % (idx + 1)
                replacements['cd_nr'] = str(idx + 1)

            final_folder_name = self.doReplace(folder_name, replacements, folder=True)
            final_file_name = self.doReplace(file_name, replacements)

            # doReplace returns bytes, convert to string for os.path.join
            if isinstance(final_folder_name, bytes):
                final_folder_name = final_folder_name.decode('utf-8', errors='replace')
            if isinstance(final_file_name, bytes):
                final_file_name = final_file_name.decode('utf-8', errors='replace')

            rename_files[current_file] = os.path.join(destination, final_folder_name, final_file_name)

        if not rename_files:
            log.debug('No rename_files built for %s, skipping', media_title)
            return

        log.info('Processing: %s -> %s', media_title, list(rename_files.values())[0] if rename_files else 'unknown')

        # Create destination folder if needed
        for src, dst in rename_files.items():
            dst_dir = os.path.dirname(dst)
            if not os.path.isdir(dst_dir):
                log.info('Creating folder: %s', dst_dir)
                try:
                    os.makedirs(dst_dir)
                except OSError as e:
                    if e.errno != 17:  # File exists
                        log.error('Failed to create folder %s: %s', dst_dir, e)
                        return

        self._moveRenamedFiles(rename_files, group)
