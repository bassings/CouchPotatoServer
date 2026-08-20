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

#: Cap on per-entry log lines a single archive may produce, for ALL FIVE
#: per-entry counters: refusals, name collisions, unreadable entries, entries
#: that could not be written to their destination, and entries refused for
#: producing more than the fixed per-entry size ceiling (`_ENTRY_HARD_CAP`).
#: (This said "BOTH refusals and name collisions" until the third counter was
#: added a commit later and this line was not updated -- the same drift the
#: rest of this branch keeps correcting.)
#: `rarfile.infolist()` parses headers only, so a hostile
#: RAR carries thousands of poisoned entries for the cost of a header each --
#: unbounded per-entry logging is therefore an amplification vector, not a
#: nicety. Small, because the first few are diagnostic and the rest are noise;
#: `_logArchiveSummary` reports the totals so nothing is hidden by the cap.
_MAX_ENTRY_LOGS = 5

#: OSError errnos caused by THIS entry's destination rather than by the
#: machine, so they skip one entry instead of abandoning the archive.
#:
#: THE CRITERION, so the next member is derivable instead of discovered: an
#: errno belongs here when it says "this NAME/PATH is unusable" and NOT when it
#: says "this filesystem cannot serve a write right now". The first is
#: attacker-chosen and affects one entry; the second is the machine and will
#: fail identically for every entry that follows.
#:
#:   ENAMETOOLONG  the flattened name exceeds the filesystem's limit
#:   EISDIR        something already occupies the destination as a directory
#:   EILSEQ        the name is not encodable for this filesystem
#:                 (driven: a lone surrogate in an entry name aborted the
#:                 archive at os.replace)
#:   EINVAL        the name contains a byte or sequence the filesystem rejects
#:
#: NOT here, deliberately: ENOSPC, EACCES, EROFS, EIO, EDQUOT. Those are the
#: machine. Continuing past them would hand `extractFiles` a partial list which
#: it tags as extracted -- silently completing a release with files missing.
#:
#: This list was built one member at a time across three review rounds
#: (ENAMETOOLONG, then EISDIR, then EILSEQ), each found only after the previous
#: was fixed, because each round asked "which errno did I miss" instead of
#: "what is the category". The criterion above is the answer to the second
#: question and is why EINVAL is here without anyone having hit it yet.
_ENTRY_DERIVED_ERRNOS = frozenset((
    errno.ENAMETOOLONG,
    errno.EISDIR,
    errno.EILSEQ,
    errno.EINVAL,
))

