"""Main Renamer class combining all mixin functionality."""
import os
import time
import traceback
import uuid

from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.variable import sp, symlink
from couchpotato.core.logger import CPLog, log_suppressed
from couchpotato.core.media_lock import media_lock
from couchpotato.core.plugins.renamer.replacement import (
    DECLINED_OUTSIDE_LIBRARY,
    DECLINED_SIZE_CONTRADICTS_QUALITY,
    DECLINED_SOURCE_CHANGED,
    DECLINED_UNVERIFIED_IDENTITY,
    REPLACE,
)
from couchpotato.core.plugins.renamer.swap import identity_of, replace_atomically
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
            # Once per process, at the top of a scan. It used to sit inside
            # `_replacementOutcome`, which only runs when a destination
            # actually COLLIDES -- so an operator who deliberately set the old
            # key on a library with nothing colliding got exactly the silence
            # D1 exists to prevent, and got it until something happened to
            # collide. Inside the try, so that a failure here still releases
            # `renaming_started` in the finally.
            self._warnAboutTheDeadSetting()

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
                self._reportStaleStagingFiles(os.path.dirname(dst))
                # The replacement decision is COMPUTED and recorded, and then
                # deliberately not acted on -- the swap is wired in the next
                # step. Computing it here first is what proves the gate is
                # REACHABLE with real scan data: withdrawn attempt #2 was
                # simultaneously dangerous and inert, and the inertness is
                # what hid the danger, because the gate never fired in
                # testing so nobody saw what it did when it fired.
                outcome, superseded = self._replacementOutcome(src, dst, group)

                if outcome == REPLACE and not self._identityIsAsserted(group):
                    outcome = DECLINED_UNVERIFIED_IDENTITY

                if outcome == REPLACE and not self._sizeSupportsTheClaimedQuality(group, src):
                    outcome = DECLINED_SIZE_CONTRADICTS_QUALITY

                measured_source_size = self._sourceStillMatchesTheScan(group, src)
                if outcome == REPLACE and measured_source_size is None:
                    # The quality rung was derived from the scanner's
                    # measurement. If the bytes have moved since, the rung
                    # describes a file that no longer exists.
                    outcome = DECLINED_SOURCE_CHANGED

                if outcome == REPLACE and not self._destinationIsInsideTheLibrary(dst):
                    # A naming template, a crafted title or a `media_folder`
                    # override can resolve outside the configured library:
                    # `doReplace` preserves separators and `..`, and
                    # `os.path.join` honours an absolute component. Refusing
                    # to move a file INTO an odd place is a mistake; refusing
                    # to DESTROY a file outside the library is not.
                    outcome = DECLINED_OUTSIDE_LIBRARY

                if outcome == REPLACE:
                    ok, reason = replace_atomically(
                        src, dst,
                        expected_source_size=measured_source_size,
                        destination_identity=identity_of(dst),
                        about_to_replace=lambda: self._announceImminentReplacement(
                            src, dst, superseded, group,
                        ),
                    )
                    if ok:
                        # Bookkeeping BEFORE disposal, and the order is not
                        # free. Both are best-effort, but a kill between them
                        # leaves different wreckage:
                        #
                        #   dispose first  -> download gone, release still
                        #                     `done` claiming a file that no
                        #                     longer exists. That is the
                        #                     unbounded re-download loop D3
                        #                     exists to prevent, with nothing
                        #                     left on disk to recover from.
                        #   supersede first-> release correctly off `done`,
                        #                     download still present. Untidy
                        #                     and entirely recoverable.
                        #
                        # The swap has already committed either way, so the
                        # only question is which half-finished state a crash
                        # leaves behind. Pick the recoverable one.
                        self._supersedeRelease(superseded, group, dst)
                        self._disposeOfSourceAfterReplacement(
                            src, dst, (group.get('media') or {}).get('_id'),
                        )
                        moved_any = True
                        continue
                    # The swap refused or failed. The library file is intact
                    # and a complete copy of the download survives -- swap.py
                    # guarantees both -- so this is an ordinary skip, and the
                    # reason is carried through rather than flattened.
                    outcome = reason

                # Two reviews disagreed about this line, so the split is
                # deliberate rather than a compromise.
                #
                # One asked for the path back, because a collision recurring
                # every scan interval is unreadable without knowing WHICH
                # file. The other pointed out that a raw library path at
                # WARNING is exactly what D8 forbids everywhere else in this
                # method -- PrivacyFilter only masks a `/home/<name>` prefix,
                # so a NAS mount or library layout goes into the rotating ring
                # and `docker logs` verbatim.
                #
                # Both are right about their own level. WARNING is the level
                # that ships and rotates unattended, so it names the media and
                # the decision. DEBUG is the level somebody turns on while
                # actually diagnosing a collision, and it gets the path.
                log.warning(
                    'Destination already exists, keeping it: media %s '
                    '(upgrade decision: %s)',
                    (group.get('media') or {}).get('_id'), outcome,
                )
                log.debug('The collided destination was: %s', dst)
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

    def _destinationIsInsideTheLibrary(self, destination):
        """Is `destination` under the configured library root?

        Only asked on the destructive path. The ordinary move already writes
        wherever the template resolves, and tightening that is a different
        change with a different blast radius; what must not happen is
        DESTROYING a file the operator never told us was ours.

        `realpath` on both sides, so a symlinked library root still matches
        and a `..` in a template cannot escape it. An unreadable or unset root
        answers False: unable to prove containment is not permission.
        """
        root = self.conf('to')
        if not root:
            return False
        try:
            root = os.path.realpath(sp(root))
            target = os.path.realpath(sp(destination))
        except (OSError, ValueError):
            return False
        return os.path.commonpath([root, target]) == root

    def _releasesForGroup(self, group, media_id):
        """The group's releases, fetched at most ONCE per group.

        AC-ARCH-5 bounds this at one lookup per group and none per file.
        `_replacementOutcome` runs per colliding `(src, dst)` pair, so a group
        with more than one existing destination -- a subtitle beside the movie
        file, say -- fired a `get_many` plus a `get` per release for each of
        them, on a timer, to reach the same answer.

        Cached on the group dict rather than on self: a group is one scan's
        worth of work with a known lifetime, whereas anything on the plugin
        outlives the scan and would go stale between them.
        """
        if not media_id:
            return []
        if '_cp_releases' not in group:
            group['_cp_releases'] = fireEvent(
                'release.for_media', media_id, require_complete=True, single=True,
            )
        return group['_cp_releases']

    #: A staging file older than this is not one somebody is still writing.
    #: Generous on purpose -- a 60 GB remux across a slow NAS mount is a long
    #: copy, and reporting a live transfer as wreckage is worse than reporting
    #: nothing.
    STALE_STAGING_AGE_SECONDS = 6 * 60 * 60

    def _reportStaleStagingFiles(self, directory):
        """Say so when a `.cp-upgrade-*.part` has been abandoned.

        If the process is killed between staging and `os.replace`, the staged
        copy survives under a hidden name the scanner ignores (`.part` is not
        a media extension) while the library file is still the old one. Left
        unreported, automation says the download is missing and gives nobody
        a way to find the complete copy that is sitting right there.

        The NAME is logged, never the directory. The name is a uuid, so it
        carries nothing private, and it is what an operator needs to run
        `find` themselves.

        Best-effort and non-fatal: this is a diagnostic, and a diagnostic that
        can break a scan is worse than no diagnostic.
        """
        try:
            names = [
                name for name in os.listdir(directory)
                if name.startswith('.cp-upgrade-') and name.endswith('.part')
            ]
        except OSError:
            return

        for name in names:
            full = os.path.join(directory, name)
            try:
                age = time.time() - os.path.getmtime(full)
                size = os.path.getsize(full)
            except OSError:
                continue
            if age < self.STALE_STAGING_AGE_SECONDS:
                continue
            log_suppressed(
                log.warning,
                'renamer_stale_staging:%s' % name,
                'An abandoned upgrade staging file is taking up %s bytes in '
                'the library: "%s", last written %s hours ago. It is a '
                'COMPLETE copy of a download that was never installed -- an '
                'upgrade was interrupted between staging and the swap. '
                'Recover it or delete it; nothing else will.',
                size, name, int(age // 3600),
            )

    @staticmethod
    def _withoutPaths(error):
        """Describe an OSError without naming the file it happened to.

        `traceback.format_exc()` embeds `OSError.filename` in its final line
        regardless of the frame limit, so `[Errno 13] Permission denied:
        '/mnt/downloads/Some.Movie.2001/incoming.mkv'` reaches the rotating
        ring verbatim. PrivacyFilter only rewrites a `/home/<name>` prefix, so
        a NAS mount, a Windows path or anything under /downloads goes straight
        through -- the leak D8 exists to prevent, arrived at through the one
        place that formats an exception rather than a message.

        errno and strerror carry the whole remedy anyway. Which file it was is
        already known from the media id in the surrounding record.
        """
        errno = getattr(error, 'errno', None)
        detail = getattr(error, 'strerror', None) or type(error).__name__
        return '[errno %s] %s' % (errno, detail) if errno else detail

    #: Identity sources that ASSERT which movie this is, as opposed to
    #: guessing. `search` is absent deliberately: it is the best match for a
    #: parsed title and year, which is a guess, and a wrong guess on this path
    #: destroys a different movie's library copy rather than mis-filing a
    #: download.
    ASSERTED_IDENTITY_SOURCES = frozenset(
        {'download_id', 'cp_tag', 'nfo', 'filename'}
    )

    @classmethod
    def _identityIsAsserted(cls, group):
        """Did we IDENTIFY this movie, or infer it?

        `folder_scanner.determineMedia` has five ways to name a group, and the
        last is `movie.search` on a title and year parsed out of the filename.
        For the scanner's original job -- putting a download somewhere -- a
        wrong guess is a misplaced file. Here it authorises fetching another
        movie's releases and overwriting that movie's destination.

        A group with no recorded source is refused rather than trusted:
        `identity_source` is written on every path through determineMedia, so
        its absence means this group did not come from there and nothing has
        vouched for it.
        """
        return group.get('identity_source') in cls.ASSERTED_IDENTITY_SOURCES

    #: How far below a rung's own size band a file may fall before its claimed
    #: quality is treated as contradicted. The bands (quality/main.py) are
    #: broad and overlapping, so this is a sanity check against the absurd --
    #: a 700 MB file labelled 2160p -- and not an attempt to re-derive quality
    #: from size, which is `quality.guess`'s job and not ours to second-guess.
    QUALITY_BAND_FLOOR_FRACTION = 0.5

    @staticmethod
    def _sizeSupportsTheClaimedQuality(group, source):
        """Do the bytes support the rung this file claims?

        `media_parser.getMetaData` PREFERS a snatched release's claimed
        quality over the scanner's own detection, so a mislabelled or
        malicious release description reaches the decision as fact. Ranked on
        that label alone, a small file claiming 2160p outranks a genuine
        1080p library copy and replaces it.

        Deliberately only catching the absurd. The size bands overlap heavily
        and encoding efficiency varies, so anything tighter would refuse real
        upgrades; this exists to stop a file that is nowhere near its claimed
        rung from destroying one that is.

        True when there is nothing to check against -- an unknown rung, no
        band, an unmeasurable file. Every one of those is refused elsewhere
        for its own reason, and inventing an answer here would only make this
        guard look like it did the work.
        """
        quality = (group.get('meta_data') or {}).get('quality') or {}
        identifier = quality.get('identifier')
        if not identifier:
            return True

        band = fireEvent('quality.single', identifier, single=True) or {}

        # `size_min`, NOT `size`. The operator edits size_min/size_max through
        # the settings UI (`quality.size.save` -> saveSize), and those land as
        # separate keys on the quality DOCUMENT. `single()` returns
        # `mergeDicts(static_quality, document)`, and the static `size` tuple
        # exists only in the static half -- so nothing the operator changes
        # ever reaches it, and reading `size` here would silently enforce the
        # shipped defaults against a library they had deliberately retuned.
        #
        # `quality.guess` uses size_min/size_max for exactly this comparison
        # (quality/main.py:470), so this follows the same source of truth
        # rather than inventing a second one.
        low = band.get('size_min')
        if not isinstance(low, (int, float)):
            low = (band.get('size') or (None, None))[0]
        if not isinstance(low, (int, float)) or low <= 0:
            return True

        try:
            megabytes = os.path.getsize(source) / 1024 / 1024
        except OSError:
            return True

        return megabytes >= low * Renamer.QUALITY_BAND_FLOOR_FRACTION

    #: How far the source may differ from the scanner's measurement.
    #:
    #: `meta_data['size']` is a float in MEGABYTES (`getFileSize` divides by
    #: 1024 twice), so recovering a byte count needs a tolerance for the
    #: round trip. One mebibyte is far more than that round trip can lose and
    #: far less than a still-downloading file differs by -- a partial
    #: download is short by a good fraction of the whole, not by a kilobyte.
    #:
    #: The honest limitation: growth smaller than this is not detected. That
    #: is accepted, because it is not the failure mode. A file that grew by
    #: 100 KB between the scan and the rename has not changed quality rung.
    SCAN_SIZE_TOLERANCE_BYTES = 1024 * 1024

    @classmethod
    def _sourceStillMatchesTheScan(cls, group, source):
        """The source's size if it still matches the scan, else None.

        Returning the SIZE rather than a bool is what lets the caller hand it
        to `replace_atomically` as `expected_source_size`. Without that the
        swap took its own fresh measurement, self-consistent with whatever it
        copied, and a downloader appending between this check and that copy
        was invisible to both.

        The quality rung on this group was derived from that measurement. A
        downloader still appending between the scan and the rename gives a
        file whose rung describes an earlier, smaller version of itself, and
        acting on it replaces a complete library copy on the strength of a
        rung the bytes have not earned.

        The comparison must be against the SCANNER's figure. Taking a fresh
        size here and comparing it to another fresh size compares a value with
        itself and passes forever, which is the shape this check exists to
        avoid.

        When the scanner recorded nothing usable the comparison is skipped
        rather than fabricated -- a size invented here would compare equal to
        itself and read exactly like a guard that works -- but the measurement
        just taken is still returned, because it is what closes the window
        above.

        Only meaningful because D7 refuses multi-file groups -- `meta_data`
        holds ONE size summed across the group's movie files, so with more
        than one it would not describe this file at all. If that refusal is
        ever relaxed, this must be revisited before it is.
        """
        try:
            actual = os.path.getsize(source)
        except OSError:
            # Unable to measure is not the same as unchanged, and this is the
            # destructive path.
            return None

        recorded_mb = (group.get('meta_data') or {}).get('size')
        if not isinstance(recorded_mb, (int, float)) or recorded_mb <= 0:
            # Nothing to compare against, but the measurement just taken is
            # still worth carrying: it closes the window between here and the
            # staging copy inside replace_atomically.
            return actual

        expected = recorded_mb * 1024 * 1024
        if abs(actual - expected) > cls.SCAN_SIZE_TOLERANCE_BYTES:
            return None
        return actual

    def _announceImminentReplacement(self, source, destination, superseded, group):
        """AC-OPS-2: one WARNING in the last moment before the file is gone.

        A crash immediately after `os.replace` leaves the old copy destroyed
        and nothing after this point having run. This record is therefore the
        only thing that can explain the deletion afterwards, so it is emitted
        BEFORE the irreversible step rather than after it.

        D8: media and rungs, never paths. Sizes are numbers, which say a great
        deal about whether the swap was sane and nothing about the operator's
        filesystem.
        """
        incoming = (group.get('meta_data') or {}).get('quality') or {}
        log.warning(
            'About to replace a library copy: media %s, %s (%s bytes) -> '
            '%s (%s bytes), superseding release %s. This destroys the old file.',
            (group.get('media') or {}).get('_id'),
            (superseded or {}).get('quality'),
            self._sizeOrNone(destination),
            incoming.get('identifier'),
            self._sizeOrNone(source),
            (superseded or {}).get('_id'),
        )

    def _disposeOfSourceAfterReplacement(self, source, destination, media_id=None):
        """Now honour `default_file_action` -- on the SOURCE, after the swap.

        Staging deliberately copies, so at this point the download still
        exists and the library holds a complete new copy. This is where the
        operator's choice genuinely applies, and doing it here rather than
        during staging is what stops `symlink_reversed` and the `link`
        fallback leaving a link to a staging path that `os.replace` has
        already renamed away.

        Best-effort throughout: the swap has succeeded, and nothing that
        happens to the download now can justify raising through a completed
        replacement.
        """
        action = self.conf('default_file_action', default='move')
        try:
            if action == 'move':
                os.remove(source)
            elif action == 'symlink_reversed':
                # Link FIRST at a temporary name, then rename it over the
                # source. Removing the source and then linking left a window
                # where a failed `symlink` -- a FAT/exFAT download mount, a
                # quota, a permissions problem, all plausible for a downloads
                # mount that differs from the library mount -- destroyed the
                # download and created nothing in its place.
                #
                # The log below then said "the download is still on disk",
                # which was false. A message that reassures about data safety
                # while the data is gone is worse than no message.
                # Unique per attempt, for the same reason swap.py's staging
                # path is: two concurrent scans, or a previous crashed run,
                # must not collide on this name. A fixed name here would have
                # been the one place in this flow that assumed the
                # single-process case the rest of it explicitly does not.
                staging_link = '%s.cp-link-%s.tmp' % (source, uuid.uuid4().hex)
                try:
                    symlink(destination, staging_link)
                    os.replace(staging_link, source)
                except Exception:
                    if os.path.lexists(staging_link):
                        try:
                            os.remove(staging_link)
                        except OSError:
                            pass
                    raise
            # 'copy' and 'link' leave the download where it is. A hardlink
            # back is not recreated: the swap replaced the destination inode,
            # so the old link would point at the destroyed file and a new one
            # cannot span filesystems anyway.
        except Exception as error:
            log.warning(
                'Replaced the library copy for media %s, but could not apply '
                '"%s" to the download afterwards. The library is correct and '
                'the download is still on disk: %s',
                media_id, action, self._withoutPaths(error),
            )

    def _supersedeRelease(self, superseded, group, destination=None):
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
            # `Release.updateStatus` CATCHES database errors and contention
            # and returns False, and the dispatcher contains handler
            # exceptions too -- so the try/except below never sees the
            # ordinary failure. The result has to be read.
            updated = fireEvent(
                'release.update_status', superseded['_id'], status = 'ignored',
                single = True,
            )
        except Exception:
            # Logged HERE, with the traceback, and then short-circuited: the
            # shared report below would otherwise fire for the same single
            # failure and produce two differently-worded ERROR records for it.
            # One failure, one record -- otherwise the log implies two things
            # went wrong and neither entry tells the whole story.
            log.error(
                'Replaced the file for release %s but could not take it off '
                '"done": %s', superseded.get('_id'), traceback.format_exc(),
            )
            return

        if updated is False or updated == []:
            log.error(
                'Replaced the file for release %s but the status update was '
                'REFUSED. That release still claims a file that no longer '
                'exists, so it may be re-downloaded; take it off "done" by '
                'hand.', superseded.get('_id'),
            )
            return

        self._detachSupersededClaim(superseded, destination)

    def _detachSupersededClaim(self, superseded, destination):
        """Stop the dead release claiming the path it no longer owns.

        Marking it `ignored` changes only the status. The document keeps its
        `files['movie']` path and its `copy_id`, and `release.for_media`
        returns ignored releases too -- so ownership resolution still sees a
        claimant for a destination whose bytes it did not produce. Left in
        place that makes the NEXT upgrade ambiguous, which resolves as a
        refusal: the operator's second upgrade silently stops working because
        of the first one.

        Best-effort, and deliberately after the status update. A file that has
        already been replaced is not made worse by a stale path.
        """
        if not destination:
            return

        # Read the result rather than catching. `detachFile` wraps its own
        # database call and RETURNS False, and fireEvent's dispatcher contains
        # handler exceptions too -- so a try/except here would only ever fire
        # for something that broke before detachFile's own guard, and would
        # look like it was handling the ordinary failure while never seeing
        # it. That is the same mistake `_supersedeRelease` documents 25 lines
        # up, and it is worth not making twice in one file.
        detached = fireEvent(
            'release.detach_file', superseded['_id'], destination, single = True,
        )
        if detached is not True:
            log.warning(
                'Release %s is off "done" but still lists the replaced path. '
                'A later upgrade of this movie may refuse as ambiguous until '
                'that document is corrected.', superseded.get('_id'),
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
            media = group.get('media') or {}
            media_id = media.get('_id')

            # The DB round trip only happens once the cheap refusals have
            # passed. `upgrade_replace` is off by default, so otherwise every
            # ordinary destination collision on every install would pay for a
            # `get_many` plus a `get` per release to reach a foregone
            # conclusion. decide_replacement checks these first too; this
            # mirrors that order rather than trusting it.
            if not bool(self.conf('upgrade_replace', default=False)):
                return DECLINED_SETTING_OFF, None
            if len((group.get('files') or {}).get('movie') or []) != 1:
                return DECLINED_MULTI_FILE_GROUP, None

            # require_complete: an unreadable release document may be the
            # one that claims this destination, and resolving ownership from a
            # partial set can attribute the wrong quality to the file about to
            # be deleted. None means "the set is incomplete" -- distinct from
            # an empty list, which means "this media genuinely has no
            # releases".
            releases = self._releasesForGroup(group, media_id)
            if releases is None:
                return DECLINED_INCOMPLETE_EVIDENCE, None

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
