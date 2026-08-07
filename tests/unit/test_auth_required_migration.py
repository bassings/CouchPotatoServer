"""The startup `auth_required` migration, EXECUTED. M2.

Carried since PR 2's review. Until now its only guard was the source-order
string search in `test_auth_required_gate.py`, which pins where the block sits
relative to `loader.run()` and can say nothing at all about what it does. That
matters more than it sounds: this block decides, once, whether an install that
has been password-protected for years comes back up protected or public.

The block is now a named module-level function, so it can be driven directly:

  * AC-ARCH-10 -- importable from `couchpotato.runner`, callable against a
    settings double, no server;
  * AC-DATA-11 -- two boots agree, an explicit 0 or 1 is never overwritten, and
    every other option in `config.ini` survives byte for byte;
  * AC-OPS-50 -- idempotent, one INFO on the first call only, and a failed
    write-back leaves the setting ABSENT so the next boot re-derives, with one
    ERROR rather than a process carrying on as though it had migrated;
  * AC-DATA-12 -- a failed write leaves `config.ini` byte-identical, non-empty,
    and still holding the api_key and the password. A neither-copy state is the
    one outcome that cannot be recovered from, and `config.ini` is also the
    documented lockout remedy: losing it destroys the remedy along with the
    configuration.

The source-order guard STAYS. An executed test cannot pin the call's position
relative to `loader.run()`, and the position is what stops `registerDefaults`
writing `auth_required = 0` before the "is it absent?" check ever runs.
"""
import configparser
import logging
import os
import sys
from pathlib import Path

import pytest

from couchpotato.core.settings import Settings
from couchpotato.environment import Env
from couchpotato.runner import resolve_auth_required_setting

sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_helper import env_restored  # noqa: E402

#: A realistic api_key: 32 characters, so a "did it survive" check cannot pass
#: by finding a short string inside unrelated text. Not hex, so `gitleaks`
#: cannot mistake the fixture for a real key.
API_KEY = 'notarealapikey' + '0' * 18
STORED_PASSWORD = 'not-a-real-bcrypt-hash-either-0000'

#: Written verbatim into `config.ini`. The unknown section and the unknown
#: option are the point of AC-DATA-11's third clause: a migration that rewrites
#: the file must not quietly drop what it does not recognise, and this file is
#: shared with plugins that register their own sections at runtime.
CONFIG = """[core]
api_key = %s
password = %s
username = admin
url_base =
launch_browser = 1

[newznab]
api_key = a-different-key-entirely
enabled = 1

[some_plugin_nobody_registered]
whatever = kept
""" % (API_KEY, STORED_PASSWORD)


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / 'config.ini'
    path.write_text(CONFIG, encoding='utf-8')
    return path


@pytest.fixture
def settings(config_file):
    """A REAL `Settings` over a real file, inside a restored `Env`."""
    with env_restored():
        instance = Settings()
        instance.setFile(str(config_file))
        Env.set('settings', instance)
        yield instance


def read(path) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser()
    parser.read(str(path), encoding='utf-8')
    return parser


def stored_auth_required(path):
    parser = read(path)
    if not parser.has_option('core', 'auth_required'):
        return None
    return parser.get('core', 'auth_required')


class FakeSettings:
    """The settings double of AC-ARCH-10. No file, no server, no database."""

    def __init__(self, data=None, save_error=None):
        self.data = dict(data or {})
        self.save_error = save_error
        self.saves = 0
        self.p = configparser.RawConfigParser()
        self.p.add_section('core')
        for option, value in self.data.items():
            self.p.set('core', option, str(value))

    def get(self, attr, default=None, section='core', type=None):
        return self.data.get(attr, default)

    def set(self, section, option, value):
        self.data[option] = value
        self.p.set(section, option, str(value))

    def addSection(self, section):
        if not self.p.has_section(section):
            self.p.add_section(section)

    def save(self):
        self.saves += 1
        if self.save_error is not None:
            raise self.save_error


