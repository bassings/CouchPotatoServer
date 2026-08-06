import sys
import os
import logging
import unittest
from unittest import TestCase

from couchpotato.core.softchroot import SoftChroot

CHROOT_DIR = '/tmp/'

class SoftChrootNonInitialized(TestCase):
    def setUp(self):
        self.b = SoftChroot()

    def test_is_root_abs(self):
        with self.assertRaises(RuntimeError):
            self.b.is_root_abs('1')

    def test_is_subdir(self):
        with self.assertRaises(RuntimeError):
            self.b.is_subdir('1')

    def test_chroot2abs(self):
        with self.assertRaises(RuntimeError):
            self.b.chroot2abs('1')

    def test_abs2chroot(self):
        with self.assertRaises(RuntimeError):
            self.b.abs2chroot('1')

    def test_get_root(self):
        with self.assertRaises(RuntimeError):
            self.b.get_chroot()

class SoftChrootNOTEnabledTest(TestCase):
    def setUp(self):
        self.b = SoftChroot()
        self.b.initialize(None)

    def test_get_root(self):
        with self.assertRaises(RuntimeError):
            self.b.get_chroot()

    def test_chroot2abs_noleading_slash(self):
        path = 'no_leading_slash'
        self.assertEqual( self.b.chroot2abs(path), path )

    def test_chroot2abs(self):
        self.assertIsNone( self.b.chroot2abs(None), None )
        self.assertEqual( self.b.chroot2abs(''), '' )
        self.assertEqual( self.b.chroot2abs('/asdf'), '/asdf' )

    def test_abs2chroot_raise_on_empty(self):
        with self.assertRaises(ValueError):
            self.b.abs2chroot(None)

    def test_abs2chroot(self):
        self.assertEqual( self.b.abs2chroot(''), '' )
        self.assertEqual( self.b.abs2chroot('/asdf'), '/asdf' )
        self.assertEqual( self.b.abs2chroot('/'), '/' )

    def test_get_root(self):
        with self.assertRaises(RuntimeError):
            self.b.get_chroot()

class SoftChrootEnabledTest(TestCase):
    def setUp(self):
        self.b = SoftChroot()
        self.b.initialize(CHROOT_DIR)

    def test_enabled(self):
        self.assertTrue( self.b.enabled)

    def test_is_subdir(self):
        self.assertFalse( self.b.is_subdir('') )
        self.assertFalse( self.b.is_subdir(None) )

        self.assertTrue( self.b.is_subdir(CHROOT_DIR) )
        noslash = CHROOT_DIR[:-1]
        self.assertTrue( self.b.is_subdir(noslash) )

        self.assertTrue( self.b.is_subdir(CHROOT_DIR + 'come') )

    def test_is_root_abs_none(self):
        with self.assertRaises(ValueError):
            self.assertFalse( self.b.is_root_abs(None) )

    def test_is_root_abs(self):
        self.assertFalse( self.b.is_root_abs('') )

        self.assertTrue( self.b.is_root_abs(CHROOT_DIR) )
        noslash = CHROOT_DIR[:-1]
        self.assertTrue( self.b.is_root_abs(noslash) )

        self.assertFalse( self.b.is_root_abs(CHROOT_DIR + 'come') )

    def test_chroot2abs_noleading_slash(self):
        path = 'no_leading_slash'
        path_sl = CHROOT_DIR + path
        #with self.assertRaises(ValueError):
        #    self.b.chroot2abs('no_leading_slash')
        self.assertEqual( self.b.chroot2abs(path), path_sl )

    def test_chroot2abs(self):
        self.assertEqual( self.b.chroot2abs(None), CHROOT_DIR )
        self.assertEqual( self.b.chroot2abs(''), CHROOT_DIR )

        self.assertEqual( self.b.chroot2abs('/asdf'), CHROOT_DIR + 'asdf' )

    def test_abs2chroot_raise_on_empty(self):
        with self.assertRaises(ValueError): self.b.abs2chroot(None)
        with self.assertRaises(ValueError): self.b.abs2chroot('')

    def test_abs2chroot(self):
        self.assertEqual( self.b.abs2chroot(CHROOT_DIR + 'asdf'), '/asdf' )
        self.assertEqual( self.b.abs2chroot(CHROOT_DIR), '/' )
        self.assertEqual( self.b.abs2chroot(CHROOT_DIR.rstrip(os.path.sep)), '/' )

    def test_get_root(self):
        self.assertEqual( self.b.get_chroot(), CHROOT_DIR )


