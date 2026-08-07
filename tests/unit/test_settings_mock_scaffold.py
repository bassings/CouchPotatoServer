from unittest import mock
from unittest.mock import patch, Mock, MagicMock
import unittest
from unittest import TestCase

from couchpotato.core.settings import Settings


class DoNotUseMe:
    """ Do not use this class, it is just for storing Mock ' s of Settings-class

    Usage:
        Select appropriate Mocks and copy-paste them to your test-method
    """

    def __do_not_call(self):
        # s = Settings
        s = Mock()

        # methods:
        s.isOptionWritable = Mock(return_value=True)
        s.set = Mock(return_value=None)
        s.save = Mock()

        # props:
        s.log = Mock()

        # subobjects
        s.p = Mock()
        s.p.getboolean = Mock(return_value=True)
        s.p.has_option = Mock


class SettingsCommon(TestCase):

    def setUp(self):
        self.s = Settings()

    def test_get_directories(self):
        s = self.s
        raw = '    /some/directory   ::/another/dir     '
        exp = ['/some/directory', '/another/dir']

        sec = 'sec'
        opt = 'opt'
        s.types[sec] = {}
        s.types[sec][opt] = 'directories'

        s.p = MagicMock()
        s.p.get.return_value = raw

        act = s.get(option = opt, section = sec)

        self.assertEqual(act, exp)

class SettingsSaveWritableNonWritable(TestCase):

    def setUp(self):
        self.s = Settings()

    def test_save_writable(self):
        s = self.s

        # set up Settings-mocks :
        # lets assume, that option is writable:
        mock_isOptionWritable = s.isOptionWritable = Mock(return_value=True)
        mock_set = s.set = Mock(return_value=None)
        mock_p_save = s.save = Mock()

        section = 'core'
        option = 'option_non_exist_be_sure'
        value = "1000"
        params = {'section': section, 'name': option, 'value': value}

        # call method:
        env_mock = Mock()

        # HERE is an example of mocking LOCAL 'import'
        with patch.dict('sys.modules', {'couchpotato.environment.Env': env_mock}):
            result = s.saveView(**params)

        self.assertIsInstance(s, Settings)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['success'])

        # -----------------------------------------
        # check mock
        # -----------------------------------------
        mock_isOptionWritable.assert_called_with(section, option)

        # check, that Settings tried to save my value:
        mock_set.assert_called_with(section, option, value)

    def test_save_non_writable(self):
        s = self.s

        # set up Settings-mocks :
        # lets assume, that option is not writable:
        mock_is_w = s.isOptionWritable = Mock(return_value=False)
        mock_set = s.set = Mock(return_value=None)
        mock_p_save = s.save = Mock()
        mock_log_s = s.log = Mock()

        section = 'core'
        option = 'option_non_exist_be_sure'
        value = "1000"
        params = {'section': section, 'name': option, 'value': value}

        # call method:
        env_mock = Mock()

        # HERE is an example of mocking LOCAL 'import'
        with patch.dict('sys.modules', {'couchpotato.environment.Env': env_mock}):
            result = s.saveView(**params)

        self.assertIsInstance(s, Settings)
        self.assertIsInstance(result, dict)
        self.assertFalse(result['success'])

        # -----------------------------------------
        # check mock
        # -----------------------------------------
        # lets check, that 'set'-method was not called:
        self.assertFalse(mock_set.called, 'Method `set` was called')
        mock_is_w.assert_called_with(section, option)


class OptionMetaSuite(TestCase):
    """ tests for ro rw hidden options """

    def setUp(self):
        self.s = Settings()
        self.meta = self.s.optionMetaSuffix()

        # hide real config-parser:
        self.s.p = Mock()

    def test_no_meta_option(self):
        s = self.s

        section = 'core'
        option = 'url'

        option_meta = option + self.meta
        # setup mock
        s.p.getboolean = Mock(return_value=True)

        # there is no META-record for our option:
        s.p.has_option = Mock(side_effect=lambda s, o: not (s == section and o == option_meta))

        # by default all options are writable and readable
        self.assertTrue(s.isOptionWritable(section, option))
        self.assertTrue(s.isOptionReadable(section, option))

    def test_non_writable(self):
        s = self.s

        section = 'core'
        option = 'url'

        def mock_get_meta_ro(s, o):
            if (s == section and o == option_meta):
                return 'ro'
            return 11

        option_meta = option + self.meta
        # setup mock
        s.p.has_option = Mock(return_value=True)
        s.p.get = Mock(side_effect=mock_get_meta_ro)

        # by default all options are writable and readable
        self.assertFalse(s.isOptionWritable(section, option))
        self.assertTrue(s.isOptionReadable(section, option))


class SettingsChrootRefusal(TestCase):
    """A directory setting that escapes the soft chroot is refused, not saved.

    Before `chroot2abs` normalised, a chrooted user could save a directory of
    `../../mnt` and have it written verbatim: the chroot confined the file
    BROWSER while the settings API walked straight out of it, after which the
    renamer and the scanner operated outside the chroot entirely. Normalising
    closed that, and this pins the handling, because an unhandled ValueError
    here would be a 500 whose traceback carries the operator's real path into
    the log (PrivacyFilter redacts api keys and query parameters, not paths).
    """

    def _settings(self, option_type):
        s = Settings()
        s.isOptionWritable = Mock(return_value=True)
        s.getType = Mock(return_value=option_type)
        s.set = Mock(return_value=None)
        s.save = Mock()
        s.log = Mock()
        return s

    def _chroot(self, tmp):
        from couchpotato.core.softchroot import SoftChroot

        sc = SoftChroot()
        sc.initialize(tmp)
        return sc

    def test_an_escaping_directory_is_refused_and_never_written(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            s = self._settings('directory')
            with patch('couchpotato.environment.Env') as env:
                env.get.return_value = self._chroot(tmp)
                result = s.saveView(section='core', name='data_dir', value='/../../etc')

        self.assertFalse(result['success'])
        # The load-bearing half: refusing must also mean not persisting.
        s.set.assert_not_called()
        s.save.assert_not_called()

    def test_a_directory_inside_the_chroot_is_still_saved(self):
        """Both directions. A guard that refused everything would pass the
        test above while breaking every legitimate settings save."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            s = self._settings('directory')
            with patch('couchpotato.environment.Env') as env:
                env.get.return_value = self._chroot(tmp)
                result = s.saveView(section='core', name='data_dir', value='/movies')

        self.assertTrue(result['success'])
        s.set.assert_called_with('core', 'data_dir', os.path.join(tmp, 'movies'))
