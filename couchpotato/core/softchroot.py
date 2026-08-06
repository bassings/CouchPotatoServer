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
            # abspath, not just rstrip and not merely normpath.
            #
            # (The operation named on THIS line matters: three of this
            # function's breaks on this branch came from edits made after
            # reading this comment, and `realpath` here reds eight existing
            # tests. The reasoning for abspath over realpath is 20 lines
            # down; this line must not contradict it.)
            #
            # `os.path.isdir` happily accepts
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
            #
            # normpath alone left two more spellings broken the same way.
            # Measured: a chroot of `./` normalises to `.`, so every absolute
            # path the browser hands back is then refused, and a relative
            # chroot works only until the process cwd moves. abspath pins both
            # at startup and normalises on the way (it calls normpath), so the
            # containment comparison in chroot2abs has a normalised prefix.
            #
            # abspath rather than realpath, deliberately. realpath would also
            # make the containment root the same object `isdir` validated,
            # which is the stricter choice -- but it REWRITES a symlinked
            # chroot into its target, and an operator whose library lives at a
            # symlinked path would find get_chroot(), and therefore every
            # directory value the settings UI shows them, silently changed
            # underneath. This is a safety-net PR and I have already
            # introduced one regression in this function by being clever.
            #
            # Two limits follow, both lexical, both recorded in
            # docs/technical-debt.md rather than left to be rediscovered: a
            # symlinked directory INSIDE the jail reaches its target, and a
            # chroot setting containing `..` AFTER a symlink component (e.g.
            # `srv/link/..`) resolves to a lexical ancestor rather than the
            # directory `isdir` accepted.
            #
            # Both need operator-authored input -- someone with write access
            # has to create the symlink, or type the setting. The FIRST is
            # then reachable from BOTH callers of chroot2abs, and the more
            # serious one is not the browse endpoint. `settings.py`'s
            # `saveView` PERSISTS the result into config.ini for `directory`
            # and `directories` options -- the renamer destination, the
            # library folders, the download dirs. So the residual is not
            # "a chrooted user can list a directory outside the jail", it is
            # "a chrooted user can point the renamer at one", which is a write
            # path against irreplaceable media.
            #
            # It is a residual, not a regression: before the traversal fix,
            # `../../mnt` was written through verbatim, which is strictly
            # worse. Via the browse endpoint it reads as:
            # measured, `chroot2abs('/link')` returns `<jail>/link` (normpath
            # is lexical and does not resolve symlinks), `is_subdir` agrees it
            # is inside, and `browser.py` lists the target's contents from
            # outside the jail. An earlier version of this comment claimed
            # neither was reachable, which was wrong and contradicted the note
            # in chroot2abs 80 lines down.
            #
            # That is an ACCEPTED residual risk, not an oversight: realpath
            # would close it and is refused above for the reason given there.
            # Recorded here so the trade-off is visible at the line that makes
            # it, rather than being rediscovered as a finding.
            # The rstrip is NOT redundant: abspath('/') is '/', and without it
            # chdir becomes '//', which is_root_abs and is_subdir both then
            # reject -- an operator with `soft_chroot = /` gets a browser that
            # refuses every path. That is the third fail-closed break of this
            # one function on this branch, so the root case is pinned in
            # SoftChrootUnnormalisedSetting rather than trusted to reading.
            self.chdir = os.path.abspath(chdir).rstrip(os.path.sep) + os.path.sep
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

        # Normalise, then refuse anything that lands outside the LEXICAL
        # chroot (see initialize: symlinks below the jail are not resolved). `path` is
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
