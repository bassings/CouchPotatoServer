"""Tag/untag/cleanup operations for the renamer."""
import fnmatch
import os
import shutil
import traceback

from couchpotato.core.helpers.variable import sp, fnEscape
from couchpotato.core.logger import CPLog

log = CPLog(__name__)


class CleanupMixin:
    """Mixin providing tag/untag/cleanup methods for the Renamer class."""

    def tagRelease(self, tag, group=None, release_download=None):
        if not tag:
            return

        text = """This file is from CouchPotato
It has marked this release as "%s"
This file hides the release from the renamer
Remove it if you want it to be renamed (again, or at least let it try again)
""" % tag

        tag_files = []

        if isinstance(group, dict):
            tag_files = [sorted(list(group['files']['movie']))[0]]
        elif isinstance(release_download, dict):
            if release_download.get('files', []):
                tag_files = [filename for filename in release_download.get('files', []) if os.path.exists(filename)]
            elif release_download['folder']:
                for root, folders, names in os.walk(sp(release_download['folder'])):
                    tag_files.extend([os.path.join(root, name) for name in names])

        for filename in tag_files:
            if os.path.splitext(filename)[1] == '.ignore':
                continue
            tag_filename = '%s.%s.ignore' % (os.path.splitext(filename)[0], tag)
            if not os.path.isfile(tag_filename):
                self.createFile(tag_filename, text)

    def untagRelease(self, group=None, release_download=None, tag=''):
        if not release_download:
            return

        tag_files = []
        folder = None

        if isinstance(group, dict):
            tag_files = [sorted(list(group['files']['movie']))[0]]
            folder = sp(group['parentdir'])
            if not group.get('dirname') or not os.path.isdir(folder):
                return False
        elif isinstance(release_download, dict):
            folder = sp(release_download['folder'])
            if not os.path.isdir(folder):
                return False
            if release_download.get('files'):
                tag_files = release_download.get('files', [])
            else:
                for root, folders, names in os.walk(folder):
                    tag_files.extend([sp(os.path.join(root, name)) for name in names if not os.path.splitext(name)[1] == '.ignore'])

        if not folder:
            return False

        ignore_files = []
        for root, dirnames, filenames in os.walk(folder):
            ignore_files.extend(fnmatch.filter([sp(os.path.join(root, filename)) for filename in filenames], '*%s.ignore' % tag))

        for tag_file in tag_files:
            ignore_file = fnmatch.filter(ignore_files, fnEscape('%s.%s.ignore' % (os.path.splitext(tag_file)[0], tag if tag else '*')))
            for filename in ignore_file:
                try:
                    os.remove(filename)
                except Exception:
                    log.debug('Unable to remove ignore file: %s. Error: %s.' % (filename, traceback.format_exc()))

    def hastagRelease(self, release_download, tag=''):
        if not release_download:
            return False

        folder = sp(release_download['folder'])
        if not os.path.isdir(folder):
            return False

        tag_files = []
        ignore_files = []

        if release_download.get('files'):
            tag_files = release_download.get('files', [])
        else:
            for root, folders, names in os.walk(folder):
                tag_files.extend([sp(os.path.join(root, name)) for name in names if not os.path.splitext(name)[1] == '.ignore'])

        for root, dirnames, filenames in os.walk(folder):
            ignore_files.extend(fnmatch.filter([sp(os.path.join(root, filename)) for filename in filenames], '*%s.ignore' % tag))

        for tag_file in [tag_files] if isinstance(tag_files, str) else tag_files:
            ignore_file = fnmatch.filter(ignore_files, fnEscape('%s.%s.ignore' % (os.path.splitext(tag_file)[0], tag if tag else '*')))
            if ignore_file:
                return True

        return False

    def deleteFolder(self, folder, check_empty=True):
        """Delete a folder after successful rename/move.
        
        Args:
            folder: Path to folder to delete
            check_empty: Only delete if folder is empty or contains only samples/metadata
        """
        folder = sp(folder)
        if not folder or not os.path.isdir(folder):
            return False

        try:
            # Get remaining files
            remaining = []
            for root, dirs, files in os.walk(folder):
                remaining.extend(files)

            # Check if folder is effectively empty (only samples/metadata remain)
            dominated_by_samples = True
            for f in remaining:
                if not any(x in f.lower() for x in ['sample', '.nfo', '.txt', '.jpg', '.png', '.ignore']):
                    dominated_by_samples = False
                    break

            if check_empty and remaining and not dominated_by_samples:
                log.debug('Folder %s still has files, not deleting: %s', folder, remaining[:5])
                return False

            log.info('Cleaning up folder: %s', folder)
            shutil.rmtree(folder)
            return True
        except Exception:
            log.error('Failed to delete folder %s: %s', folder, traceback.format_exc())
            return False