class TestItIsCallableWithoutAServer:
    """AC-ARCH-10."""

    def test_it_is_a_module_level_function_on_couchpotato_runner(self):
        import couchpotato.runner as runner

        assert callable(getattr(runner, 'resolve_auth_required_setting', None))

    @pytest.mark.parametrize('password,expected', [
        (STORED_PASSWORD, 1),
        ('', 0),
    ])
    def test_it_derives_from_the_stored_password(self, password, expected):
        double = FakeSettings({'password': password})

        with env_restored():
            Env.set('settings', double)
            assert resolve_auth_required_setting() == expected

        assert double.data['auth_required'] == expected

    def test_an_install_with_a_password_comes_back_protected(self):
        """The whole reason the block exists.

        Deriving from `bool(password)` is what stops an install that has been
        password-protected for years coming up public after an upgrade, because
        `config.ini` predates the setting.
        """
        double = FakeSettings({'password': STORED_PASSWORD})

        with env_restored():
            Env.set('settings', double)
            resolve_auth_required_setting()

            # Both halves. `auth_is_required()` alone passes against a
            # migration that did NOTHING, because its absent-value fallback
            # derives from the password too -- so the assertion that matters is
            # that the answer is now written down and greppable, which is the
            # documented lockout recovery path.
            assert double.data.get('auth_required') == 1, double.data
            from couchpotato import auth_is_required
            assert auth_is_required() is True


class TestAnExplicitValueIsNeverOverwritten:
    """AC-DATA-11's second clause."""

    @pytest.mark.parametrize('stored', ['0', '1'])
    def test_the_stored_value_survives(self, settings, config_file, stored):
        settings.addSection('core')
        settings.p.set('core', 'auth_required', stored)
        settings.save()

        assert resolve_auth_required_setting() is None, (
            'the migration acted on an install that had already made this '
            'decision explicitly'
        )
        assert stored_auth_required(config_file) == stored

    def test_an_explicit_zero_survives_even_with_a_password_set(self, settings, config_file):
        """The dangerous direction. An operator who deliberately turned
        authentication off, on a box with a password still stored, must not
        have it turned back on by a boot."""
        settings.p.set('core', 'auth_required', '0')
        settings.save()

        resolve_auth_required_setting()

        assert stored_auth_required(config_file) == '0'
        assert read(config_file).get('core', 'password') == STORED_PASSWORD


class TestBootingTwiceIsIdempotent:
    """AC-DATA-11's first clause and AC-OPS-50."""

    def test_the_second_boot_leaves_the_same_value(self, settings, config_file):
        first = resolve_auth_required_setting()
        after_first = stored_auth_required(config_file)

        second = resolve_auth_required_setting()

        assert first == 1, first
        assert second is None, 'the second boot migrated again'
        assert stored_auth_required(config_file) == after_first == '1'

    def test_the_info_record_is_emitted_only_on_the_first_call(self, settings, caplog):
        with caplog.at_level(logging.INFO):
            resolve_auth_required_setting()
            first = [r for r in caplog.records
                     if r.levelno >= logging.INFO and 'auth_required' in r.getMessage()]
            caplog.clear()
            resolve_auth_required_setting()
            second = [r for r in caplog.records
                      if r.levelno >= logging.INFO and 'auth_required' in r.getMessage()]

        assert len(first) == 1, [r.getMessage() for r in first]
        assert second == [], [r.getMessage() for r in second]

    def test_the_file_is_byte_identical_across_the_second_boot(self, settings, config_file):
        resolve_auth_required_setting()
        after_first = config_file.read_bytes()

        resolve_auth_required_setting()

        assert config_file.read_bytes() == after_first


class TestEverythingElseInTheFileSurvives:
    """AC-DATA-11's third clause.

    `Settings.save()` rewrites the WHOLE file through ConfigParser, so this is
    not a formality: anything the parser did not read is gone, permanently, and
    the file holds the api_key, the UI password and every downloader credential.
    """

    def test_every_option_is_still_present_and_unchanged(self, settings, config_file):
        before = read(config_file)

        resolve_auth_required_setting()

        after = read(config_file)
        for section in before.sections():
            assert after.has_section(section), section
            for option, value in before.items(section):
                assert after.get(section, option) == value, (section, option)

    def test_the_api_key_and_the_password_are_intact(self, settings, config_file):
        resolve_auth_required_setting()

        after = read(config_file)
        assert after.get('core', 'api_key') == API_KEY
        assert after.get('core', 'password') == STORED_PASSWORD

    def test_an_unknown_section_is_not_dropped(self, settings, config_file):
        resolve_auth_required_setting()

        after = read(config_file)
        assert after.get('some_plugin_nobody_registered', 'whatever') == 'kept'

    def test_the_only_difference_is_the_new_option(self, settings, config_file):
        before = read(config_file)

        resolve_auth_required_setting()

        after = read(config_file)
        added = {
            (section, option)
            for section in after.sections()
            for option, _ in after.items(section)
            if not before.has_option(section, option)
        }
        assert added == {('core', 'auth_required')}, added


