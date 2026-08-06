"""Tests for the settings file browser.

Relocated from `couchpotato/core/plugins/browser_test.py`, where it sat
tracked but outside `pytest.ini`'s `testpaths` and outside its
`python_files = test_*.py` convention, so no runner had executed it since the
Python 3 port. It was sitting on a live defect the whole time: see
`test_view_returns_chroot_relative_directories_as_a_list`.
"""
#import sys
import os
import shutil
import tempfile

from unittest import mock
import unittest
from unittest import TestCase

import pytest


from couchpotato.core.plugins.browser import FileBrowser
from couchpotato.core.softchroot import SoftChroot


# A per-test temporary directory, NOT the host's real /tmp. This file
# inherited `CHROOT_DIR = '/tmp/'` from the un-run copy under couchpotato/,
# and `view(CHROOT_DIR)` reaches FileBrowser.getDirectories, which does a real
# os.listdir on it: a unit test whose duration and contents depend on whatever
# the developer's machine has in /tmp. The assertions here are all about
# chroot-relative paths, so nothing needs the real one.


def test_view_returns_chroot_relative_directories_as_a_list(tmp_path):
    """The chrooted listing is a real list, not a lazy `map`.

    Python 2's `map()` returned a list; Python 3's returns an iterator, so
    `view()` raised `TypeError: object of type 'map' has no len()` for every
    operator who had configured a soft chroot. The file browser is how you
    choose a media directory in settings, so for those installs it was a
    plain 500 with a traceback in the log and no working way to set a path.

    The two TestCase methods below tripped over that too, but only as a side
    effect of `len()`. This pins the contract directly: a change that dodged
    `len()` while still handing an iterator to the response serialiser would
    pass those and fail this one.
    """
    # realpath: on macOS the temp root is reached through a symlink, and
    # SoftChroot compares paths with a plain `startswith` against the
    # resolved directory the browser walks.
    chroot = os.path.realpath(str(tmp_path))
    os.mkdir(os.path.join(chroot, 'movies'))
    os.mkdir(os.path.join(chroot, 'tv'))

    soft_chroot = SoftChroot()
    soft_chroot.initialize(chroot)

    with mock.patch('couchpotato.core.plugins.browser.Env') as env:
        env.get.return_value = soft_chroot
        result = FileBrowser().view('/')

    assert isinstance(result['dirs'], list), 'dirs must be serialisable, not a lazy iterator'
    assert result['dirs'] == ['/movies/', '/tv/']
    assert result['empty'] is False

# 'couchpotato.core.plugins.browser.Env', 
@mock.patch('couchpotato.core.plugins.browser.Env', name='EnvMock')
class FileBrowserChrootedTest(TestCase):

    def setUp(self):
        self.b = FileBrowser()
        self._tmp = tempfile.mkdtemp()
        # realpath: on macOS the temp root is reached through a symlink, and
        # SoftChroot compares resolved paths with a plain startswith.
        self.chroot_dir = os.path.realpath(self._tmp) + os.path.sep

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def tuneMock(self, env):
        #set up mock:
        sc = SoftChroot()
        sc.initialize(self.chroot_dir)
        env.get.return_value = sc


    def test_view__chrooted_path_none(self, env):
        #def view(self, path = '/', show_hidden = True, **kwargs):

        self.tuneMock(env)

        r = self.b.view(None)
        self.assertEqual(r['home'], '/')
        self.assertEqual(r['parent'], '/')
        self.assertTrue(r['is_root'])

    def test_view__chrooted_path_chroot(self, env):
        #def view(self, path = '/', show_hidden = True, **kwargs):

        self.tuneMock(env)

        # Chroot-RELATIVE paths only. The third case used to be CHROOT_DIR
        # itself, which only produced parent '/' because '/tmp' happens to be
        # a single path component: chroot2abs prepends the chroot, so
        # '/tmp' + '/tmp/' nested exactly one level. Against any real
        # temporary directory that expectation is simply wrong, and the case
        # added nothing -- the chroot root is '/' here, which
        # test_view__chrooted_path_none already covers.
        for path, parent in [('/asdf', '/'), ('/mnk/123/t', '/mnk/123/')]:
            r = self.b.view(path)
            path_strip = path
            if (path.endswith(os.path.sep)):
                path_strip = path_strip.rstrip(os.path.sep)

            self.assertEqual(r['home'], '/')
            self.assertEqual(r['parent'], parent)
            self.assertFalse(r['is_root'])


def test_view_refuses_to_list_outside_the_chroot(tmp_path):
    """The traversal is refused at the endpoint, not just in the helper.

    There was no traversal test here at all, and until the `map`/`len` repair
    above there could not usefully be one: every chroot-enabled call raised
    TypeError before reaching any path handling. Measured on this branch
    before the SoftChroot fix, `view('/../outside')` returned a normal
    `{'dirs': [], 'empty': True}` for an empty directory outside the chroot
    and a ValueError naming the real path for a non-empty one -- an existence
    oracle and a path disclosure from one endpoint.

    Both fixtures are created because the two cases took different branches:
    a test with only the empty one would have missed the disclosure, and one
    with only the non-empty one would have missed the oracle.
    """
    chroot = os.path.realpath(str(tmp_path / 'jail'))
    os.mkdir(chroot)
    os.mkdir(os.path.join(chroot, 'movies'))
    outside_empty = os.path.join(os.path.realpath(str(tmp_path)), 'outside_empty')
    outside_full = os.path.join(os.path.realpath(str(tmp_path)), 'outside_full')
    os.mkdir(outside_empty)
    os.mkdir(outside_full)
    os.mkdir(os.path.join(outside_full, 'Real Name Films'))

    soft_chroot = SoftChroot()
    soft_chroot.initialize(chroot)

    with mock.patch('couchpotato.core.plugins.browser.Env') as env:
        env.get.return_value = soft_chroot

        # Sanity: the legitimate call still works, so a blanket refusal
        # cannot be mistaken for a passing traversal guard.
        assert FileBrowser().view('/')['dirs'] == ['/movies/']

        for escape in ('/../outside_empty', '/../outside_full', '/../..'):
            with pytest.raises(ValueError) as excinfo:
                FileBrowser().view(escape)
            assert 'Real Name Films' not in str(excinfo.value)
            assert chroot not in str(excinfo.value)
