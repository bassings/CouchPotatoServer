import os
import sys


class SoftChrootInitError(IOError):
    """Error during soft-chroot initialization"""
    pass

class SoftChroot:
    """Soft Chroot module

    Provides chroot feature for interation with Web-UI. Since it is not real chroot, so the name is SOFT CHROOT.
    The module prevents access to entire file-system, allowing access only to subdirs of SOFT-CHROOT directory.
    """
    def __init__(self):
        self.enabled = None
        self.chdir = None

    def initialize(self, chdir):
        """ initialize module, by setting soft-chroot-directory

        Sets soft-chroot directory and 'enabled'-flag

        Args:
            self (SoftChroot) : self
            chdir (string) : absolute path to soft-chroot

        Raises:
            SoftChrootInitError: when chdir doesn't exist
        """

        orig_chdir = chdir

        if chdir:
            chdir = chdir.strip()

        if (chdir):
            # enabling soft-chroot:
            if not os.path.isdir(chdir):
                raise SoftChrootInitError(2, 'SOFT-CHROOT is requested, but the folder doesn\'t exist', orig_chdir)

            self.enabled = True
            # normpath, not just rstrip. `os.path.isdir` happily accepts
            # `/srv//media`, `/srv/./media` and `/srv/x/../media`, so an
            # operator's config.ini can hold any of them and the chroot
            # initialises cleanly. Once chroot2abs started normalising ITS
            # result, an unnormalised `chdir` meant the containment check
            # compared a normalised path against an unnormalised prefix and
            # never matched: every path was refused, including the chroot's
            # own root, and the log said it resolved outside the chroot --
            # which was not true. Fails closed, so it was never a hole; it
            # was a total functional break of the feature with a misleading
            # diagnosis, introduced by the traversal fix and found at review.
            self.chdir = os.path.normpath(chdir).rstrip(os.path.sep) + os.path.sep
        else:
            self.enabled = False

    def get_chroot(self):
        """Returns root in chrooted environment

        Raises:
            RuntimeError: when `SoftChroot` is not initialized OR enabled
        """
        if None == self.enabled:
            raise RuntimeError('SoftChroot is not initialized')
        if not self.enabled:
            raise RuntimeError('SoftChroot is not enabled')

        return self.chdir

    def is_root_abs(self, abspath):
        """ Checks whether absolute path @abspath is the root in the soft-chrooted environment"""
        if None == self.enabled:
            raise RuntimeError('SoftChroot is not initialized')

        if None == abspath:
            raise ValueError('abspath can not be None')

        if not self.enabled:
            # if not chroot environment : check, whether parent is the same dir:
            parent = os.path.dirname(abspath.rstrip(os.path.sep))
            return parent==abspath

        # in soft-chrooted env: check, that path == chroot
        path = abspath.rstrip(os.path.sep) + os.path.sep
        return self.chdir == path

    def is_subdir(self, abspath):
        """ Checks whether @abspath is subdir (on any level) of soft-chroot"""
        if None == self.enabled:
            raise RuntimeError('SoftChroot is not initialized')

        if None == abspath:
            return False

        if not self.enabled:
            return True

        if not abspath.endswith(os.path.sep):
            abspath += os.path.sep

        return abspath.startswith(self.chdir)

    def chroot2abs(self, path):
        """ Converts chrooted path to absolute path

        Raises:
            ValueError: when `path` resolves outside the soft chroot.
        """

        if None == self.enabled:
            raise RuntimeError('SoftChroot is not initialized')
        if not self.enabled:
            return path

        if None == path or len(path)==0:
            return self.chdir

        if not path.startswith(os.path.sep):
            path = os.path.sep + path

        # Normalise, then refuse anything that lands outside. `path` is
        # attacker-influenced: it arrives on the directory.list query string
        # and on settings values. Plain concatenation let '..' segments
        # through, and nothing downstream caught them by itself -- is_subdir
        # is a bare startswith, and abs2chroot only rejects a NON-EMPTY
        # result, so an empty directory outside the chroot came back as a
        # normal 200 and made this a directory-existence oracle.
        #
        # Refuse rather than clamp to the chroot root: silently rewriting a
        # traversal into a legitimate request hides the attempt from the
        # operator and returns a listing the caller did not ask for.
        #
        # The message deliberately carries neither the path nor the chroot.
        # It surfaces through api.py's handler, which logs a full traceback,
        # and PrivacyFilter redacts api keys and query parameters, not
        # filesystem paths -- so naming the path here would replace the
        # oracle with a disclosure.
        resolved = os.path.normpath(self.chdir[:-1] + path)
        root = self.chdir.rstrip(os.path.sep)
        if resolved != root and not resolved.startswith(root + os.path.sep):
            raise ValueError('path resolves outside the soft chroot')

        return resolved

    def abs2chroot(self, path, force = False):
        """ Converts absolute path to chrooted path"""

        if None == self.enabled:
            raise RuntimeError('SoftChroot is not initialized')

        if None == path:
            raise ValueError('path is empty')

        if not self.enabled:
            return path

        if path == self.chdir.rstrip(os.path.sep):
            return '/'

        resulst = None
        if not path.startswith(self.chdir):
            if (force):
                result = self.get_chroot()
            else:
                raise ValueError("path must starts with 'chdir': %s" % path)
        else:
            l = len(self.chdir)-1
            result = path[l:]

        return result