class SoftChrootTraversal(TestCase):
    """`chroot2abs` must not let a caller out of the chroot.

    Reachable only since the FileBrowser `map`/`len` repair: before it, every
    chroot-enabled call to `FileBrowser.view()` died with `TypeError: object of
    type 'map' has no len()`, so the endpoint was inert and this path could not
    be driven at all. Un-breaking it made a pre-existing weakness live, which
    is the reason it is fixed in the same change rather than filed.

    `chroot2abs` concatenated strings with no normalisation and `is_subdir` is
    a bare `startswith`, so `..` segments survived. Measured before the fix: a
    path of `/../&lt;empty dir outside the chroot&gt;` returned HTTP 200 with
    `empty: True` -- a directory-existence oracle for arbitrary paths -- and a
    non-empty one raised a ValueError carrying the operator's real filesystem
    path, which `api.py` then wrote into the log with a full traceback.
    `PrivacyFilter` redacts api keys and query parameters, not paths.
    """

    def setUp(self):
        self.b = SoftChroot()
        self.b.initialize(CHROOT_DIR)

    def test_dotdot_escaping_the_chroot_is_refused(self):
        for path in ('/..', '/../', '/../etc', '/subdir/../../etc', '/../../'):
            with self.assertRaises(ValueError, msg='%r escaped the chroot' % path):
                self.b.chroot2abs(path)

    def test_the_refusal_does_not_disclose_the_resolved_path(self):
        """The message goes into a logged traceback, so it must not carry the
        path it just refused: that would turn the fix into the disclosure."""
        try:
            self.b.chroot2abs('/../secret_library')
        except ValueError as exc:
            assert CHROOT_DIR.rstrip('/') not in str(exc), str(exc)
            assert 'secret_library' not in str(exc), str(exc)
        else:
            raise AssertionError('expected ValueError')

    def test_dotdot_that_stays_inside_the_chroot_is_allowed(self):
        """Refuse escapes, not every `..`. A path that normalises back inside
        is legitimate, and clamping it would silently rewrite the request."""
        self.assertEqual(self.b.chroot2abs('/a/../b'), CHROOT_DIR + 'b')

    def test_the_chroot_root_itself_is_still_reachable(self):
        self.assertEqual(self.b.chroot2abs('/'), CHROOT_DIR.rstrip(os.path.sep))


class SoftChrootUnnormalisedSetting(TestCase):
    """An unnormalised `soft_chroot` setting must still work.

    `initialize` only stripped trailing separators, so `self.chdir` kept any
    interior `//`, `/.` or `/..`. Once `chroot2abs` started normalising its
    result, it compared a NORMALISED path against an UNNORMALISED prefix and
    never matched -- so a chroot of `/srv//media` initialised cleanly
    (`os.path.isdir` accepts it) and then refused every path including its own
    root. The file browser returned an error on every call and settings saves
    silently failed, with a log line claiming the path resolved outside the
    chroot, which was not true.

    A regression introduced by the traversal fix, found at review. It failed
    closed, so it was never a hole; it was a total functional break of the
    chroot feature with a misleading diagnosis. Pinned here because
    `os.path.isdir` will keep accepting these spellings.
    """

    def _chroot(self, tmp, spelling):
        sc = SoftChroot()
        sc.initialize(spelling)
        return sc

    def test_every_spelling_of_the_same_directory_behaves_identically(self):
        import shutil
        import tempfile

        tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        if True:
            jail = os.path.join(tmp, 'jail')
            os.mkdir(jail)
            os.mkdir(os.path.join(jail, 'movies'))

            spellings = [
                jail,
                jail + os.path.sep,
                jail + os.path.sep + os.path.sep,
                jail + '/./',
                os.path.join(tmp, '.', 'jail'),
                os.path.join(tmp, 'jail', '..', 'jail'),
            ]
            for spelling in spellings:
                assert os.path.isdir(spelling), spelling
                sc = self._chroot(tmp, spelling)

                resolved = sc.chroot2abs('/movies')
                self.assertEqual(
                    resolved, os.path.join(jail, 'movies'),
                    'chroot2abs refused a legitimate path for chroot spelling %r' % spelling,
                )
                self.assertEqual(sc.chroot2abs('/'), jail, spelling)
                self.assertTrue(sc.is_root_abs(jail), spelling)
                self.assertEqual(sc.abs2chroot(os.path.join(jail, 'movies')), '/movies', spelling)

    def test_an_escape_is_still_refused_for_every_spelling(self):
        """The other direction: normalising the chroot must not reopen the
        traversal the normalisation was added to close."""
        import shutil
        import tempfile

        tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        jail = os.path.join(tmp, 'jail')
        os.mkdir(jail)

        for spelling in (jail, jail + '//', jail + '/./', os.path.join(tmp, '.', 'jail')):
            sc = self._chroot(tmp, spelling)
            with self.assertRaises(ValueError, msg='escape allowed for %r' % spelling):
                sc.chroot2abs('/../outside')
