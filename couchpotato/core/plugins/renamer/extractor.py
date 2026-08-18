"""Archive extraction for the renamer.

RAR is a proprietary format, so listing an archive's contents can be done
in pure Python (via the ``rarfile`` package) but actually decompressing
files requires shelling out to an external tool -- ``unrar``, ``unar``,
``7z``/``7zz``, or ``bsdtar``. ``rarfile`` auto-detects whichever of those
is available on PATH. When none is installed, extraction is skipped: a
single warning is logged per scan (naming the missing tool and how to
install one per OS) and the archive is left untouched -- the release is
NOT tagged or failed, it is simply retried on a later scan once a tool is
available.
"""
import errno
import glob
import os
import re
import tempfile
import threading
import traceback

import rarfile

from couchpotato.core.helpers.variable import isSubFolder, sp
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env

log = CPLog(__name__)

#: Cap on per-entry log lines a single archive may produce, for ALL FOUR
#: per-entry counters: refusals, name collisions, unreadable entries, and
#: names too long for the filesystem.
#: (This said "BOTH refusals and name collisions" until the third counter was
#: added a commit later and this line was not updated -- the same drift the
#: rest of this branch keeps correcting.)
#: `rarfile.infolist()` parses headers only, so a hostile
#: RAR carries thousands of poisoned entries for the cost of a header each --
#: unbounded per-entry logging is therefore an amplification vector, not a
#: nicety. Small, because the first few are diagnostic and the rest are noise;
#: `_logArchiveSummary` reports the totals so nothing is hidden by the cap.
_MAX_ENTRY_LOGS = 5

# rarfile forces the extractor tool to be selected via the process-global
# ``rarfile.UNRAR_TOOL`` (there is no per-call parameter), so setting it and
# then shelling out to it is shared mutable state. Serialize the whole
# tool-path-mutation + extraction critical section so overlapping renamer
# scans (e.g. a manual ``renamer.scan`` API trigger racing a scheduled one)
# cannot flip UNRAR_TOOL while another extraction is mid-flight. Extraction is
# rare and IO-bound, so a single coarse lock is fine.
_extract_lock = threading.Lock()

# Naming for the atomic-extract temp files. Kept as recognizable module
# constants so both the writer (tempfile.mkstemp) and the leftover-sweep use
# the exact same pattern. A hard kill (SIGKILL/OOM/power-loss) mid-extraction
# can orphan one of these; the sweep self-heals it on the next scan.
_TEMP_PREFIX = '.cp-extract-'
_TEMP_SUFFIX = '.part'
_TEMP_GLOB = _TEMP_PREFIX + '*' + _TEMP_SUFFIX

# rarfile's default extractor-tool name, captured at import before any custom
# path is applied. Used to restore auto-detection when the user clears the
# "Custom path to unrar bin" setting (rarfile.UNRAR_TOOL is a module global and
# otherwise stays pinned to the stale custom path forever). rarfile has no
# public "original tool" constant, so we snapshot UNRAR_TOOL at import time.
DEFAULT_UNRAR_TOOL = rarfile.UNRAR_TOOL

# Shown once per scan when no external extractor tool is available for
# rarfile to shell out to.
NO_EXTRACTOR_TOOL_MESSAGE = (
    'No RAR extractor tool found (rarfile needs "unrar", "unar", "7z", '
    '"7zz" or "bsdtar" on PATH). Skipping RAR extraction until one is installed. '
    'Windows: install UnRAR.exe or 7-Zip and add it to PATH (or set '
    '"Custom path to unrar bin" in Renamer settings). '
    'macOS: "brew install unar" (or "brew install rar"). '
    'Linux: install your distro\'s "unrar" or "unar" package. '
    'Alpine/Docker: "apk add 7zip" (already included in the official image).'
)


