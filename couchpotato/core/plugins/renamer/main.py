"""Main Renamer class combining all mixin functionality."""
import os
import traceback

from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.variable import sp
from couchpotato.core.logger import CPLog, log_suppressed
from couchpotato.core.media_lock import media_lock
from couchpotato.core.plugins.renamer.replacement import REPLACE
from couchpotato.core.plugins.renamer.swap import replace_atomically
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
    _warned_dead_setting = False

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
        # Check-and-set must be atomic, or two threads can both pass the
        # check before either sets the flag. The lock is only held for this
        # instant, not the whole scan (which can take minutes) -- a second
        # caller is refused promptly rather than blocked for that long.
        with media_lock('renamer-scan'):
            if self.renaming_started:
                log.info('Renamer is already running, skipping')
                return
            self.renaming_started = True

        try:
            if not self.conf('from') and not base_folder:
                return

            # Reset per-scan state: the "no RAR extractor tool" warning is
            # emitted at most once across the whole scan, not once per group
            # (scan may call extractFiles once per movie folder via
            # _processGroup).
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
            with media_lock('renamer-scan'):
                self.renaming_started = False



    def _moveRenamedFiles(self, rename_files, group):
        """Move each renamed file into the library, then clean up -- but only
        if there is nothing left behind.

        Scope note. This method used to also REPLACE an existing destination,
        implementing the long-declared-but-never-read
        `remove_lower_quality_copies` setting. That was removed after two
        failed attempts, both of which put the user's irreplaceable library at
        risk:

          - the first had no quality comparison at all, so a 720p download
            overwrote a 2160p remux (measured);
          - the second compared with `quality.ishigher`, which is a SEARCH
            heuristic: it answers 'higher' when the existing quality is not a
            rung of the profile ("anything beats a rung I do not want"). The
            default Best profile excludes 2160p, so it still authorised
            destroying a remux -- while simultaneously being inert, because the
            scanner-supplied `group['media']` carries no `releases` key
            (`media.get` attaches that, and the scanner never calls it).

        Replacement needs a total quality ranking that does not exist in this
        codebase today, on the one code path that deletes files from the user's
        library. It is therefore its own piece of work, specified in
        specs/FEAT-009-durable-set-aside-and-upgrade-replacement.md, and not a
        detail of this method.

        What remains is the half that was always a straight bug fix: an
        existing destination means the incoming file is SKIPPED (as it always
        was), and a skip now suppresses `cleanup` -- because deleting the
        source folder after skipping a file destroyed the download the user had
        just made.
        """
        skipped = False
        moved_any = False

        for src, dst in rename_files.items():
            if not os.path.exists(src):
                log.warning('Source file does not exist: %s', src)
                skipped = True
                continue

            if os.path.exists(dst):
                # The replacement decision is COMPUTED and recorded, and then
                # deliberately not acted on -- the swap is wired in the next
                # step. Computing it here first is what proves the gate is
                # REACHABLE with real scan data: withdrawn attempt #2 was
                # simultaneously dangerous and inert, and the inertness is
                # what hid the danger, because the gate never fired in
                # testing so nobody saw what it did when it fired.
                outcome, superseded = self._replacementOutcome(src, dst, group)

                if outcome == REPLACE:
                    ok, reason = replace_atomically(
                        src, dst,
                        lambda a, b: self.moveFile(a, b, use_default = True),
                    )
                    if ok:
                        self._supersedeRelease(superseded, group)
                        moved_any = True
                        continue
                    # The swap refused or failed. The library file is intact
                    # and a complete copy of the download survives -- swap.py
                    # guarantees both -- so this is an ordinary skip, and the
                    # reason is carried through rather than flattened.
                    outcome = reason

                log.warning(
                    'Destination already exists, keeping it: %s (upgrade decision: %s)',
                    dst, outcome,
                )
                skipped = True
                continue

            try:
                self.moveFile(src, dst, use_default = True)
                log.info('Moved: %s -> %s', os.path.basename(src), dst)
                moved_any = True
            except Exception as e:
                log.error('Failed to move %s: %s', src, e)
                skipped = True

        # Never delete the source folder when anything was left behind. This is
        # the data-loss half: previously a skipped move was followed by cleanup,
        # so the file the user had just downloaded was skipped AND destroyed.
        if skipped:
            log.info('Leaving source folder in place: not every file was moved')
            return

        if moved_any and self.conf('cleanup', default = True):
            source_folder = group.get('parentdir')
            if source_folder and os.path.isdir(source_folder):
                self.deleteFolder(source_folder)

    @staticmethod
    def _rankViaEvent(quality):
        """`fireEvent(single=True)` collects only non-None handler results and
        returns `[]` when there are none -- so `rankQuality` answering None for
        an UNRECOGNISED identifier arrives here as `[]`, and `[] is None` is
        False.

        Without this normalisation the unknown-identifier guard in
        decide_replacement never fires through the real wiring: it was dead in
        production while passing every unit test, because the tests injected a
        plain function. Found by review, confirmed by executing fireEvent.
        """
        result = fireEvent('quality.rank', quality, single=True)
        return None if result == [] else result

    def _supersedeRelease(self, superseded, group):
        """Take the replaced release off `done` after its file has gone.

        Spec D3. `os.replace` has already destroyed the old file by this
        point, so "account for the old copy" can only mean a database change
        -- and leaving the old rung at `done` while it still claims the path
        is what produced the unbounded re-download loop in FEAT-009 designs #2
        and #4: `Release.add` keys on `<imdb>.<audio>.<quality>`
        (release/main.py:222) and would create a SECOND done release beside it.

        Best-effort by design. The bytes are already swapped; failing the
        whole rename now would not undo that, and raising here would abort a
        scan that has otherwise succeeded. A stale `done` release is
        recoverable by the next scan, which is not true of the file.
        """
        media = group.get('media') or {}
        media_id = media.get('_id')
        incoming = (group.get('meta_data') or {}).get('quality') or {}

        # D8: the record names the MEDIA and the two rungs, never the
        # destination path. PrivacyFilter only rewrites the `/home/<name>`
        # prefix (core/logger.py), so a raw path would put library layout and
        # film titles into the rotating ring and `docker logs` on every
        # replacement. Whoever diagnoses a bad swap needs to know which movie
        # and which two rungs; the path adds nothing the database cannot give
        # them from the id.
        log.info(
            'Replaced a library copy: media %s, %s -> %s (release %s superseded)',
            media_id,
            (superseded or {}).get('quality'),
            incoming.get('identifier'),
            (superseded or {}).get('_id'),
        )

        if not superseded or not superseded.get('_id'):
            return
        try:
            fireEvent(
                'release.update_status', superseded['_id'], status = 'ignored',
                single = True,
            )
        except Exception:
            log.error(
                'Replaced the file for release %s but could not take it off '
                '"done": %s', superseded.get('_id'), traceback.format_exc(),
            )

    def _warnAboutTheDeadSetting(self):
        """Tell an operator ONCE that `remove_lower_quality_copies` is inert.

        Spec D1. That key carried 'default': True for the life of the fork
        while being read by nothing, so `setDefault` has already persisted
        True into real config files. Upgrade replacement therefore reads a NEW
        key, `upgrade_replace`, which defaults off -- but somebody who set the
        old one DELIBERATELY would otherwise get silence where they expected
        behaviour, and silence is the worst answer for a setting whose name
        promises deletion.

        Once per process, not once per scan: the renamer runs on a timer, and
        a warning repeated every few minutes is one an operator learns to
        filter out.
        """
        if Renamer._warned_dead_setting:
            return
        Renamer._warned_dead_setting = True
        if self.conf('remove_lower_quality_copies', default=False):
            log.warning(
                'The "Delete Others" setting (remove_lower_quality_copies) is no '
                'longer read and does nothing. Upgrade replacement is now the '
                '"Replace lower quality copies" setting (upgrade_replace), which '
                'is OFF by default and must be enabled deliberately.'
            )

    def _replacementOutcome(self, src, dst, group):
        """What WOULD upgrade replacement do with this file? Decide, do not act.

        Returns an outcome value from `renamer.replacement`, or
        `declined_error` if anything at all goes wrong. This runs inside the
        ordinary rename path, so it must never raise: a decision that cannot
        be made is a decision not to replace, and an exception escaping here
        would abort a scan that was otherwise fine (AC-QA-12).
        """
        from couchpotato.core.plugins.renamer.replacement import (
            DECLINED_ERROR,
            DECLINED_INCOMPLETE_EVIDENCE,
            DECLINED_MULTI_FILE_GROUP,
            DECLINED_SETTING_OFF,
            decide_replacement,
        )

        try:
            self._warnAboutTheDeadSetting()
            media = group.get('media') or {}
            media_id = media.get('_id')

            # The DB round trip only happens once the cheap refusals have
            # passed. `upgrade_replace` is off by default, so otherwise every
            # ordinary destination collision on every install would pay for a
            # `get_many` plus a `get` per release to reach a foregone
            # conclusion. decide_replacement checks these first too; this
            # mirrors that order rather than trusting it.
            if not bool(self.conf('upgrade_replace', default=False)):
                return DECLINED_SETTING_OFF
            if len((group.get('files') or {}).get('movie') or []) != 1:
                return DECLINED_MULTI_FILE_GROUP

            # require_complete: an unreadable release document may be the
            # one that claims this destination, and resolving ownership from a
            # partial set can attribute the wrong quality to the file about to
            # be deleted. None means "the set is incomplete" -- distinct from
            # an empty list, which means "this media genuinely has no
            # releases".
            releases = fireEvent(
                'release.for_media', media_id, require_complete=True, single=True,
            ) if media_id else []
            if releases is None:
                return DECLINED_INCOMPLETE_EVIDENCE

            outcome, existing = decide_replacement(
                destination=dst,
                incoming_quality=(group.get('meta_data') or {}).get('quality'),
                releases=releases or [],
                size_on_disk=self._sizeOrNone(dst),
                video_file_count=len((group.get('files') or {}).get('movie') or []),
                setting_enabled=bool(self.conf('upgrade_replace', default=False)),
                is_better=lambda a, b: bool(
                    fireEvent('quality.is_better', a, b, single=True)
                ),
                rank=self._rankViaEvent,
            )
            return outcome, existing
        except Exception:
            # The collided download is deliberately left in place, so a group
            # that raises here raises again on every scheduled scan. An
            # unbounded full traceback each time evicts the rotating log,
            # which is the only diagnostic a self-hosted install has -- so the
            # failure would erase the evidence of itself. `log_suppressed`
            # keeps the FIRST occurrence complete and bounds the repeats.
            #
            # The key is the media id, never the path: paths are exactly what
            # PrivacyFilter exists to keep out of logs.
            log_suppressed(
                log.error,
                'renamer_replacement_decision_failed:%s' % (
                    (group.get('media') or {}).get('_id') or 'unknown',
                ),
                'Could not decide on upgrade replacement: %s',
                traceback.format_exc(),
            )
            return DECLINED_ERROR, None

    @staticmethod
    def _sizeOrNone(path):
        """None means "could not stat", which the decision layer treats as a
        refusal rather than as a size of zero."""
        try:
            return os.path.getsize(path)
        except OSError:
            return None

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
