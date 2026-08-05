"""Tests for the settings file browser.

Relocated from `couchpotato/core/plugins/browser_test.py`, where it sat
tracked but outside `pytest.ini`'s `testpaths` and outside its
`python_files = test_*.py` convention, so no runner had executed it since the
Python 3 port. It was sitting on a live defect the whole time: see
`test_view_returns_chroot_relative_directories_as_a_list`.
"""
#import sys
import os

from unittest import mock
import unittest
from unittest import TestCase


from couchpotato.core.plugins.browser import FileBrowser
from couchpotato.core.softchroot import SoftChroot


CHROOT_DIR = '/tmp/'


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

    def tuneMock(self, env):
        #set up mock:
        sc = SoftChroot()
        sc.initialize(CHROOT_DIR)
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

        for path, parent in [('/asdf','/'), (CHROOT_DIR, '/'), ('/mnk/123/t', '/mnk/123/')]:
            r = self.b.view(path)
            path_strip = path
            if (path.endswith(os.path.sep)):
                path_strip = path_strip.rstrip(os.path.sep)

            self.assertEqual(r['home'], '/')
            self.assertEqual(r['parent'], parent)
            self.assertFalse(r['is_root'])
