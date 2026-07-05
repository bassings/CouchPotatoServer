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
import os
import re
import traceback

import rarfile

from couchpotato.core.helpers.variable import sp
from couchpotato.core.logger import CPLog

log = CPLog(__name__)

# Shown once per scan when no external extractor tool is available for
# rarfile to shell out to.
NO_EXTRACTOR_TOOL_MESSAGE = (
    'No RAR extractor tool found (rarfile needs "unrar", "unar", "7z" or '
    '"7zz" on PATH). Skipping RAR extraction until one is installed. '
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
        warned_no_tool = False

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
                if not warned_no_tool:
                    log.warning(NO_EXTRACTOR_TOOL_MESSAGE)
                    warned_no_tool = True
                continue
            except rarfile.Error as e:
                log.error('Failed to extract %s: %s %s', archive['file'], e, traceback.format_exc())
                continue
            except Exception as e:
                log.error('Failed to extract %s: %s %s', archive['file'], e, traceback.format_exc())
                continue

            if not extracted:
                continue

            if self.conf('unrar_modify_date'):
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
        previous unrar2-based behavior) and any file that already exists at
        the destination is left alone (not re-extracted). Returns the list
        of paths that were extracted.

        Raises ``rarfile.RarCannotExec`` if no extractor tool (unrar/unar/
        7z/7zz/bsdtar) is available, and other ``rarfile.Error`` subclasses
        for archive problems (bad/corrupt archive, wrong password, etc).
        Callers should treat both as "skip this archive", not a hard
        failure -- the caller (``extractFiles``) does exactly that.
        """
        if custom_tool_path:
            rarfile.UNRAR_TOOL = custom_tool_path
            rarfile.tool_setup(force=True)

        extracted = []
        rar_handle = rarfile.RarFile(rar_path)
        try:
            for info in rar_handle.infolist():
                if info.isdir():
                    continue
                extr_file_path = sp(os.path.join(extr_path, os.path.basename(info.filename)))
                if os.path.isfile(extr_file_path):
                    continue
                log.debug('Extracting %s...', info.filename)
                with rar_handle.open(info) as source, open(extr_file_path, 'wb') as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                extracted.append(extr_file_path)
        finally:
            rar_handle.close()

        return extracted

    def keepFile(self, filename):
        for i in self.ignored_in_path:
            if i in filename.lower():
                log.debug('Ignored "%s" contains "%s".', filename, i)
                return False
        return True
