"""``settings.save`` handles an option under its registered name, whatever case is sent.

The config parser folds option names to lower case, so ``core.PASSWORD`` wrote
the real ``password`` option while every step keyed on the name (the hashing
hook, the ``auth_required`` coupling, the displayed-mask refusal, the soft
chroot, the ``.after`` and ``.committed`` events and the password lock) is
case-sensitive and was skipped. These tests drive the real endpoint with
``core`` and the renamer registered from their live declarations and the real
core hooks wired, and read ``config.ini`` as bytes.
"""
import configparser
import os

import pytest

from couchpotato.core._base._core import Core
from couchpotato.core._base import _core
from couchpotato.core.event import addEvent
from couchpotato.core.helpers.variable import check_password, md5
from couchpotato.core.plugins.renamer import api as renamer_api
from couchpotato.core.softchroot import SoftChroot
from couchpotato.environment import Env
from tests.helpers.combine_groups import held_by_another_thread, sha
from tests.integration.test_settings_group_save_route import live_world, url

pytestmark = pytest.mark.integration

ROUTE = 'settings.save'
NEW_PASSWORD = 'placeholder-new-password-one'
OTHER_PASSWORD = 'placeholder-new-password-two'
SPELLINGS = ('PASSWORD', 'Password', 'pAsSwOrD')
UPPER_FROM = ('FROM', 'From', 'fRoM')
HARMLESS = 'use_tab_threed'
HARMLESS_SPELLINGS = ('USE_TAB_THREED', 'Use_Tab_Threed')
TRANSPORTS = ('form', 'json', 'query')
MASK_REFUSAL = {'success': False, 'error': 'That is the masked placeholder, not the real value. '
                                          'Clear the field and paste the credential to change it.'}


@pytest.fixture
def world(tmp_path, monkeypatch):
    with live_world(tmp_path, monkeypatch) as live:
        settings, client = live
        for config in (_core.config, renamer_api.config):
            for entry in config:
                settings.addOptions(entry['name'], entry)
                options = {option['name']: option
                           for group in entry['groups'] for option in group['options']}
                settings.registerDefaults(entry['name'], options)
        # The real hooks (hash, auth_required guard, rotation marker), registered
        # exactly as `Core.__init__` does. Only the far end of the rotation, the
        # session-secret write that needs a database, is replaced by a counter.
        Core()
        rotations = []
        monkeypatch.setattr('couchpotato.rotate_session_secret',
                            lambda *args, **kwargs: rotations.append(1) or 'secret')
        settings.rotations = rotations
        yield settings, client


def send(client, section, name, value, transport='form'):
    fields = {'section': section, 'name': name, 'value': value}
    if transport == 'json':
        return client.post(url(route=ROUTE), json=fields)
    if transport == 'query':
        return client.get(url(route=ROUTE), params=fields)
    return client.post(url(route=ROUTE), data=fields)


def stored_on_disk(settings, section, option):
    parser = configparser.RawConfigParser()
    parser.read(settings.file, encoding='utf-8')
    return parser.get(section, option, fallback=None)


def file_text(settings):
    with open(settings.file, encoding='utf-8') as handle:
        return handle.read()


def spy(names):
    fired = []
    for name in names:
        addEvent(name, lambda *args, _name=name, **kwargs: fired.append(_name))
    return fired


def lifecycle(section, option):
    return ['setting.save.%s.%s%s' % (section, option, suffix)
            for suffix in ('', '.after', '.committed')]


@pytest.mark.parametrize('spelling', SPELLINGS)
@pytest.mark.parametrize('transport', TRANSPORTS)
class TestThePasswordIsHashedWhateverTheCase:

    def test_the_stored_value_is_a_bcrypt_hash_in_memory_and_on_disk(self, world, spelling, transport):
        settings, client = world

        response = send(client, 'core', spelling, NEW_PASSWORD, transport)

        assert response.json()['success'] is True
        for held in (settings.p.get('core', 'password'), stored_on_disk(settings, 'core', 'password')):
            assert held.startswith('$2') and len(held) == 60
            assert check_password(md5(NEW_PASSWORD), held)
        assert NEW_PASSWORD not in file_text(settings)

    def test_the_response_does_not_echo_the_hash_or_the_text(self, world, spelling, transport):
        settings, client = world

        response = send(client, 'core', spelling, NEW_PASSWORD, transport)

        assert NEW_PASSWORD not in response.text
        assert '$2' not in response.text

    def test_login_is_required_and_the_session_is_revoked_as_for_lower_case(
            self, world, spelling, transport):
        settings, client = world

        send(client, 'core', spelling, NEW_PASSWORD, transport)

        assert str(settings.p.get('core', 'auth_required')) == '1'
        assert stored_on_disk(settings, 'core', 'auth_required') == '1'
        assert settings.rotations == [1]
        assert stored_on_disk(settings, 'core', 'session_rotation_pending') == '0'


