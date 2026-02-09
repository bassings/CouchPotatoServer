"""File moving/linking operations for the renamer."""
import os
import shutil
import traceback

from couchpotato.core.helpers.variable import link, symlink, sp
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env

log = CPLog(__name__)


class MoverMixin:
    """Mixin providing file move/copy/link methods for the Renamer class."""

    def moveFile(self, old, dest, use_default=False):
        dest = sp(dest)
        try:
            if os.path.exists(dest) and os.path.isfile(dest):
                raise Exception('Destination "%s" already exists' % dest)

            move_type = self.conf('file_action')
            if use_default:
                move_type = self.conf('default_file_action')

            if move_type not in ['copy', 'link', 'symlink_reversed']:
                try:
                    log.info('Moving "%s" to "%s"', old, dest)
                    shutil.move(old, dest)
                except:
                    exists = os.path.exists(dest)
                    if exists and os.path.getsize(old) == os.path.getsize(dest):
                        log.error('Successfully moved file "%s", but something went wrong: %s', dest, traceback.format_exc())
                        os.unlink(old)
                    else:
                        if exists:
                            os.unlink(dest)
                        raise
            elif move_type == 'copy':
                log.info('Copying "%s" to "%s"', old, dest)
                shutil.copy(old, dest)
            elif move_type == 'symlink_reversed':
                log.info('Reverse symlink "%s" to "%s"', old, dest)
                try:
                    shutil.move(old, dest)
                except:
                    log.error('Moving "%s" to "%s" went wrong: %s', old, dest, traceback.format_exc())
                try:
                    symlink(dest, old)
                except:
                    log.error('Error while linking "%s" back to "%s": %s', dest, old, traceback.format_exc())
            else:
                log.info('Linking "%s" to "%s"', old, dest)
                try:
                    log.debug('Hardlinking file "%s" to "%s"...', old, dest)
                    link(old, dest)
                except:
                    log.debug('Couldn\'t hardlink file "%s" to "%s". Symlinking instead. Error: %s.', old, dest, traceback.format_exc())
                    shutil.copy(old, dest)
                    try:
                        old_link = '%s.link' % sp(old)
                        symlink(dest, old_link)
                        os.unlink(old)
                        os.rename(old_link, old)
                    except:
                        log.error('Couldn\'t symlink file "%s" to "%s". Copied instead. Error: %s. ', old, dest, traceback.format_exc())

            try:
                os.chmod(dest, Env.getPermission('file'))
                if os.name == 'nt' and self.conf('ntfs_permission'):
                    os.popen('icacls "' + dest + '"* /reset /T')
            except:
                log.debug('Failed setting permissions for file: %s, %s', dest, traceback.format_exc(1))
        except:
            log.error('Couldn\'t move file "%s" to "%s": %s', old, dest, traceback.format_exc())
            raise

        return True

    def fileIsAdded(self, src, group):
        if not group or not group.get('before_rename'):
            return False
        return src in group['before_rename']

    def moveTypeIsLinked(self):
        return self.conf('default_file_action') in ['copy', 'link', 'symlink_reversed']