class ExtractorMixin:
    """Mixin providing archive extraction methods for the Renamer class."""

    def extractFiles(self, folder=None, media_folder=None, files=None, cleanup=False):
        if not files:
            files = []

        archive_regex = r'(?P<file>^(?P<base>(?:(?!\.part\d+\.rar$).)*)\.(?:(?:part0*1\.)?rar)$)'
        restfile_regex = r'(^%s\.(?:part(?!0*1\.rar$)\d+\.rar$|[rstuvw]\d+$))'
        extr_files = []

        from_folder = sp(self.conf('from'))

        if not folder:
            folder = from_folder

        check_file_date = True
        if media_folder:
            check_file_date = False

        if not files:
            if not isinstance(folder, (str, bytes, os.PathLike)):
                log.warning('extractFiles: folder is not a valid path type (%s), skipping', type(folder).__name__)
                return []
            for root, folders, names in os.walk(folder):
                files.extend([sp(os.path.join(root, name)) for name in names])

        archives = [re.search(archive_regex, name).groupdict() for name in files if re.search(archive_regex, name)]

        for archive in archives:
            if self.hastagRelease(release_download={'folder': os.path.dirname(archive['file']), 'files': archive['file']}):
                continue

            archive['files'] = [name for name in files if re.search(restfile_regex % re.escape(archive['base']), name)]
            archive['files'].append(archive['file'])

            if check_file_date:
                files_too_new, time_string = self.checkFilesChanged(archive['files'])
                if files_too_new:
                    log.info('Archive seems to be still copying/moving/downloading or just copied/moved/downloaded (created on %s), ignoring for now: %s', time_string, os.path.basename(archive['file']))
                    continue

            log.info('Archive %s found. Extracting...', os.path.basename(archive['file']))

            extr_path = os.path.join(from_folder, os.path.relpath(os.path.dirname(archive['file']), folder))
            self.makeDir(extr_path)

            unrar_path = self.conf('unrar_path')
            unrar_path = unrar_path if unrar_path and (os.path.isfile(unrar_path) or re.match(r'^[a-zA-Z0-9_/\.\-]+$', unrar_path)) else None

            try:
                extracted = self.extractArchive(archive['file'], extr_path, custom_tool_path=unrar_path)
            except rarfile.RarCannotExec:
                # Warn at most once per scan. Renamer.scan() resets
                # self._warned_no_tool at the start of every scan; a scan can
                # invoke extractFiles once per movie folder, so a local flag
                # would warn once per group instead of once per scan.
                if not getattr(self, '_warned_no_tool', False):
                    log.warning(NO_EXTRACTOR_TOOL_MESSAGE)
                    self._warned_no_tool = True
                continue
            except rarfile.Error as e:
                # Known archive problem (corrupt/bad RAR, wrong password, etc.).
                log.error('Skipping archive with a known RAR problem %s: %s %s', archive['file'], e, traceback.format_exc())
                continue
            except Exception as e:
                # Anything else (I/O error, permissions, unexpected bug).
                log.error('Unexpected error extracting %s: %s %s', archive['file'], e, traceback.format_exc())
                continue

            # extractArchive() returns every target file present after the call
            # -- newly written AND already-present (the idempotency contract), so
            # a fully-extracted archive (e.g. files written then a crash before
            # tagRelease persisted) still reaches the tag + cleanup below on the
            # next scan. An empty list therefore means the archive had no real
            # file entries at all (directory-only / empty): nothing to tag,
            # date-stamp, or move on, so skipping is correct.
            if not extracted:
                continue

            if self.conf('unrar_modify_date'):
                # extracted may include already-present files (idempotency);
                # re-stamping their mtime from the archive on a re-scan before
                # the release is tagged is a harmless, idempotent refresh.
                for extr_file_path in extracted:
                    try:
                        os.utime(extr_file_path, (os.path.getatime(archive['file']), os.path.getmtime(archive['file'])))
                    except Exception:
                        log.error('Rar modify date enabled, but failed: %s', traceback.format_exc())

            extr_files.extend(extracted)

            if not cleanup:
                self.tagRelease(release_download={'folder': os.path.dirname(archive['file']), 'files': [archive['file']]}, tag='extracted')

            for filename in archive['files']:
                if cleanup:
                    try:
                        os.remove(filename)
                    except Exception as e:
                        log.error('Failed to remove %s: %s %s', filename, e, traceback.format_exc())
                        continue
                files.remove(filename)

        if extr_files and folder != from_folder:
            for leftoverfile in list(files):
                move_to = os.path.join(from_folder, os.path.relpath(leftoverfile, folder))
                try:
                    self.makeDir(os.path.dirname(move_to))
                    self.moveFile(leftoverfile, move_to, cleanup)
                except Exception as e:
                    log.error('Failed moving left over file %s to %s: %s %s', leftoverfile, move_to, e, traceback.format_exc())
                    if os.path.isfile(move_to) and os.path.getsize(leftoverfile) == os.path.getsize(move_to):
                        if cleanup:
                            log.info('Deleting left over file %s instead...', leftoverfile)
                            os.unlink(leftoverfile)
                    else:
                        continue
                files.remove(leftoverfile)
                extr_files.append(move_to)

            if cleanup:
                log.debug('Removing old movie folder %s...', media_folder)
                self.deleteEmptyFolder(media_folder)

            media_folder = os.path.join(from_folder, os.path.relpath(media_folder, folder))
            folder = from_folder

        if extr_files:
            files.extend(extr_files)

        if not media_folder:
            files = []
            folder = None

        return folder, media_folder, files, extr_files

    def extractArchive(self, rar_path, extr_path, custom_tool_path=None):
        """Extract every file in a RAR archive (and its parts) into extr_path.

        Files are flattened to their basename in extr_path (matching the
        previous unrar2-based behavior). A file that already exists at the
        destination is not re-written (the extract I/O is skipped), but its
        destination path IS still included in the returned list: the return
        value is the set of target files present at the destination after
        the call -- newly written OR already present.

        This matters for idempotency: if the process crashes after the files
        were written to disk but before the caller persisted the "extracted"
        tag, the next scan finds every target already present. Returning them
        (rather than an empty list) lets ``extractFiles`` still tag and clean
        up the release instead of retrying it forever. The returned list is
        empty only for a genuinely empty/all-directory archive.

        Each entry is written atomically: it streams to a temporary file in
        the destination directory and is only ``os.replace``-d into place once
        the full read/write succeeds. If any read/write raises partway (disk
        full, permission revoked, mid-stream CRC error), the temp file is
        unlinked and no partial file is ever left at the real destination, so a
        transient I/O hiccup cannot leave a truncated file that a later scan
        mistakes for "already extracted".

        Raises ``rarfile.RarCannotExec`` if no extractor tool (unrar/unar/
        7z/7zz/bsdtar) is available, and other ``rarfile.Error`` subclasses
        for archive problems (bad/corrupt archive, wrong password, etc). On
        either failure it extracts nothing/raises, so the caller skips the
        archive without tagging it -- the caller (``extractFiles``) does
        exactly that.
        """
        # rarfile.UNRAR_TOOL is a process-global; hold the lock across setting
        # it AND the whole extraction so a concurrent scan cannot swap the tool
        # out from under an in-flight extraction (see _extract_lock above).
        with _extract_lock:
            if custom_tool_path:
                # Pin rarfile to the user-provided binary and force it to re-probe.
                if rarfile.UNRAR_TOOL != custom_tool_path:
                    rarfile.UNRAR_TOOL = custom_tool_path
                    rarfile.tool_setup(force=True)
            elif rarfile.UNRAR_TOOL != DEFAULT_UNRAR_TOOL:
                # A previous call pinned a custom path; the setting has since been
                # cleared. Restore rarfile's default auto-detection (UNRAR_TOOL is
                # a module-global, so it would otherwise stay stale forever).
                rarfile.UNRAR_TOOL = DEFAULT_UNRAR_TOOL
                rarfile.tool_setup(force=True)

            # Self-heal: a prior run hard-killed mid-extraction can leave a
            # stray .cp-extract-*.part in this dir, which would make
            # deleteEmptyFolder's rmdir fail with ENOTEMPTY forever. Sweep it.
            self._sweepStrayTempFiles(extr_path)

            # NOT sp()-normalised, deliberately, and this was measured rather
            # than assumed. When extr_path itself contains a backslash -- legal
            # on POSIX, and choosable by a hostile torrent naming its folder --
            # sp() rewrites the TARGET into a tree that does not exist, so no
            # entry can be written either way. The question is only which way
            # it fails:
            #
            #   base without sp(): contained=False -> refused, loop continues
            #   base with    sp(): contained=True  -> write into a missing dir,
            #                                         raises, ABANDONS the archive
            #
            # Applying sp() here therefore trades a clean per-entry refusal for
            # an exception that sinks everything else in the archive. Tried it,
            # measured it, reverted it. The real defect is sp() mangling
            # extr_path, which is out of scope here -- tracked as T41.
            extr_real_path = os.path.realpath(extr_path)
            refused = 0
            collisions = 0
            unreadable = 0
            too_long = 0
            extracted = []
            # Parallel set purely for membership. `extracted` stays a list
            # because its ORDER is the return contract, but `x in list` is a
            # linear scan, so collision detection was O(n^2) on exactly the
            # input this function treats as hostile: an archive with thousands
            # of entries, which costs the attacker one header each.
            seen = set()
            rar_handle = rarfile.RarFile(rar_path)
            try:
                for info in rar_handle.infolist():
                    if info.isdir():
                        continue
                    entry_name = self._safeEntryBasename(info.filename)
                    extr_file_path = sp(os.path.join(extr_path, entry_name))
                    if entry_name in ('', '.', '..') or not isSubFolder(extr_file_path, extr_real_path):
                        # Two refusal reasons sharing one path, so every
                        # rejected shape behaves identically.
                        #
                        # NAME: entries that sanitize to nothing useful -- '',
                        # '.', '..', and anything ending in a separator, which
                        # basename reduces to ''. Those join back to extr_path
                        # ITSELF, and isSubFolder accepts equality, so
                        # containment alone waves them through into
                        # `os.replace(tmp, <a directory>)` -> IsADirectoryError,
                        # which escapes extractArchive and abandons the WHOLE
                        # archive: a permanent per-release wedge on an
                        # unattended server.
                        #
                        # CONTAINMENT: belt-and-braces for any shape that
                        # defeats the sanitization, whatever the next one is.
                        #
                        # Refuse this entry only -- one hostile name must not
                        # sink the archive -- and log the entry NAME, bounded.
                        # Not rar_path, not the resolved destination: those add
                        # nothing an operator needs, and PrivacyFilter redacts
                        # only /home/<user> and /Users/<user>, so every NAS
                        # layout would have gone to disk in full. %r because the
                        # name may contain newlines.
                        refused += 1
                        if refused <= _MAX_ENTRY_LOGS:
                            log.error(
                                'Refusing to extract archive entry outside the '
                                'extraction directory: %r', info.filename,
                            )
                        continue
                    if not os.path.isfile(extr_file_path):
                        # %r, not %s: the entry name is attacker-controlled and
                        # may contain newlines, which interpolated raw let a
                        # crafted archive write whole fake log records. This is
                        # the REACHABLE forging vector -- the refusal line above
                        # cannot be, since only '', '.' and '..' are refused and
                        # none can carry a newline. Found by a test whose premise
                        # was wrong: it aimed at the refusal path and failed
                        # because the entry was never refused.
                        log.debug('Extracting %r...', info.filename)
                        try:
                            self._extractOneAtomic(
                                rar_handle, info, extr_file_path, extr_path)
                        except rarfile.RarCannotExec:
                            # The extractor TOOL is missing. Environmental, and
                            # it will fail identically for every remaining
                            # entry, so it must reach the caller -- that is what
                            # surfaces NO_EXTRACTOR_TOOL_MESSAGE ("apk add
                            # 7zip") instead of a thousand skipped entries and
                            # an archive quietly reported as empty.
                            #
                            # Caught BEFORE rarfile.Error because it subclasses
                            # it. A pre-existing test found this within seconds
                            # of the broader catch going in, which is the whole
                            # argument for the narrow one.
                            raise
                        except OSError as e:
                            # ENAMETOOLONG is an OSError, but it is derived
                            # from THIS entry's attacker-controlled name, not
                            # from the environment -- driven, a 300-character
                            # entry name gives errno 63 out of `os.replace`
                            # and aborted the archive, so `good.mkv` sitting
                            # after it never extracted.
                            #
                            # That correction matters more than the case: the
                            # axis is not "rarfile.Error vs OSError", it is
                            # "caused by this entry or by the machine". Sorting
                            # by exception TYPE looked like the same thing and
                            # is not, which is why one hostile name still got
                            # through a split written specifically to stop
                            # hostile names.
                            #
                            # Only ENAMETOOLONG, deliberately. ENOSPC, EACCES,
                            # EROFS and EIO are the machine, will fail
                            # identically for every remaining entry, and must
                            # still abort rather than hand `extractFiles` a
                            # partial list it tags as extracted.
                            if e.errno != errno.ENAMETOOLONG:
                                raise
                            # Its OWN counter, not folded into `unreadable`.
                            # This entry WAS read; it could not be WRITTEN. An
                            # operator seeing "could not be read" would chase a
                            # corrupt archive, when the remedy is a filesystem
                            # name limit. Two causes, two remediations, two
                            # counts.
                            too_long += 1
                            if too_long <= _MAX_ENTRY_LOGS:
                                log.error('Archive entry name is too long for '
                                          'this filesystem, skipping it: %r',
                                          info.filename)
                            continue
                        except rarfile.Error:
                            # A corrupt or unreadable ENTRY is attacker-
                            # controlled, so it gets the same treatment as a
                            # hostile name: refuse this one, keep the archive.
                            # Without this the invariant was only half true --
                            # one bad entry among a thousand still aborted
                            # everything after it.
                            #
                            # Deliberately `rarfile.Error` and NOT `Exception`.
                            # An OSError here (disk full, permissions, the
                            # filesystem going away) is ENVIRONMENTAL, and
                            # continuing would hand `extractFiles` a partial
                            # list which it then tags as extracted -- silently
                            # completing a release with files missing. Aborting
                            # leaves it untagged and retried next scan, which
                            # is the recoverable outcome. Attacker-controlled
                            # failures are per-entry; environmental failures
                            # are not.
                            unreadable += 1
                            if unreadable <= _MAX_ENTRY_LOGS:
                                log.error('Could not read archive entry, '
                                          'skipping it: %r', info.filename)
                            continue
                    # Report the target path whether we just wrote it or it was
                    # already present -- an already-extracted archive is a success,
                    # not a no-op, so the caller can still tag/clean it up. Dedupe:
                    # two entries that flatten to the same basename (e.g. a top-level
                    # file and a same-named one under Sample/) map to one destination,
                    # so the contract "distinct target files present" must hold.
                    if extr_file_path in seen:
                        # BOUNDED for the same reason the refusal above is: an
                        # earlier version of this very commit capped refusals
                        # and then added this warning uncapped, which is the
                        # identical amplification vector two hunks apart.
                        #
                        # Visible, because the loser is discarded silently and
                        # the release is still tagged extracted. Driven:
                        #
                        #   ['movie.mkv', 'Sample\\movie.mkv'] -> FEATURE-20GB
                        #   ['Sample\\movie.mkv', 'movie.mkv'] -> SAMPLE-50MB
                        #
                        # Archive ORDER decides, so in the bad order a 50MB
                        # sample replaces the feature and nobody is told.
                        # Long-standing for `Sample/` (RAR3); T36 widens it to
                        # `Sample\\` (RAR5), which previously crashed instead.
                        # Warn only -- picking a winner is a behaviour change
                        # that does not belong in a security fix. See T43.
                        collisions += 1
                        if collisions <= _MAX_ENTRY_LOGS:
                            log.warning(
                                'Two archive entries flatten to the same name; '
                                'the later one is discarded and which wins '
                                'depends on archive order: %r', info.filename,
                            )
                    else:
                        seen.add(extr_file_path)
                        extracted.append(extr_file_path)
            finally:
                rar_handle.close()
            self._logArchiveSummary(refused, collisions, unreadable, too_long)

        return extracted

    @staticmethod
    def _logArchiveSummary(refused, collisions, unreadable, too_long):
        """Report totals when per-entry logging was capped.

        The cap exists so a hostile archive cannot flood the log, but a cap
        with no summary hides how bad the archive was -- an operator sees five
        lines and cannot tell five poisoned entries from five thousand. An
        earlier version of this code promised "a count follows at the end" in
        the truncation notice and never emitted one, which is worse than
        silence: a log line that tells the reader to wait for something that
        never arrives.

        Counts only, deliberately: no paths, no entry names.
        """
        if refused > _MAX_ENTRY_LOGS:
            log.error('%d archive entries were refused in total (only the first '
                      '%d were logged individually).', refused, _MAX_ENTRY_LOGS)
        if collisions > _MAX_ENTRY_LOGS:
            log.warning('%d archive entries collided on the same destination in '
                        'total (only the first %d were logged individually).',
                        collisions, _MAX_ENTRY_LOGS)
        if unreadable > _MAX_ENTRY_LOGS:
            log.error('%d archive entries could not be read in total (only the '
                      'first %d were logged individually).',
                      unreadable, _MAX_ENTRY_LOGS)
        if too_long > _MAX_ENTRY_LOGS:
            log.error('%d archive entry names were too long for this '
                      'filesystem in total (only the first %d were logged '
                      'individually).', too_long, _MAX_ENTRY_LOGS)

    @staticmethod
    def _safeEntryBasename(filename):
        """Return just the final path component of an archive-supplied entry
        name, treating BOTH '/' and '\\' as separators.

        Archive formats (RAR, ZIP) are portable and an entry name is
        attacker-controlled, so it can carry a backslash as a directory
        separator even when extraction runs on POSIX, where
        ``os.path.basename`` only recognises '/'. Left alone, a name like
        ``..\\..\\..\\evil.txt`` survives ``os.path.basename`` completely
        intact, and ``sp()``'s Windows-path handling (needed elsewhere for
        genuine remote-Windows-box paths, so not something to change here)
        then anchors the joined path at the filesystem root -- walking the
        extraction straight out of ``extr_path``. Normalising '\\' to '/'
        before taking the basename neutralises that without touching
        ``sp()`` itself.

        This alone is NOT sufficient (see the containment check at the call
        site): a bare ``..`` has no separator at all, so basename returns it
        completely unchanged regardless of this normalisation.
        """
        return os.path.basename(filename.replace('\\', '/'))

    @staticmethod
    def _sweepStrayTempFiles(extr_path):
        """Remove any leftover atomic-extract temp files in extr_path. These
        can only survive a hard kill (the normal error path unlinks them); a
        stray one blocks empty-folder cleanup (rmdir -> ENOTEMPTY) forever."""
        for stray in glob.glob(os.path.join(extr_path, _TEMP_GLOB)):
            try:
                os.unlink(stray)
                log.debug('Removed stray extract temp file %s', stray)
            except OSError:
                pass

    @staticmethod
    def _extractOneAtomic(rar_handle, info, extr_file_path, extr_path):
        """Stream a single archive entry to a temp file in extr_path, then
        atomically ``os.replace`` it into extr_file_path. On ANY error the
        temp file is removed so no partial output survives at the real path."""
        # Temp file in the SAME directory so os.replace is atomic (same fs).
        fd, tmp_path = tempfile.mkstemp(dir=extr_path, prefix=_TEMP_PREFIX, suffix=_TEMP_SUFFIX)
        try:
            # fdopen first so the fd is always owned/closed by the `with`, even
            # if rar_handle.open(info) raises before we start reading.
            with os.fdopen(fd, 'wb') as target, rar_handle.open(info) as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
            # tempfile.mkstemp always creates the file 0600 (owner-only),
            # ignoring umask; without this the extracted media file would be
            # unreadable by Plex/Kodi/other users (and broken under the Docker
            # PUID/PGID drop-privilege setup). Apply the configured file
            # permission before the atomic rename, matching mover.py.
            os.chmod(tmp_path, Env.getPermission('file'))
            os.replace(tmp_path, extr_file_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def keepFile(self, filename):
        for i in self.ignored_in_path:
            if i in filename.lower():
                log.debug('Ignored "%s" contains "%s".', filename, i)
                return False
        return True