@pytest.mark.parametrize('spelling', ('AUTH_REQUIRED', 'Auth_Required'))
class TestAuthRequiredWithNoPassword:

    def test_it_is_rewritten_to_zero_exactly_as_lower_case_is(self, world, spelling):
        settings, client = world
        assert settings.p.get('core', 'password') == ''

        response = send(client, 'core', spelling, '1')

        assert response.json()['success'] is True
        assert str(settings.p.get('core', 'auth_required')) == '0'
        assert stored_on_disk(settings, 'core', 'auth_required') == '0'

    def test_the_response_matches_the_lower_case_response(self, world, spelling):
        settings, client = world
        lower = send(client, 'core', 'auth_required', '1').json()

        upper = send(client, 'core', spelling, '1').json()

        assert upper == lower
        assert lower.get('changed') is True


@pytest.mark.parametrize('spelling', SPELLINGS)
class TestTheDisplayedMaskIsRefused:

    def mask_of_stored(self, settings):
        return '*' * len(settings.p.get('core', 'password'))

    def test_it_is_refused_as_lower_case_is_and_nothing_changes(self, world, spelling):
        settings, client = world
        send(client, 'core', 'password', NEW_PASSWORD)
        before_hash = settings.p.get('core', 'password')
        before_bytes = sha(settings.file)
        mask = self.mask_of_stored(settings)
        assert len(mask) == 60
        lower = send(client, 'core', 'password', mask).json()
        assert lower == MASK_REFUSAL

        upper = send(client, 'core', spelling, mask).json()

        assert upper == lower
        assert settings.p.get('core', 'password') == before_hash
        assert sha(settings.file) == before_bytes
        assert check_password(md5(NEW_PASSWORD), before_hash)

    def test_a_masked_jackett_key_is_refused_whatever_the_case(self, world, spelling):
        settings, client = world
        stored_key = 'placeholder-jackett-key'
        send(client, 'torrentpotato', 'jackett_api_key', stored_key)
        assert settings.p.get('torrentpotato', 'jackett_api_key') == stored_key
        before_bytes = sha(settings.file)
        mask = '*' * len(stored_key)
        lower = send(client, 'torrentpotato', 'jackett_api_key', mask).json()
        assert lower == MASK_REFUSAL

        upper = send(client, 'torrentpotato', 'JACKETT_API_KEY', mask).json()

        assert upper == lower
        assert settings.p.get('torrentpotato', 'jackett_api_key') == stored_key
        assert sha(settings.file) == before_bytes


@pytest.mark.parametrize('spelling', UPPER_FROM)
class TestTheSoftChrootStillConfinesADirectory:

    @pytest.fixture
    def chroot(self, tmp_path, monkeypatch):
        root = tmp_path / 'chroot'
        root.mkdir()
        soft = SoftChroot()
        soft.initialize(str(root))
        monkeypatch.setattr(Env, '_softchroot', soft, raising=False)
        return os.path.realpath(root)

    def test_an_escaping_path_is_refused_as_lower_case_is(self, world, chroot, spelling):
        settings, client = world
        before_bytes = sha(settings.file)
        before = settings.p.get('renamer', 'from')
        lower = send(client, 'renamer', 'from', '/../../../etc').json()
        assert lower == {'success': False}

        upper = send(client, 'renamer', spelling, '/../../../etc').json()

        assert upper == lower
        assert settings.p.get('renamer', 'from') == before
        assert sha(settings.file) == before_bytes
        assert '/etc' not in file_text(settings)

    def test_a_path_inside_the_chroot_is_stored_the_same_way_as_lower_case(self, world, chroot, spelling):
        settings, client = world
        send(client, 'renamer', 'from', '/downloads')
        lower = settings.p.get('renamer', 'from')
        assert lower == os.path.join(chroot, 'downloads')

        send(client, 'renamer', spelling, '/other')

        assert settings.p.get('renamer', 'from') == os.path.join(chroot, 'other')


