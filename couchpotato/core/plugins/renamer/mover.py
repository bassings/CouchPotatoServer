"""File moving/linking operations for the renamer."""
import os
import shutil
import traceback

from couchpotato.core.helpers.variable import link, symlink, sp
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env

log = CPLog(__name__)


def _discard_partial_destination(old, dest):
    """Remove `dest` when a transfer failed part-way through writing it.

    `shutil.move` falls back to `copy2`, which on a full disk or a dropped
    mount writes part of the file and then raises. T1.8 made that failure
    propagate, which stopped the caller deleting the source -- but it left a
    truncated file sitting at the library filename. `_moveRenamedFiles` then
    skipped that file on every subsequent run, because fix (a)'s `lexists`
    guard refuses a destination that already exists, so the retry could never
    succeed; and the scanner attached the truncated file to the movie.

    The default-move branch has cleaned this up since before T1.8. The `copy`
    and `symlink_reversed` branches did not, which is the same "fix the
    instance, miss the class" shape this area keeps producing.

    Deleting here cannot lose data: `old` is intact in every one of these
    cases, so the only copy being removed is one that is already wrong. The
    two ways that could stop being true are both refused:

    - the destination is the same size as the source, so the bytes did land
      and the failure came afterwards (`shutil.move`'s own final unlink of the
      source can fail on its own). Never discard a complete copy to tidy up
      after a failure that already succeeded at the part that matters.
    - the source cannot be sized at all, so complete and partial are
      indistinguishable and what is at the destination may be the only copy
      left. Keep it and let the exception carry the failure.
    """
    try:
        if not os.path.lexists(dest):
            return
        dest_size = os.path.getsize(dest)
        old_size = os.path.getsize(old)
    except OSError:
        log.warning('Could not compare "%s" with "%s" after a failed transfer, '
                    'leaving the destination in place: %s',
                    old, dest, traceback.format_exc(1))
        return

    if dest_size == old_size:
        return

    try:
        os.unlink(dest)
    except OSError:
        log.warning('Failed removing the partial destination "%s" (%s of %s '
                    'bytes); it will block every retry until removed by hand: %s',
                    dest, dest_size, old_size, traceback.format_exc(1))