#: T44, 2026-08-20: this file previously carried a per-entry cross-check
#: comparing bytes actually written against `info.file_size` (declared
#: header size) plus a margin. Review measured it dead on the pinned
#: `rarfile==4.5`, and worse than dead: actively unsafe.
#:
#: MEASURED, not assumed, against
#: `.venv/lib/python3.14/site-packages/rarfile.py`:
#:
#:   RarExtFile._open_extfile():  self._remain = self._inf.file_size
#:   RarExtFile.read(self, n=-1):
#:       if n is None or n < 0: n = self._remain
#:       elif n > self._remain: n = self._remain
#:       ...
#:       self._remain -= len(data)
#:
#: `PipeReader`/`DirectReader` (the two concrete readers `rarfile` actually
#: returns) override only `_read`/`readinto`, never the public `read()` this
#: file calls. So `read()` NEVER hands back more than `info.file_size` bytes
#: for an entry, regardless of how much the underlying decompressor is
#: willing to produce: `written <= declared` is an INVARIANT of this
#: library version, which makes `written > declared + margin` unreachable.
#: Three of the four tests the deleted cross-check shipped with only passed
#: because their fixture reader had no `_remain` and was therefore MORE
#: permissive than production -- the exact incidentally-passing shape
#: CLAUDE.md's guard-verification rule (11) exists to catch, caught here by
#: a second reviewer's own mutation, not by the tests themselves.
#:
#: The cross-check was also actively UNSAFE, not merely inert. RAR5
#: FILE_COPY/HARD_LINK redirects (`CommonParser.open()`) swap `inf` for the
#: ORIGINAL entry before opening it -- `inf = self.getinfo(redir_name)` --
#: so the stream that comes back is clamped to the ORIGINAL's file_size, not
#: the redirect entry's own. A redirect entry honestly declaring a small (or
#: zero) size for itself while pointing at a large legitimate file would have
#: had its real data refused by a budget computed from the wrong header.
#: Measured: a link entry declaring 0 got refused while the real media file
#: behind it kept streaming its true size. What WinRAR actually writes into
#: a real FILE_COPY/HARD_LINK header could not be settled on this machine
#: (no rar/unrar/7z/7zz/unar, only bsdtar) -- deleting the cross-check makes
#: that question moot rather than resolving it.
#:
#: What replaced it is ONE fixed ceiling, never derived from anything the
#: archive header claims: an entry whose header self-consistently says
#: "400 GiB" and then produces 400 GiB sails straight through rarfile's own
#: clamp, since that clamp only stops an entry producing MORE than its
#: header declares, not how large that declaration may honestly be. This is
#: the LIVE guard against the pinned library version, and because it checks
#: bytes ACTUALLY WRITTEN it is also defence-in-depth against a hypothetical
#: future rarfile that weakens or removes the `_remain` clamp entirely (see
#: the "NOTE for the next bump" at requirements.txt:52-55, about rarfile
#: 5.0's *unrelated* config-location break): if that clamp ever went away,
#: an entry could then both lie about its header AND overproduce, and this
#: ceiling would still catch it on actual output alone.
#:
#: Deliberately NOT derived from `shutil.disk_usage()`. A free-space-based
#: bound would make one extraction's outcome depend on how much OTHER,
#: unrelated data already sits on the volume: nondeterministic (races with
#: concurrent downloads/scans on the same disk), unrepresentable in a test
#: without faking disk state, and it would surprise an operator with an
#: extraction that fails today and would have succeeded yesterday against an
#: identical archive purely because something else filled the disk in the
#: meantime. A fixed ceiling is deterministic and directly testable instead.
#:
#: 200 GiB (the value this constant shipped with originally) bought nothing
#: over a tighter figure: a UHD Blu-ray remux, the largest legitimate single
#: media file this application is ever asked to manage, tops out around
#: 100 GB. 128 GiB leaves that real ceiling ~28 GiB of headroom without
#: leaving the attacker another 72 GiB of it to abuse for free.
#:
#: WHAT THIS DOES NOT DO, stated plainly because a second guard in this area
#: was already built and removed here for overclaiming (see git history on
#: this branch): this bounds ONE ENTRY, not an ARCHIVE. N entries each just
#: under 128 GiB still write N * 128 GiB combined, and a REFUSED entry still
#: writes up to just-under-128 GiB transiently to its temp file (unlinked
#: afterward, but present on disk while the entry streams) before this check
#: catches it. An archive-wide budget was attempted on this branch and
#: removed because it could not fire on the input it was built for: many
#: entries each individually tripping this per-entry cap contributed ZERO to
#: a running total, because a refused entry's bytes were discarded before
#: they were ever counted (measured: 26.7x the intended archive budget
#: written to disk with the running total still at zero). An archive of many
#: large or many small honest entries summing past any sane per-release
#: total is therefore OPEN DEBT, not fixed here.
_ENTRY_HARD_CAP = 128 * 1024 ** 3  # 128 GiB
#: **A THIRD limit this does not provide, raised in review of #280 and recorded
#: rather than fixed.** The cap is a fixed byte count, not a function of free
#: space, so on a volume with less than 128 GiB available a single hostile
#: entry exhausts the disk and raises `ENOSPC` BEFORE the cap can fire. That
#: errno is not in `_ENTRY_DERIVED_ERRNOS`, so the archive aborts, which is the
#: right response but arrives after the damage. Measured on the deployment this
#: project actually runs: extraction targets `/downloads`, a NAS share with
#: 1.9 TiB free, so 128 GiB fits with room to spare and the case does not bite
#: there. It bites on a smaller volume, and nothing here detects that.
#:
#: A free-space-derived bound was considered and rejected for making one
#: extraction's outcome depend on unrelated data already on the disk:
#: nondeterministic, hard to test without faking disk state, and surprising to
#: an operator. The better answer is the pre-flight frame recorded in T44:
#: `read()` clamps to `file_size`, and `file_redir` plus `getinfo()` resolve
#: RAR5 copy and hard-link targets from headers alone, so the sum of resolved
#: declared sizes is an exact upper bound computable BEFORE any byte is
#: written. Refusing on that sum, compared against free space, costs nothing
#: and writes nothing. It is not built.