class TestTheEventsCarryTheRegisteredSpelling:

    @pytest.mark.parametrize('spelling', HARMLESS_SPELLINGS)
    def test_the_upper_case_listeners_never_fire_and_the_lower_case_ones_do(self, world, spelling):
        settings, client = world
        canonical = spy(lifecycle('renamer', HARMLESS))
        callers = spy(lifecycle('renamer', spelling))
        send(client, 'renamer', HARMLESS, '0')
        baseline = list(canonical)
        del canonical[:]

        response = send(client, 'renamer', spelling, '1')

        assert response.json()['success'] is True
        assert callers == []
        assert canonical == baseline
        assert 'setting.save.renamer.%s.committed' % HARMLESS in canonical
        assert settings.p.get('renamer', HARMLESS) == '1'

    @pytest.mark.parametrize('spelling', HARMLESS_SPELLINGS)
    def test_the_after_listener_fires_for_an_upper_case_save_as_for_lower_case(self, world, spelling):
        settings, client = world
        after = spy(['setting.save.renamer.%s.after' % HARMLESS])
        send(client, 'renamer', HARMLESS, '0')
        per_save = len(after)
        assert per_save >= 1
        del after[:]

        send(client, 'renamer', spelling, '1')

        assert len(after) == per_save


class TestThePasswordLock:

    @pytest.mark.parametrize('name', ['password', 'PASSWORD', 'Auth_Required', 'auth_required'])
    def test_the_save_runs_while_the_password_lock_is_held(self, world, monkeypatch, name):
        from couchpotato.core import settings as settings_module
        settings, _client = world
        held = []
        names = []

        def record(**kwargs):
            held.append(held_by_another_thread(settings_module._PASSWORD_SAVE_LOCK))
            names.append(kwargs['name'])
            return {'success': True}

        monkeypatch.setattr(settings, '_saveView', record)

        settings.saveView(section='core', name=name, value='x')

        assert held == [True]
        assert names == [name.lower()]

    def test_another_section_does_not_take_the_lock(self, world, monkeypatch):
        from couchpotato.core import settings as settings_module
        settings, _client = world
        held = []
        monkeypatch.setattr(settings, '_saveView', lambda **kwargs: held.append(
            held_by_another_thread(settings_module._PASSWORD_SAVE_LOCK)) or {'success': True})

        settings.saveView(section='renamer', name='PASSWORD', value='x')

        assert held == [False]


class TestRefusalsAreUnchanged:

    def test_a_flag_name_in_any_case_is_still_refused_with_the_flag_text(self, world):
        settings, client = world
        before = sha(settings.file)

        body = send(client, 'core', 'API_KEY_INTERNAL_META', 'rw').json()

        assert body == {'success': False, 'error': 'An option flag cannot be changed through '
                                                   'settings.save. Nothing was saved.'}
        assert sha(settings.file) == before

    @pytest.mark.parametrize('name', ['PASSWORD ', ' password', '\tPASSWORD\n'])
    def test_a_name_with_surrounding_whitespace_is_refused_by_the_name_rule(self, world, name):
        settings, client = world
        before = sha(settings.file)

        body = send(client, 'core', name, NEW_PASSWORD).json()

        assert body['success'] is False
        assert 'error' in body
        assert sha(settings.file) == before
        assert NEW_PASSWORD not in file_text(settings)

    def test_a_combine_column_in_any_case_is_still_refused_per_column(self, world):
        settings, client = world
        before = sha(settings.file)

        body = send(client, 'newznab', 'HOST', 'https://placeholder.invalid').json()

        assert body['success'] is False
        assert 'error' in body
        assert sha(settings.file) == before


class TestASectionIsNotFolded:

    @pytest.mark.parametrize('section', ['CORE', 'Core'])
    def test_a_wrong_case_section_does_not_reach_the_real_option(self, world, section):
        settings, client = world
        before = sha(settings.file)
        original = settings.p.get('core', 'password')

        body = send(client, section, 'password', NEW_PASSWORD).json()

        assert body.get('success') is not True
        assert settings.p.get('core', 'password') == original
        assert sha(settings.file) == before
        assert NEW_PASSWORD not in file_text(settings)
        assert not settings.p.has_section(section)