class TestAFailedWriteBackLeavesTheSettingAbsent:
    """AC-OPS-50's second half and AC-DATA-12.

    Absent, not half-written: the next boot re-derives and gets the same answer,
    whereas a value that reached memory but not disk means this process is
    enforcing something `config.ini` does not say -- and `config.ini` is where
    the locked-out operator looks.
    """

    @pytest.fixture
    def failing(self, settings, monkeypatch):
        def explode(self):
            raise OSError('read-only file system')

        monkeypatch.setattr(Settings, 'save', explode)
        return settings

    def test_it_returns_without_claiming_success(self, failing):
        assert resolve_auth_required_setting() is None

    def test_the_setting_is_absent_afterwards(self, failing, config_file):
        resolve_auth_required_setting()

        assert stored_auth_required(config_file) is None, 'it reached the file'
        assert failing.get('auth_required', default=None) in (None, ''), (
            'the value is still in memory, so this process enforces something '
            'config.ini does not say and the operator cannot grep for it'
        )

    def test_one_error_names_the_failure(self, failing, caplog):
        with caplog.at_level(logging.ERROR):
            resolve_auth_required_setting()

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1, [r.getMessage() for r in errors]
        assert 'auth_required' in errors[0].getMessage()

    def test_the_next_boot_re_derives(self, settings, config_file, monkeypatch):
        def explode(self):
            raise OSError('read-only file system')

        monkeypatch.setattr(Settings, 'save', explode)
        resolve_auth_required_setting()
        monkeypatch.undo()

        assert resolve_auth_required_setting() == 1
        assert stored_auth_required(config_file) == '1'

    def test_config_ini_is_byte_identical(self, failing, config_file):
        before = config_file.read_bytes()

        resolve_auth_required_setting()

        after = config_file.read_bytes()
        assert after == before
        assert after, 'config.ini is EMPTY -- the api_key and password are gone'
        assert API_KEY in after.decode('utf-8')
        assert STORED_PASSWORD in after.decode('utf-8')


class TestAReadOnlyDirectoryIsTheSameStory:
    """AC-DATA-12 driven by the real failure rather than a patched `save`.

    `Settings.save()` writes a sibling temp file and renames it, so a read-only
    DIRECTORY is what actually breaks it -- and the two must not disagree,
    because the patched-save test would happily pass against an implementation
    that truncates the real file first.
    """

    @pytest.fixture
    def locked(self, tmp_path):
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            pytest.skip('running as root: file modes are not enforced')

        directory = tmp_path / 'config'
        directory.mkdir()
        path = directory / 'config.ini'
        path.write_text(CONFIG, encoding='utf-8')

        with env_restored():
            instance = Settings()
            instance.setFile(str(path))
            Env.set('settings', instance)
            os.chmod(directory, 0o500)
            try:
                yield path
            finally:
                os.chmod(directory, 0o700)

    def test_the_file_survives_byte_for_byte(self, locked):
        before = locked.read_bytes()

        resolve_auth_required_setting()

        after = locked.read_bytes()
        assert after == before
        assert after
        assert API_KEY in after.decode('utf-8')
        assert STORED_PASSWORD in after.decode('utf-8')

    def test_no_stray_temp_file_is_left_behind(self, locked):
        """A neither-copy state includes half a copy sitting beside the real
        one, which the next reader may pick up."""
        resolve_auth_required_setting()

        assert [p.name for p in locked.parent.iterdir()] == ['config.ini']

    def test_the_premise_holds_the_directory_really_is_unwritable(self, locked):
        """Anti-vacuity. If the mode were not enforced, every assertion above
        would pass against a successful write."""
        with pytest.raises(OSError):
            (locked.parent / 'canary').write_text('x')
