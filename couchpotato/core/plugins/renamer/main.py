"""Main Renamer class combining all mixin functionality."""
import os
import traceback

from couchpotato.api import addApiView
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
        scan_folder = base_folder or sp(self.conf('from'))

        try:
            if not os.path.isdir(scan_folder):
                log.warning('Scan folder %s does not exist', scan_folder)
                return

            groups = fireEvent('scanner.scan', folder=scan_folder,
                              simple=not bool(release_download),
                              single=True) or {}

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

    def _processGroup(self, group, media_folder=None, release_download=None):
        """Process a single scanner group (rename/move files)."""
        # Get the media info from the group
        media_info = group.get('media', {})
        if not media_info:
            return

        # Determine file action
        file_action = self.conf('default_file_action', default='move')
        if release_download and self.downloadIsTorrent(release_download):
            file_action = self.conf('file_action', default='link')

        # Extract if needed
        if self.conf('unrar', default=False):
            group_folder = group.get('parentdir') or group.get('dirname')
            if isinstance(group_folder, dict):
                log.warning('Group folder is a dict instead of a path, skipping extraction: %s', group_folder)
                group_folder = None
            if not group_folder or not isinstance(group_folder, str):
                group_folder = None
            self.extractFiles(
                folder=group_folder,
                media_folder=media_folder,
            )

        # Build the destination path
        to_folder = media_folder or sp(self.conf('to'))
        if not to_folder:
            log.warning('No destination folder configured')
            return

        # Use namer to build file/folder names
        rename_files = group.get('rename_files', {})
        if not rename_files:
            return

        log.info('Processing: %s', group.get('meta_data', {}).get('name', 'Unknown'))
