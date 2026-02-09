"""Archive extraction for the renamer."""
import os
import re
import traceback

from couchpotato.core.helpers.variable import sp
from couchpotato.core.logger import CPLog
from couchpotato.lib.unrar2 import RarFile

log = CPLog(__name__)


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
            try:
                unrar_path = self.conf('unrar_path')
                unrar_path = unrar_path if unrar_path and (os.path.isfile(unrar_path) or re.match(r'^[a-zA-Z0-9_/\.\-]+$', unrar_path)) else None

                rar_handle = RarFile(archive['file'], custom_path=unrar_path)
                extr_path = os.path.join(from_folder, os.path.relpath(os.path.dirname(archive['file']), folder))
                self.makeDir(extr_path)
                for packedinfo in rar_handle.infolist():
                    extr_file_path = sp(os.path.join(extr_path, os.path.basename(packedinfo.filename)))
                    if not packedinfo.isdir and not os.path.isfile(extr_file_path):
                        log.debug('Extracting %s...', packedinfo.filename)
                        rar_handle.extract(condition=[packedinfo.index], path=extr_path, withSubpath=False, overwrite=False)
                        if self.conf('unrar_modify_date'):
                            try:
                                os.utime(extr_file_path, (os.path.getatime(archive['file']), os.path.getmtime(archive['file'])))
                            except Exception:
                                log.error('Rar modify date enabled, but failed: %s', traceback.format_exc())
                        extr_files.append(extr_file_path)
                del rar_handle
                if not cleanup and os.path.isfile(extr_file_path):
                    self.tagRelease(release_download={'folder': os.path.dirname(archive['file']), 'files': [archive['file']]}, tag='extracted')
            except Exception as e:
                log.error('Failed to extract %s: %s %s', archive['file'], e, traceback.format_exc())
                continue

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

    def keepFile(self, filename):
        for i in self.ignored_in_path:
            if i in filename.lower():
                log.debug('Ignored "%s" contains "%s".', filename, i)
                return False
        return True