class _ArchiveEntryTooLarge(Exception):
    """Raised internally by `_extractOneAtomic` when a single entry's ACTUAL
    output crosses the fixed `_ENTRY_HARD_CAP` -- never anything the archive
    header claims (see the note above `_ENTRY_HARD_CAP` for why the header
    cannot be trusted as a budget input, only rarfile's own clamp on it).

    Deliberately its own type, not `OSError`/`rarfile.Error`: the write
    SUCCEEDS every time this fires. There is no I/O failure to observe here,
    only an entry that keeps producing more bytes than it is allowed to, so
    it cannot share `_ENTRY_DERIVED_ERRNOS`'s handling -- nothing raises an
    OSError on this path.
    """

    def __init__(self, written, budget):
        super().__init__(
            'entry wrote at least %d bytes, exceeding the fixed %d-byte '
            'per-entry ceiling' % (written, budget))
        self.written = written
        self.budget = budget

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
            unwritable = 0
            oversized = 0
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
                        except _ArchiveEntryTooLarge as e:
                            # T44: this entry's ACTUAL output crossed the
                            # fixed per-entry ceiling -- never anything its
                            # header claims (rarfile's own read() already
                            # clamps output to the declared file_size; see
                            # the note above `_ENTRY_HARD_CAP`). The write
                            # ALWAYS succeeds here; there is no OSError to
                            # sort by errno, which is why this needs its own
                            # except clause rather than joining
                            # `_ENTRY_DERIVED_ERRNOS`.
                            #
                            # Attacker-controlled like a hostile name or a
                            # corrupt entry, so the same treatment applies:
                            # refuse this one, keep the archive. Its own
                            # counter for the same reason `unwritable` has
                            # one -- "refused for exceeding the fixed size
                            # ceiling" is a different remedy from "could not
                            # be read" or "could not be written". Note this
                            # bounds only THIS entry, not the archive as a
                            # whole -- see `_ENTRY_HARD_CAP`'s comment.
                            oversized += 1
                            if oversized <= _MAX_ENTRY_LOGS:
                                log.error(
                                    'Archive entry decompressed beyond the '
                                    'fixed %d-byte per-entry ceiling (wrote '
                                    'at least %d bytes before refusing it), '
                                    'skipping it: %r',
                                    _ENTRY_HARD_CAP, e.written, info.filename,
                                )
                            continue
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
                            if e.errno not in _ENTRY_DERIVED_ERRNOS:
                                raise
                            # Its OWN counter, not folded into `unreadable`.
                            # This entry WAS read; it could not be WRITTEN. An
                            # operator seeing "could not be read" would chase a
                            # corrupt archive, when the remedy is a filesystem
                            # name limit. Two causes, two remediations, two
                            # counts.
                            unwritable += 1
                            if unwritable <= _MAX_ENTRY_LOGS:
                                log.error('Archive entry could not be written '
                                          'to its destination (%s), skipping '
                                          'it: %r',
                                          errno.errorcode.get(e.errno, e.errno),
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
                # In the `finally`, because the counts matter MOST on an
                # aborted archive. Sitting after the try block, this was
                # skipped by exactly the paths that make it useful: an
                # environmental OSError, RarCannotExec, or any entry-derived
                # errno not yet in the set. The operator then saw five capped
                # per-entry lines, an abort, and no totals -- the diagnostic
                # deleted at the moment it was needed.
                self._logArchiveSummary(
                    refused, collisions, unreadable, unwritable, oversized)

        return extracted

    @staticmethod
    def _logArchiveSummary(refused, collisions, unreadable, unwritable, oversized):
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
        if unwritable > _MAX_ENTRY_LOGS:
            log.error('%d archive entries could not be written to their '
                      'destination in total (only the first %d were logged '
                      'individually).', unwritable, _MAX_ENTRY_LOGS)
        if oversized > _MAX_ENTRY_LOGS:
            log.error('%d archive entries exceeded the fixed per-entry size '
                      'ceiling and were refused in total (only the first %d '
                      'were logged individually).', oversized, _MAX_ENTRY_LOGS)

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
        temp file is removed so no partial output survives at the real path.

        The read loop enforces a per-entry byte ceiling against
        ``_ENTRY_HARD_CAP``, checked against bytes ACTUALLY WRITTEN -- never
        against ``info.file_size`` or anything else the archive header
        claims. See the note above ``_ENTRY_HARD_CAP`` for why a
        header-derived budget was tried and removed (measured unreachable
        against the pinned ``rarfile==4.5``, and actively unsafe besides),
        and for what this ceiling does and does not bound -- it stops ONE
        entry whose header honestly declares, and rarfile then honours, far
        more than any real media file this application manages; it does NOT
        bound an archive's total output across many entries.

        Raises ``_ArchiveEntryTooLarge`` -- checked BEFORE each chunk is
        written, so the temp file for a refused entry never grows past the
        ceiling, rather than silently truncating the entry. The caller
        treats this as a refusal, never as a successful partial extract.
        """
        # Temp file in the SAME directory so os.replace is atomic (same fs).
        fd, tmp_path = tempfile.mkstemp(dir=extr_path, prefix=_TEMP_PREFIX, suffix=_TEMP_SUFFIX)
        try:
            # fdopen first so the fd is always owned/closed by the `with`, even
            # if rar_handle.open(info) raises before we start reading.
            with os.fdopen(fd, 'wb') as target, rar_handle.open(info) as source:
                written = 0
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    # `written` counts bytes ON DISK, and the cap is tested
                    # against the PROSPECTIVE total, so the temp file never
                    # exceeds the cap even transiently. An earlier form
                    # incremented first and tested after, which meant a refusal
                    # reported the chunk it had just declined to write: up to
                    # 1 MiB of bytes that reached the reader and never reached
                    # the file, in a message that says "wrote". Diagnostics
                    # that overstate are how an operator ends up hunting the
                    # wrong entry.
                    #
                    # The comparison stays strict, so an entry that writes
                    # EXACTLY the cap is allowed through. That boundary is
                    # deliberate and is pinned by a test.
                    if written + len(chunk) > _ENTRY_HARD_CAP:
                        raise _ArchiveEntryTooLarge(written, _ENTRY_HARD_CAP)
                    target.write(chunk)
                    written += len(chunk)
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
