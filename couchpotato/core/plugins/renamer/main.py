"""Main Renamer class combining all mixin functionality."""
import hashlib
import os
import threading
import time
import traceback
import uuid

from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.variable import sp, symlink
from couchpotato.core.logger import CPLog, log_suppressed, without_paths
from couchpotato.core.media_lock import media_lock
from couchpotato.core.plugins.renamer.replacement import (
    DECLINED_MULTI_FILE_GROUP,
    DECLINED_OUTSIDE_LIBRARY,
    DECLINED_SETTING_OFF,
    DECLINED_SIZE_CONTRADICTS_QUALITY,
    DECLINED_SOURCE_CHANGED,
    DECLINED_UNVERIFIED_IDENTITY,
    OPERATOR_DECLINED_AMBIGUOUS_FILE,
    OPERATOR_REFUSED_ALREADY_RUNNING,
    OPERATOR_REFUSED_SOURCE_OUTSIDE_WATCH_FOLDER,
    OPERATOR_REPLACE,
    REPLACE,
    decide_operator_replacement,
)
from couchpotato.core.plugins.renamer.swap import (
    REFUSED_NO_SOURCE,
    identity_of,
    replace_atomically,
)
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

    #: Settings that feed the replacement decision. A remembered decision is
    #: reused only when every one of these reads exactly as it did when the
    #: entry was recorded (AC-QA-7): turning `upgrade_replace` on,
    #: retargeting the library, or editing a naming template forces a
    #: re-decide with no restart needed.
    DECISION_MEMORY_SETTINGS = ('upgrade_replace', 'to', 'folder_name', 'file_name')

    #: Only a refusal whose cause CANNOT change without a file or a setting
    #: change is worth remembering (AC-QA-9). `declined_error`,
    #: `declined_incomplete_evidence` and every outcome `decide_replacement`
    #: derives from a release document are deliberately absent: those can
    #: flip on a transient read failure or a release document being edited,
    #: with neither the source file nor a setting moving at all -- and a
    #: memory that outlives its cause is worse than the loop it replaces.
    REMEMBER_ELIGIBLE_OUTCOMES = frozenset({
        DECLINED_SETTING_OFF,
        DECLINED_UNVERIFIED_IDENTITY,
        DECLINED_MULTI_FILE_GROUP,
        DECLINED_OUTSIDE_LIBRARY,
        DECLINED_SIZE_CONTRADICTS_QUALITY,
    })

    def __init__(self):

        addApiView('renamer.scan', self.scanView, docs={
            'desc': 'Trigger a renamer scan for the download folder',
            'params': {
                'base_folder': {'desc': 'Optional folder to scan instead of the configured from-folder'},
                'media_folder': {'desc': 'Optional specific media folder'},
            },
            'return': {'type': 'object: {"success": true}'},
        })

        addApiView('renamer.operator_replace', self.operatorReplaceView, docs={
            'desc': 'Replace the library copy of a film with a file the '
                    'operator placed by hand under the configured download '
                    'folder. Backgrounded; poll notifications for the outcome.',
            'params': {
                'media_id': {'desc': 'The media whose library copy is being replaced'},
                'source': {'desc': 'Name of a file already listed under the configured from-folder'},
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

    def _folderSignature(self, scan_folder):
        """A cheap fingerprint of what is actually on disk under
        `scan_folder`: every file's path relative to it, its size and its
        mtime in nanoseconds. No identity resolution, no TMDB lookup, no RAR
        inspection -- just what `os.walk` and `os.stat` already know, which
        is what binding decision 1 means by "a cheap read of names, sizes
        and mtimes".

        `None` means the folder could not be walked in full, which fails
        open: an unmeasurable folder (a permission error, a NAS mount
        dropping mid-walk, a file that vanished between the walk and the
        stat) is never treated as unchanged, so it forces a re-decide rather
        than a silent, permanent skip (AC-QA-14).
        """
        entries = []
        try:
            for root, _dirs, files in os.walk(scan_folder):
                for name in files:
                    full = os.path.join(root, name)
                    try:
                        stat_result = os.stat(full)
                    except OSError:
                        return None
                    entries.append((
                        os.path.relpath(full, scan_folder),
                        stat_result.st_size,
                        stat_result.st_mtime_ns,
                    ))
        except OSError:
            return None
        return frozenset(entries)

    def _settingsSignature(self):
        """A snapshot of the settings that feed the replacement decision,
        compared the same way `_folderSignature` compares the filesystem
        (AC-QA-7)."""
        return tuple(self.conf(key) for key in self.DECISION_MEMORY_SETTINGS)

    @staticmethod
    def _destinationSignature(paths):
        """A cheap fingerprint of the destination paths a remembered
        decision was recorded against: whether each one exists, and if so
        its size and mtime. `_folderSignature` only ever walks the
        DOWNLOADS folder, so a change on the library side -- the operator
        deleting the stale file that was blocking a park, or replacing it
        in place -- is otherwise invisible to the memory (AC-QA-6). A path
        that cannot be stat-ed is recorded as `(path, None, None)` rather
        than skipped, so "missing" and "present with these bytes" are never
        confused with each other.
        """
        entries = []
        for path in paths:
            try:
                stat_result = os.stat(path)
            except OSError:
                entries.append((path, None, None))
            else:
                entries.append((path, stat_result.st_size, stat_result.st_mtime_ns))
        # Sorted so the comparison does not depend on dict/set ordering --
        # `paths` is built from `rename_files.items()`, whose order is not a
        # contract worth relying on here. Safe to sort tuples of mixed
        # None/int in the trailing positions because every leading `path`
        # is unique, so comparison never falls through to them.
        return tuple(sorted(entries))

    def _notifyParked(self, group, outcome):
        """Binding decision 3: entering a parked state fires exactly one
        `fireEvent('notify', ...)`, using the existing durable notification
        document and the existing `notification.list` API -- no new route,
        template or setting. So a parked film is discoverable without
        reading the log, which is what AC-OPS-4's bounded restatement means
        an operator will not be doing in real time.

        Deduplicated on `(media id, outcome)` for the life of the process:
        process-local only, like the rest of this memory (AC-SIMP-5), never
        written through `get_db()` or `Env` itself. Re-entering the SAME
        parked state on a later scan -- whether because the memory skipped
        the folder outright, or because it was invalidated and re-decided
        onto the same outcome -- fires nothing further (AC-OPS-5); a
        DIFFERENT outcome for the same media is a new park and notifies
        again.
        """
        media_id = (group.get('media') or {}).get('_id')
        key = (media_id, outcome)

        if getattr(self, '_notified_parked', None) is None:
            self._notified_parked = set()
        if key in self._notified_parked:
            return
        self._notified_parked.add(key)

        from couchpotato.core.helpers.variable import getTitle
        library = (group.get('media') or {}).get('info', {})
        media_title = getTitle(library) or group.get('dirname') or 'Unknown'

        # No absolute path in the message (AC-SEC-8): `media_title` and
        # `outcome` are both TMDB/decision metadata, never a filesystem
        # path, matching the WARNING record this restates.
        fireEvent(
            'notify',
            message='"%s" is parked and needs a look: %s' % (media_title, outcome),
            data={'media_id': media_id, 'outcome': outcome},
        )

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

            # Lazily created rather than in __init__: process-local only
            # (AC-SIMP-5, AC-SEC-5) -- plain state on the instance, nothing
            # persisted, nothing surviving a restart. Keyed on the folder
            # actually scanned, never written to disk or the database.
            if getattr(self, '_decision_memory', None) is None:
                self._decision_memory = {}

            try:
                if not os.path.isdir(scan_folder):
                    log.warning('Scan folder %s does not exist', scan_folder)
                    return

                # A targeted scan -- a specific media_folder, or one carrying
                # a release_download -- is an operator asking about ONE
                # group, not a verdict on the whole folder. It must never be
                # answered from a memory keyed on the folder as a whole, and
                # must never overwrite that memory either: doing so would let
                # one targeted call evict every other group's remembered
                # decision (AC-OPS-12).
                targeted = media_folder is not None or release_download is not None

                current_signature = self._folderSignature(scan_folder)
                current_settings = self._settingsSignature()

                if not targeted:
                    remembered = self._decision_memory.get(scan_folder)
                    if (
                        remembered is not None
                        and current_signature is not None
                        and remembered['source_signature'] == current_signature
                        and remembered['settings_signature'] == current_settings
                        and self._destinationSignature(remembered['destination_paths'])
                            == remembered['destination_signature']
                    ):
                        # Nothing on disk or in the settings that feed the
                        # decision has changed since every group here was
                        # last fully decided -- skip the folder walk AND the
                        # identity resolution inside
                        # fireEvent('scanner.scan', ...) entirely, rather
                        # than only skipping the log line that follows it.
                        # This is the cost the production incident paid
                        # roughly 1,100 times: a full rescan and a live TMDB
                        # search for a decision that could not have changed.
                        # D8: no path at INFO, matching every other record in
                        # this file -- the count and the fact that nothing
                        # changed is all an operator needs here.
                        log.info(
                            'Renamer: %d group(s) already decided and '
                            'unchanged; skipping the scan',
                            remembered['group_count'],
                        )
                        log.debug('The unchanged scan folder was: %s', scan_folder)
                        return

                groups = fireEvent('scanner.scan', folder=scan_folder,
                                  simple=not bool(release_download),
                                  single=True) or {}

                log.info('Renamer found %d groups to process in %s', len(groups), scan_folder)

                # True only while every group seen this scan is safely
                # parkable -- a REPLACE, a plain move, a raised exception, or
                # any outcome outside REMEMBER_ELIGIBLE_OUTCOMES turns it off
                # for the rest of this scan, so one unresolved group cannot
                # let the whole folder be remembered as settled.
                all_remember_eligible = bool(groups)
                # Destination paths behind every group this scan decided to
                # park, so the NEXT scan can cheaply re-stat exactly those
                # paths and notice a deleted or replaced library file before
                # it ever trusts the memory (AC-QA-6). Only ever populated
                # from a fully eligible group -- see below -- because the
                # memory is keyed on the whole folder, not per group.
                destination_paths = []
                for group_identifier, group in groups.items():
                    if self.shuttingDown():
                        all_remember_eligible = False
                        break

                    try:
                        outcomes = self._processGroup(group, media_folder, release_download)
                    except Exception:
                        log.error('Error processing group %s: %s',
                                 group_identifier, traceback.format_exc())
                        all_remember_eligible = False
                        continue

                    if not outcomes:
                        all_remember_eligible = False
                        continue

                    group_eligible = True
                    for outcome, dst in outcomes:
                        if outcome in self.REMEMBER_ELIGIBLE_OUTCOMES:
                            # Binding decision 3: the film is discoverable
                            # through notification.list the moment it is
                            # parked, without reading the log. Fires at most
                            # once per (media, outcome) for the life of the
                            # process -- deduplicated inside the method --
                            # so repeated scans of an unchanged park, and
                            # repeated re-decides that land on the same
                            # outcome, never re-fire it.
                            self._notifyParked(group, outcome)
                        else:
                            group_eligible = False
                    if group_eligible:
                        destination_paths.extend(dst for _outcome, dst in outcomes)
                    else:
                        all_remember_eligible = False

                if not targeted:
                    if all_remember_eligible and current_signature is not None:
                        destination_paths = tuple(sorted(set(destination_paths)))
                        self._decision_memory[scan_folder] = {
                            'source_signature': current_signature,
                            'settings_signature': current_settings,
                            'destination_paths': destination_paths,
                            'destination_signature': self._destinationSignature(destination_paths),
                            'group_count': len(groups),
                        }
                    else:
                        # Something this scan was not safely parkable, or
                        # the folder could not be fingerprinted -- forget any
                        # earlier memory for it rather than risk vouching for
                        # a folder that no longer matches what was recorded.
                        self._decision_memory.pop(scan_folder, None)

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
        # One `(outcome, dst)` entry per (src, dst) pair handled below, in
        # the order they are processed. `scan()` reads this back to decide
        # whether the group's decision is safe to remember (AC-QA-9): only
        # when it is non-empty and every outcome is one of
        # `REMEMBER_ELIGIBLE_OUTCOMES`, and it reads `dst` off the eligible
        # entries to know which library paths a remembered park depends on
        # (AC-QA-6). `outcome=None` marks a pair that was not a DECLINED_*
        # refusal at all -- a missing source, an ordinary move, or a failed
        # move -- and, like `REPLACE` itself, always makes the whole group
        # ineligible to remember.
        outcomes = []

        for src, dst in rename_files.items():
            if not os.path.exists(src):
                log.warning('Source file does not exist: %s', src)
                skipped = True
                outcomes.append((None, dst))
                continue

            if os.path.exists(dst):
                # NOT gated on `upgrade_replace`, and that is deliberate --
                # it was gated for one commit and the gating was wrong.
                #
                # The argument for gating is real: `.cp-upgrade-*.part` is
                # written by `replace_atomically` and nothing else, so on an
                # install that never enabled the feature this listdir looks
                # for something that cannot be there.
                #
                # But the setting is what an operator turns OFF after a swap
                # goes wrong. Gate on it and the sequence is: enable, a swap
                # is interrupted leaving a complete download under a hidden
                # name, disable the feature because of that failure -- and the
                # only thing that would have told them where their download
                # went now stays silent. The diagnostic goes dark precisely
                # when it is needed.
                #
                # One listdir, on a path that has already found a collision
                # and is about to do filesystem work anyway, is the cheaper
                # side of that trade by a wide margin.
                self._reportStaleStagingFiles(os.path.dirname(dst))
                # The replacement decision is COMPUTED and recorded, and then
                # deliberately not acted on -- the swap is wired in the next
                # step. Computing it here first is what proves the gate is
                # REACHABLE with real scan data: withdrawn attempt #2 was
                # simultaneously dangerous and inert, and the inertness is
                # what hid the danger, because the gate never fired in
                # testing so nobody saw what it did when it fired.
                # Identity BEFORE the decision, not after. It is a pure
                # dict-membership check with no I/O, while
                # `_replacementOutcome` pays for a `release.for_media` read
                # and a couple of event dispatches -- and a group whose
                # identity was guessed can never replace, so that work was
                # spent to reach a foregone conclusion. Same ordering
                # principle as the release lookup and the scan-size check.
                if not self._identityIsAsserted(group):
                    outcome, superseded = DECLINED_UNVERIFIED_IDENTITY, None
                else:
                    outcome, superseded = self._replacementOutcome(src, dst, group)

                # Scan-size FIRST, and its measurement is then reused.
                #
                # Ordering: establishing that the file is still what the
                # scanner measured comes before reasoning about whether its
                # size supports its claimed rung -- the second question is
                # meaningless if the answer to the first is no.
                #
                # Reuse: both checks stat the source, and on a NAS-mounted
                # download share (the case this module keeps calling out)
                # that is two round trips for one number.
                #
                # Inside the REPLACE guard, so an install that has not opted
                # into `upgrade_replace` -- the common case -- pays nothing on
                # an ordinary collision.
                measured_source_size = None
                if outcome == REPLACE:
                    measured_source_size = self._sourceStillMatchesTheScan(group, src)
                    if measured_source_size is None:
                        # The quality rung was derived from the scanner's
                        # measurement. If the bytes have moved since, the rung
                        # describes a file that no longer exists.
                        outcome = DECLINED_SOURCE_CHANGED

                if outcome == REPLACE and not self._sizeSupportsTheClaimedQuality(
                    group, src, measured_source_size
                ):
                    outcome = DECLINED_SIZE_CONTRADICTS_QUALITY

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
                        outcomes.append((REPLACE, dst))
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
                #
                # AC-OPS-3: bounded by `log_suppressed` independently of the
                # memory above. FEAT-009B already required this exact bound
                # once (its AC-OPS-6) and shipped unmet -- measured at 40
                # records for 20 calls, growing linearly -- because the bound
                # was proven only on a path that happened to go through
                # `log_suppressed` elsewhere. This method is also reachable
                # through a TARGETED scan, which per D8 never touches the
                # memory at all, so the backstop has to hold on its own.
                media_id = (group.get('media') or {}).get('_id')
                log_suppressed(
                    log.warning,
                    'renamer_collision:%s:%s' % (media_id, outcome),
                    'Destination already exists, keeping it: media %s '
                    '(upgrade decision: %s)',
                    media_id, outcome,
                )
                log.debug('The collided destination was: %s', dst)
                skipped = True
                outcomes.append((outcome, dst))
                continue

            try:
                self.moveFile(src, dst, use_default = True)
                log.info('Moved: %s -> %s', os.path.basename(src), dst)
                moved_any = True
                outcomes.append((None, dst))
            except Exception as e:
                log.error('Failed to move %s: %s', src, e)
                skipped = True
                outcomes.append((None, dst))

        # Never delete the source folder when anything was left behind. This is
        # the data-loss half: previously a skipped move was followed by cleanup,
        # so the file the user had just downloaded was skipped AND destroyed.
        if skipped:
            # DEBUG, not INFO: the WARNING above (or the "source file does
            # not exist" / "failed to move" record for whichever pair
            # skipped) already names the reason at a level that ships and
            # rotates unattended. Restating "not every file was moved" at
            # INFO on every one of those calls was the other half of the
            # AC-OPS-3 baseline (40 records for 20 calls: 20 WARNING plus 20
            # of this line), and it carries no information the caller does
            # not already have.
            log.debug('Leaving source folder in place: not every file was moved')
            return outcomes

        if moved_any and self.conf('cleanup', default = True):
            source_folder = group.get('parentdir')
            if source_folder and os.path.isdir(source_folder):
                self.deleteFolder(source_folder)

        return outcomes

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

        Checked against `conf('to')` and NOT against `media_folder`, and that
        is the point rather than an oversight.

        `_processGroup` builds the destination from `media_folder or
        conf('to')`, and `media_folder` arrives from the `renamer.scan` API as
        a request parameter. Trusting it would mean a caller could nominate
        any directory and have replacement destroy files there -- which is the
        exact thing this function exists to refuse. The library root is
        operator CONFIGURATION; a scan argument is a request, and the two do
        not carry the same authority.

        A targeted scan whose `media_folder` sits inside the library (the
        documented shape -- "specific media subfolder") passes normally. One
        pointing outside gets `declined_outside_library`, which is logged
        rather than silent, and only the DESTRUCTIVE path is affected: the
        ordinary move still writes wherever the caller asked.
        """
        root = self.conf('to')
        if not root:
            return False
        # `commonpath` is inside the guard too: it raises ValueError on paths
        # that share no root -- different drives on Windows, or a mix of
        # absolute and relative -- and everything else on this path is
        # deliberately hardened so nothing escapes into a scan. An unprovable
        # containment answers False, which refuses.
        try:
            root = os.path.realpath(sp(root))
            target = os.path.realpath(sp(destination))
            return os.path.commonpath([root, target]) == root
        except (OSError, ValueError):
            return False

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
        """Delegates to `logger.without_paths`.

        Kept as a method because the tests and several call sites use it that
        way, but the LOGIC lives in one place now: this was duplicated into
        release/main.py, the copy gated on `errno is not None`, and an OSError
        carrying only a filename fell through to `str()` and leaked the path.
        """
        return without_paths(error)

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
    def _sizeSupportsTheClaimedQuality(group, source, measured_size=None):
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

        # Reuse the measurement `_sourceStillMatchesTheScan` already took;
        # it runs first and stats the same file. Falling back to a fresh stat
        # keeps this callable on its own, which its unit tests rely on.
        if measured_size is None:
            try:
                measured_size = os.path.getsize(source)
            except OSError:
                return True
        megabytes = measured_size / 1024 / 1024

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

        # Detach FIRST, and the order is load-bearing rather than tidy.
        #
        # `Release.updateStatus` BACKFILLS copy_id when it moves a release to
        # `ignored`, from the sizes of the files the release still lists
        # (release/main.py). By this point `os.replace` has run, so the path
        # it lists holds the INCOMING file's bytes -- a legacy release with no
        # stored copy_id would be given one describing the file that just
        # replaced it.
        #
        # If the detach then failed, that release would sit there claiming the
        # destination with a copy_id that MATCHES the current bytes: ownership
        # resolution would read it as the verified owner at the OLD rung, and
        # authorise a later, worse copy to replace what is actually a better
        # one. Detaching first makes that state unreachable -- the backfill
        # finds no files and `copyIdentity` answers None.
        #
        # The failure mode this leaves is strictly milder, and it is named
        # here rather than only in the commit that chose it: these are two
        # independent best-effort writes with no transaction spanning them, so
        # a crash BETWEEN them leaves the superseded release detached (no
        # files, no copy_id) but still at `done` -- an orphaned "done with
        # nothing" record.
        #
        # Recoverable, and not destructive: the file is safely swapped either
        # way, and the release claims nothing, so it cannot be mistaken for
        # the owner of anything. The next scan can re-derive it. Compare the
        # alternative ordering, where the same crash leaves a release claiming
        # a path with an identity matching bytes it did not produce.
        self._detachSupersededClaim(superseded, destination)

        try:
            # `Release.updateStatus` CATCHES database errors and contention
            # and returns False, and the dispatcher contains handler
            # exceptions too -- so the try/except below never sees the
            # ordinary failure. The result has to be read.
            updated = fireEvent(
                'release.update_status', superseded['_id'], status = 'ignored',
                single = True,
            )
        except Exception as error:
            # Logged HERE and then short-circuited: the
            # shared report below would otherwise fire for the same single
            # failure and produce two differently-worded ERROR records for it.
            # One failure, one record -- otherwise the log implies two things
            # went wrong and neither entry tells the whole story.
            # `_withoutPaths`, not `format_exc`. The traceback's last line
            # embeds `OSError.filename` regardless of frame limit, which is
            # the same leak `_withoutPaths` was added for -- and this file is
            # otherwise meticulous about it.
            log.error(
                'Replaced the file for release %s but could not take it off '
                '"done": %s', superseded.get('_id'), self._withoutPaths(error),
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

    # ------------------------------------------------------------------
    # FEAT-011: the operator-initiated replacement. A SEPARATE entry point
    # from the automatic path above, sharing only the mechanical safety
    # net (the atomic swap, the re-entrancy guard, the library-containment
    # check) and never `decide_replacement` or `_identityIsAsserted` --
    # the operator naming a specific film and a specific file IS the
    # identity assertion (spec owner decision 1). `upgrade_replace` and
    # the quality comparison are deliberately never consulted here.
    # ------------------------------------------------------------------

    #: Marks a release document as claiming a file the OPERATOR placed by
    #: hand, distinct from every `identity_source` `folder_scanner
    #: .determineMedia` can produce (`ASSERTED_IDENTITY_SOURCES` above). An
    #: explicit, different marker, not one of those four, so a later read
    #: can tell an operator-authored release apart from one the automatic
    #: path derived.
    OPERATOR_IDENTITY_SOURCE = 'operator_placed'

    def operatorReplaceView(self, **kwargs):
        """API-facing entry point for an operator's replacement.

        Reads only `media_id` and `source` out of `kwargs` -- every other
        key is ignored, so a request carrying `destination`, `dst`, `to`,
        `path`, `media_folder` or `base_folder` cannot redirect the
        destructive step anywhere (AC-SEC-1). The destination is always
        resolved server-side, inside `_executeOperatorReplacement`, from
        the media's own release records.

        Runs the real work on a background thread rather than inline
        (spec owner decision 2): the prompting case is a 20.3 GB copy
        across NAS mounts, and answering synchronously would hold the
        request open for minutes. The thread is kept at
        `self._operator_thread` purely so a test can join it
        deterministically -- nothing else may depend on that attribute.
        """
        media_id = kwargs.get('media_id')
        source = kwargs.get('source')

        thread = threading.Thread(
            target=self._executeOperatorReplacement,
            args=(media_id, source),
        )
        thread.daemon = True
        self._operator_thread = thread
        thread.start()

        return {'success': True}

    def _executeOperatorReplacement(self, media_id, source_name):
        """Act on an operator's decision to replace a film's library copy.

        Synchronous worker for `operatorReplaceView`. `source_name` is a
        bare name (or relative path) chosen from a listing already
        produced under `conf('from')` -- never a full path supplied by a
        caller. Returns `(outcome, destination_or_None)`; `destination` is
        non-None only when `outcome` is `OPERATOR_REPLACE`.

        Holds the SAME re-entrancy guard `scan()` uses above (AC-ARCH-7):
        the check-and-set is atomic under `media_lock('renamer-scan')` and
        held only for that instant, so a second operator activation, or a
        scan, running at the same time is refused promptly rather than
        queued behind the first -- a per-route lock would queue it, which
        is the exact trap the spec calls out.
        """
        with media_lock('renamer-scan'):
            if self.renaming_started:
                log.info('Renamer is already running, refusing the operator replacement')
                return OPERATOR_REFUSED_ALREADY_RUNNING, None
            self.renaming_started = True

        try:
            return self._runOperatorReplacement(media_id, source_name)
        finally:
            with media_lock('renamer-scan'):
                self.renaming_started = False

    def _runOperatorReplacement(self, media_id, source_name):
        """The actual work, unguarded -- always called through
        `_executeOperatorReplacement`, never directly."""
        source = self._resolveOperatorSource(source_name)
        if source is None:
            return OPERATOR_REFUSED_SOURCE_OUTSIDE_WATCH_FOLDER, None

        releases = fireEvent(
            'release.for_media', media_id, require_complete=True, single=True,
        ) or []
        outcome, existing_release = decide_operator_replacement(releases)
        if outcome != OPERATOR_REPLACE:
            return outcome, None

        # The destination is the release's OWN recorded file, exactly as
        # it stands -- never recomputed from the naming template (spec's
        # fifth, derived decision). More than one recorded file is the
        # same "do not guess" shape as an ambiguous release: replacing one
        # of several risks destroying a file the operator did not choose.
        movie_files = (existing_release.get('files') or {}).get('movie') or []
        if len(movie_files) != 1:
            return OPERATOR_DECLINED_AMBIGUOUS_FILE, None
        destination = sp(movie_files[0])

        # AC-SEC-3: checked against `conf('to')` alone, via the SAME method
        # the automatic path uses -- no request-supplied folder is ever
        # consulted.
        if not self._destinationIsInsideTheLibrary(destination):
            return DECLINED_OUTSIDE_LIBRARY, None

        # The picker's OWN measurement, taken here, immediately before it
        # is handed to the swap -- never a value trusted from an earlier
        # step or from the caller.
        try:
            expected_source_size = os.path.getsize(source)
        except OSError:
            return REFUSED_NO_SOURCE, None

        incoming_quality = fireEvent(
            'quality.guess', files=[source],
            size=expected_source_size / 1024 / 1024, single=True,
        ) or {}

        media_doc = fireEvent('media.get', media_id, single=True) or {}
        group = {
            'media': {'_id': media_id},
            'identifier': media_doc.get('identifier') or media_id,
            'meta_data': {'quality': incoming_quality},
            'files': {'movie': [destination]},
            'identity_source': self.OPERATOR_IDENTITY_SOURCE,
        }

        # AC-SEC-4: the ONLY route to the destructive step, with a
        # measured, non-None `expected_source_size` and a
        # `destination_identity` from `swap.identity_of` -- so
        # `refused_source_is_symlink`, `refused_destination_is_symlink`,
        # `refused_same_file`, `refused_source_changed` and
        # `failed_destination_changed` all stay reachable here exactly as
        # they are on the automatic path.
        ok, reason = replace_atomically(
            source, destination,
            expected_source_size=expected_source_size,
            destination_identity=identity_of(destination),
            about_to_replace=lambda: self._announceImminentReplacement(
                source, destination, existing_release, group,
            ),
        )
        if not ok:
            return reason, None

        # Bookkeeping BEFORE disposal, and the order is not free -- the
        # same reasoning `_moveRenamedFiles` documents above for the
        # automatic path applies here unchanged: both are best-effort, and
        # a kill between them must leave the RECOVERABLE half-finished
        # state, which is the download still on disk with the database
        # already accounting for the swap that already happened, not the
        # download gone with nothing recording it.
        #
        # `release.add` first: without a release claiming the placed file
        # at its detected quality the media is permanently
        # `declined_no_owner` on every later decision (owner decision 4).
        fireEvent('release.add', group, single=True)
        self._supersedeRelease(existing_release, group, destination)

        # Owner decision 3: the operator's source is ALWAYS consumed now,
        # whatever `default_file_action` says -- only after the swap has
        # verified, never before.
        self._disposeOfOperatorSource(source, media_id)

        return OPERATOR_REPLACE, destination

    def _resolveOperatorSource(self, source_name):
        """Resolve the operator's chosen SOURCE name to a path confined to
        the configured watch folder, or None.

        AC-SEC-2. `os.path.realpath` on both the folder and the candidate,
        re-derived HERE rather than trusted from a name a caller echoes
        back, and refused -- never clamped -- when it lands outside. A
        relative traversal, an absolute path elsewhere on disk, a name
        containing a NUL byte and a symlink whose target escapes the
        folder all reach this refusal, proven the way
        `softchroot.chroot2abs` is proven
        (`couchpotato/core/softchroot.py:167-205`): the caller learns
        nothing about which hostile shape it was.

        The path returned is the LEXICAL join, not the realpath: a source
        that is itself a symlink, whose target still resolves inside the
        folder, is handed back as the symlink so that
        `replace_atomically`'s own `REFUSED_SOURCE_IS_SYMLINK` check still
        sees it as one rather than as the regular file it points at.
        """
        watch = self.conf('from')
        if not watch or not source_name:
            return None
        try:
            root = os.path.realpath(sp(watch))
            lexical = os.path.normpath(os.path.join(root, source_name))
            resolved = os.path.realpath(lexical)
        except (OSError, ValueError):
            # ValueError: a NUL byte in the name. OSError: a component that
            # cannot be resolved. Both are refusals, not exceptions to
            # propagate to a caller.
            return None
        if resolved != root and not resolved.startswith(root + os.path.sep):
            return None
        return lexical

    def _disposeOfOperatorSource(self, source, media_id=None):
        """Owner decision 3: the operator's source is ALWAYS removed after
        a verified swap, whatever `default_file_action` says.

        `_disposeOfSourceAfterReplacement` above leaves the source in
        place on `copy` and `link`, which is correct for the AUTOMATIC
        path -- but here it is exactly the trap the spec calls out: the
        next scan finds the operator's file again and repeats the refusal
        FEAT-012 exists to end, on exactly the setting values that cause
        it. The library already holds a verified complete copy at this
        point, so nothing is lost by removing the one left in the watch
        folder.

        Best-effort, same as the automatic path's equivalent: the swap has
        already succeeded, and nothing that happens to the download now
        can justify raising through a completed replacement.
        """
        try:
            os.remove(source)
        except OSError as error:
            log.warning(
                'Replaced the library copy for media %s, but could not '
                'remove the operator-placed source from the watch folder '
                'afterwards: %s', media_id, self._withoutPaths(error),
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

        # The latch is set only when the warning is actually EMITTED, not on
        # the first call. Setting it first looked equivalent and was not:
        # `self.conf` reads live, so an operator can enable "Delete Others" in
        # the settings UI without a restart. With the latch already flipped by
        # an earlier call made while the setting was off, every later call
        # returns before re-reading the config and the notice never comes --
        # which is exactly the silence D1 exists to prevent, arrived at by a
        # different door.
        if self.conf('remove_lower_quality_copies', default=False):
            Renamer._warned_dead_setting = True
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
        # Imported here rather than at module scope: release.main imports the
        # renamer package indirectly, and a top-level import closes the cycle.
        from couchpotato.core.plugins.release.main import INCOMPLETE_RELEASE_SET
        from couchpotato.core.plugins.renamer.replacement import (
            DECLINED_ERROR,
            DECLINED_INCOMPLETE_EVIDENCE,
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
            # be deleted. The SENTINEL means "the set is incomplete" --
            # distinct from an empty list, which means "this media genuinely
            # has no releases".
            #
            # Cached per group (AC-ARCH-5: one lookup per group, none per
            # file) AND compared against the sentinel by identity, NOT with
            # `is None`. Both halves matter: the cache came from this branch,
            # the sentinel from the one it merges into, and taking either side
            # of this merge whole would have dropped the other -- reinstating
            # a guard that `fireEvent` filters away, or a lookup per collided
            # file.
            releases = self._releasesForGroup(group, media_id)
            if releases is INCOMPLETE_RELEASE_SET:
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
        except Exception as error:
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
                # Distinct per group even when there is no media id. A
                # shared 'unknown' bucket meant one repeatedly-failing group
                # silenced every OTHER group that also failed before its id
                # was available -- which is the same failure this suppression
                # exists to stop, applied to the wrong axis. The digest is of
                # the destination, so it distinguishes without being a path.
                'renamer_replacement_decision_failed:%s' % (
                    (group.get('media') or {}).get('_id')
                    or 'nomedia-' + hashlib.sha1(
                        dst.encode('utf-8', 'replace')
                    ).hexdigest()[:12],
                ),
                'Could not decide on upgrade replacement: %s',
                self._withoutPaths(error),
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

        return self._moveRenamedFiles(rename_files, group)