class MoverMixin:
    """Mixin providing file move/copy/link methods for the Renamer class."""

    def moveFile(self, old, dest, use_default=False):
        dest = sp(dest)
        try:
            if os.path.lexists(dest):
                raise FileExistsError('Destination "%s" already exists' % dest)

            move_type = self.conf('file_action')
            if use_default:
                move_type = self.conf('default_file_action')

            if move_type not in ['copy', 'link', 'symlink_reversed']:
                try:
                    log.info('Moving "%s" to "%s"', old, dest)
                    shutil.move(old, dest)
                except Exception:
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
                try:
                    # copyfile, NOT copy. `shutil.copy` is copyfile+copymode,
                    # and when the bytes land but the chmod fails -- measured
                    # on a mount that refuses chmod, as some FUSE and CIFS
                    # setups do -- a COMPLETE destination is left behind. The
                    # cleanup below then correctly refuses to remove it (never
                    # discard a complete copy), and the `lexists` guard blocks
                    # every retry for ever: the same permanent poisoning the
                    # cleanup exists to remove, reached by a different door.
                    # moveFile sets the permission itself a few lines later
                    # and already treats that failure as non-fatal, so
                    # copymode was buying nothing here.
                    shutil.copyfile(old, dest)
                except Exception:
                    _discard_partial_destination(old, dest)
                    raise
            elif move_type == 'symlink_reversed':
                log.info('Reverse symlink "%s" to "%s"', old, dest)
                # A failed move must not be swallowed here: if nothing reached
                # `dest`, the caller (_moveRenamedFiles) must see this as a
                # failure, not a success -- otherwise cleanup deletes the only
                # copy of the file. Only the symlink-back is best-effort.
                #
                # The failure still propagates; the only thing this handler
                # does is take a truncated `dest` back out of the library
                # first, so the next run is able to retry at all.
                try:
                    # copy_function=copyfile, for the same reason the `copy`
                    # branch does not use `shutil.copy`: `shutil.move` is not
                    # a single operation either. On a cross-device move -- an
                    # SSD download dir and a NAS library, i.e. the ordinary
                    # setup -- it falls back to `copy2`, which is copyfile
                    # PLUS copystat, and copystat's chmod fails on the same
                    # mounts. Measured: the destination lands COMPLETE, the
                    # PermissionError propagates, the cleanup correctly
                    # refuses to delete a complete copy, and the `lexists`
                    # guard then blocks every retry for ever. Identical
                    # failure, identical door, third branch.
                    #
                    # NOT applied to the default-move branch above: that one
                    # already recovers (it unlinks the source on an equal-size
                    # destination and returns True), and forcing copyfile
                    # there would drop mtime preservation on the most common
                    # path for no benefit. Here mtime is already the accepted
                    # trade, as it is in `copy`.
                    shutil.move(old, dest, copy_function=shutil.copyfile)
                except Exception:
                    _discard_partial_destination(old, dest)
                    raise
                try:
                    symlink(dest, old)
                except Exception:
                    log.error('Error while linking "%s" back to "%s": %s', dest, old, traceback.format_exc())
            else:
                log.info('Linking "%s" to "%s"', old, dest)
                try:
                    log.debug('Hardlinking file "%s" to "%s"...', old, dest)
                    link(old, dest)
                except Exception:
                    log.debug('Couldn\'t hardlink file "%s" to "%s". Symlinking instead. Error: %s.', old, dest, traceback.format_exc())
                    # The same cleanup as the two branches above, and the one
                    # that matters most: `link` is the SHIPPING DEFAULT
                    # (renamer/api.py's `file_action` default), and the
                    # hardlink fails whenever the download directory and the
                    # library sit on different filesystems -- which is the
                    # ordinary setup, an SSD download dir and a NAS library.
                    # So this fallback copy is the most likely place in the
                    # whole function to meet a full disk, and it was the one
                    # branch left leaving a truncated file at the library
                    # filename. Fixing only the two branches that were
                    # reported would have been the same "fix the instance,
                    # miss the class" mistake this area keeps producing.
                    try:
                        # copyfile, not copy: see the `copy` branch above.
                        shutil.copyfile(old, dest)
                    except Exception:
                        _discard_partial_destination(old, dest)
                        raise
                    old_link = '%s.link' % sp(old)
                    try:
                        symlink(dest, old_link)
                        # os.replace is atomic and never unlinks `old` first:
                        # either it lands as the symlink, or `old` is left
                        # exactly as it was. The previous unlink-then-rename
                        # could leave `old` gone entirely if the rename failed
                        # in between.
                        os.replace(old_link, old)
                    except Exception:
                        log.error('Couldn\'t symlink file "%s" to "%s". Copied instead. Error: %s. ', old, dest, traceback.format_exc())
                        if os.path.lexists(old_link):
                            try:
                                os.unlink(old_link)
                            except Exception:
                                # WARNING, not DEBUG: setup_logging leaves the
                                # root logger at INFO unless --debug, so a
                                # DEBUG line here is emitted by nothing in
                                # production -- and what it reports is a
                                # `<file>.link` symlink left behind in the
                                # user's media library.
                                log.warning('Failed removing stray link file "%s": %s', old_link, traceback.format_exc())

            try:
                os.chmod(dest, Env.getPermission('file'))
                if os.name == 'nt' and self.conf('ntfs_permission'):
                    os.popen('icacls "' + dest + '"* /reset /T')
            except Exception:
                log.debug('Failed setting permissions for file: %s, %s', dest, traceback.format_exc(1))
        except Exception:
            log.error('Couldn\'t move file "%s" to "%s": %s', old, dest, traceback.format_exc())
            raise

        return True

    def fileIsAdded(self, src, group):
        if not group or not group.get('before_rename'):
            return False
        return src in group['before_rename']

    def moveTypeIsLinked(self):
        return self.conf('default_file_action') in ['copy', 'link', 'symlink_reversed']
