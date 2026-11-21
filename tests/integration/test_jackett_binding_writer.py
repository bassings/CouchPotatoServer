"""SEC-005 P1: a saved Jackett API key is stored with the address it was saved for.

Every test drives the real ``settings.save`` route over a real ``Settings`` and a
real ``TorrentPotato`` provider (the value hook that writes the binding is
registered by the provider's constructor), and reads ``config.ini`` back with a
fresh parser. Nothing reads the binding to refuse anything in this slice, so
what is asserted here is only what the writer stores. Expected strings are
literals written in the test or in ``tests/helpers/jackett_binding.py``, never
the normaliser's own output.

Hosts are ``.local`` or ``.invalid`` and every key is a ``placeholder-`` string.
"""
import configparser
import json

import pytest

from couchpotato.core.event import addEvent
from couchpotato.core.settings import _PASSWORD_SAVE_LOCK
from tests.helpers.combine_groups import LogCapture, held_by_another_thread, sha
from tests.helpers.jackett_binding import (
    BINDING_OPTION,
    KEY_OPTION,
    NORMALISER_TABLE,
    OTHER_KEY,
    PLACEHOLDER_KEY,
    SECTION,
    UNPARSEABLE,
    URL_OPTION,
    jackett_world,
    on_disk,
)
from tests.integration.test_settings_group_save_route import url

pytestmark = pytest.mark.integration

ROUTE = 'settings.save'
ADDRESS_A = 'http://jackett-a.local:9117'
ADDRESS_B = 'http://jackett-b.local:9117'
BOUND_A = 'http://jackett-a.local:9117'
BOUND_B = 'http://jackett-b.local:9117'


@pytest.fixture
def world(tmp_path, monkeypatch):
    with jackett_world(tmp_path, monkeypatch) as live:
        yield live


def save(client, name, value, section=SECTION):
    return client.post(url(route=ROUTE), data={'section': section, 'name': name, 'value': value})


def save_json(client, name, value):
    return client.post(url(route=ROUTE), json={'section': SECTION, 'name': name, 'value': value})


def memory(settings, option):
    return settings.p.get(SECTION, option) if settings.p.has_option(SECTION, option) else None


def bind_to_a(client, key=PLACEHOLDER_KEY):
    """The user's own steps: address first, then key."""
    assert save(client, URL_OPTION, ADDRESS_A).json()['success'] is True
    assert save(client, KEY_OPTION, key).json()['success'] is True


class TestAKeySaveWritesTheBinding:
    """AC-SEC-6 (writer clauses), AC-ARCH-7"""

    def test_the_key_and_the_binding_are_stored_together(self, world):
        settings, client, _ = world

        bind_to_a(client)

        assert on_disk(settings, KEY_OPTION) == PLACEHOLDER_KEY
        assert on_disk(settings, BINDING_OPTION) == BOUND_A
        assert memory(settings, BINDING_OPTION) == BOUND_A

    def test_the_key_save_is_one_file_replace(self, world, monkeypatch):
        settings, client, _ = world
        save(client, URL_OPTION, ADDRESS_A)
        import couchpotato.core.settings as settings_module
        real = settings_module.os.replace
        replaced = []
        monkeypatch.setattr(settings_module.os, 'replace',
                            lambda src, dst: replaced.append(dst) or real(src, dst))

        save(client, KEY_OPTION, PLACEHOLDER_KEY)

        assert len(replaced) == 1

    def test_the_address_is_read_inside_the_same_hold_of_the_settings_lock(self, world):
        """AC-DATA-1: no address save can fall between the read of the address and the file write."""
        settings, client, _ = world
        save(client, URL_OPTION, ADDRESS_A)
        held = []
        # Registered after the real hook, so it runs once the address has been read
        # and before the file is written.
        addEvent('setting.save.torrentpotato.jackett_api_key',
                 lambda value: held.append(held_by_another_thread(_PASSWORD_SAVE_LOCK)))

        save(client, KEY_OPTION, PLACEHOLDER_KEY)

        assert held == [True]
        assert on_disk(settings, BINDING_OPTION) == BOUND_A

    @pytest.mark.parametrize('spelling', ['JACKETT_API_KEY', 'Jackett_Api_Key'])
    def test_a_key_saved_under_another_spelling_is_bound_to_the_address_now_saved(self, world, spelling):
        """Reverting the second prerequisite (#615) makes these rows fail."""
        settings, client, _ = world
        bind_to_a(client)
        save(client, URL_OPTION, ADDRESS_B)
        assert on_disk(settings, BINDING_OPTION) == BOUND_A

        response = save(client, spelling, OTHER_KEY)

        assert response.json()['success'] is True
        assert on_disk(settings, KEY_OPTION) == OTHER_KEY
        assert on_disk(settings, BINDING_OPTION) == BOUND_B
        assert memory(settings, BINDING_OPTION) == BOUND_B

    @pytest.mark.parametrize('label,value,stored', [
        ('plain text', 'placeholder-plain-key', 'placeholder-plain-key'),
        ('a control character', 'placeholder-key\x01with-control', 'placeholder-key\x01with-control'),
        # A fresh parser trims the padding when it reads the file back.
        ('text with surrounding spaces', '  placeholder-padded-key  ', 'placeholder-padded-key'),
    ])
    def test_a_non_empty_text_key_is_bound(self, world, label, value, stored):
        settings, client, _ = world
        save(client, URL_OPTION, ADDRESS_A)

        response = save(client, KEY_OPTION, value)

        assert response.json()['success'] is True
        assert on_disk(settings, KEY_OPTION) == stored
        assert on_disk(settings, BINDING_OPTION) == BOUND_A

    def test_a_non_text_key_is_stored_and_bound(self, world):
        settings, client, _ = world
        save(client, URL_OPTION, ADDRESS_A)

        response = save_json(client, KEY_OPTION, 12345)

        assert response.json()['success'] is True
        assert on_disk(settings, KEY_OPTION) == '12345'
        assert on_disk(settings, BINDING_OPTION) == BOUND_A

    @pytest.mark.parametrize('blank', ['', '   ', '\t'])
    def test_a_blank_key_leaves_both_empty(self, world, blank):
        settings, client, _ = world
        bind_to_a(client)

        response = save(client, KEY_OPTION, blank)

        assert response.json()['success'] is True
        assert on_disk(settings, BINDING_OPTION) == ''
        assert memory(settings, BINDING_OPTION) == ''

    @pytest.mark.parametrize('falsy', [0, False, None, []])
    def test_a_falsy_non_text_key_holds_no_binding(self, world, falsy):
        """It is read as no key until a restart, so it must not carry an address."""
        settings, client, _ = world
        bind_to_a(client)

        response = save_json(client, KEY_OPTION, falsy)

        assert response.json()['success'] is True
        assert on_disk(settings, BINDING_OPTION) == ''


class TestNothingSecretIsLogged:
    """The key, the address and the binding are secrets or private paths: none reaches a log line."""

    def test_a_key_save_and_a_clearing_save_log_none_of_them(self, world):
        settings, client, _ = world
        save(client, URL_OPTION, 'http://test-user:test-pass@jackett-a.local:9117')

        with LogCapture() as logs:
            save(client, KEY_OPTION, PLACEHOLDER_KEY)
            save(client, KEY_OPTION, '')
            save(client, KEY_OPTION, '*' * len(PLACEHOLDER_KEY))
            save(client, BINDING_OPTION, 'http://evil.invalid:9117')

        ours = '\n'.join(r.getMessage() for r in logs.records if r.name.startswith('couchpotato'))
        for secret in (PLACEHOLDER_KEY, 'jackett-a.local', 'test-user', 'test-pass', 'evil.invalid'):
            assert secret not in ours


class TestTheHookNeverBlocksOrLeavesAStaleBinding:
    """AC-SEC-6: `fireEvent` would swallow a raise, and the key would keep the earlier key's binding."""

    def test_a_failure_reading_the_saved_address_still_stores_the_key_and_clears_the_old_binding(
            self, world, monkeypatch):
        settings, client, provider = world
        bind_to_a(client)

        def unreadable(name):
            raise RuntimeError('the address could not be read')

        monkeypatch.setattr(provider, '_savedJackettSetting', unreadable)

        response = save(client, KEY_OPTION, OTHER_KEY)

        assert response.json()['success'] is True
        assert on_disk(settings, KEY_OPTION) == OTHER_KEY
        assert on_disk(settings, BINDING_OPTION) == ''

    def test_the_hook_returns_nothing_so_the_key_is_stored_exactly_as_sent(self, world):
        settings, client, provider = world

        assert provider.bind_saved_key(PLACEHOLDER_KEY) is None


class TestWhatDoesNotMoveTheBinding:
    """AC-SEC-6 (writer clauses), AC-SEC-7 (writer clauses)"""

    def assert_binding_unchanged(self, settings, before_value):
        assert memory(settings, BINDING_OPTION) == before_value
        assert on_disk(settings, BINDING_OPTION) == before_value

    def test_the_displayed_mask_is_refused_and_nothing_changes(self, world):
        settings, client, _ = world
        bind_to_a(client)
        before = sha(settings.file)

        response = save(client, KEY_OPTION, '*' * len(PLACEHOLDER_KEY))

        assert response.json()['success'] is False
        assert sha(settings.file) == before
        self.assert_binding_unchanged(settings, BOUND_A)
        assert memory(settings, KEY_OPTION) == PLACEHOLDER_KEY

    def test_a_key_that_is_not_writable_is_refused_and_nothing_changes(self, world):
        settings, client, _ = world
        bind_to_a(client)
        settings.p.set(SECTION, KEY_OPTION + '_internal_meta', 'ro')
        settings.save()
        before = sha(settings.file)

        response = save(client, KEY_OPTION, OTHER_KEY)

        assert response.json()['success'] is False
        assert sha(settings.file) == before
        self.assert_binding_unchanged(settings, BOUND_A)

    def test_any_number_of_address_saves_leave_it_alone(self, world):
        settings, client, _ = world
        bind_to_a(client)

        for address in (ADDRESS_B, '', 'localhost:9999', 'http://[::1', ADDRESS_A, ADDRESS_B):
            assert save(client, URL_OPTION, address).json()['success'] is True
            self.assert_binding_unchanged(settings, BOUND_A)

    def test_a_group_save_of_the_provider_rows_leaves_it_alone(self, world):
        settings, client, _ = world
        bind_to_a(client)
        columns = settings.combine_groups()[SECTION]
        rows = [{column: ('1' if column == 'use' else 'placeholder-%s' % column) for column in columns}]
        rows[0].update({'host': 'http://indexer.invalid/api', 'seed_ratio': '1', 'seed_time': '40',
                        'extra_score': '0'})

        response = client.post(url(route='settings.save_group'), json={'section': SECTION, 'rows': rows})

        assert response.json()['success'] is True
        self.assert_binding_unchanged(settings, BOUND_A)

    def test_a_new_key_after_an_address_change_binds_to_the_new_address(self, world):
        settings, client, _ = world
        bind_to_a(client)
        save(client, URL_OPTION, ADDRESS_B)

        save(client, KEY_OPTION, OTHER_KEY)

        assert on_disk(settings, BINDING_OPTION) == BOUND_B

    def test_clearing_the_address_does_not_clear_the_binding(self, world):
        settings, client, _ = world
        bind_to_a(client)

        save(client, URL_OPTION, '')

        self.assert_binding_unchanged(settings, BOUND_A)
        assert on_disk(settings, KEY_OPTION) == PLACEHOLDER_KEY

    def test_clearing_the_key_clears_the_binding_in_the_same_write(self, world, monkeypatch):
        settings, client, _ = world
        bind_to_a(client)
        import couchpotato.core.settings as settings_module
        real = settings_module.os.replace
        written = []

        def recording_replace(src, dst):
            parser = configparser.RawConfigParser()
            parser.read(src, encoding='utf-8')
            written.append((parser.get(SECTION, KEY_OPTION), parser.get(SECTION, BINDING_OPTION)))
            return real(src, dst)

        monkeypatch.setattr(settings_module.os, 'replace', recording_replace)

        save(client, KEY_OPTION, '')

        # One write, and in it the key and the binding are both already empty.
        assert written == [('', '')]


class TestAFailedWriteLeavesNothingBehind:
    """AC-DATA-1 (writer clauses): memory is restored, so the next writer cannot persist it."""

    def test_a_faulted_key_save_keeps_the_old_key_and_binding_in_file_and_memory(self, world, monkeypatch):
        settings, client, _ = world
        bind_to_a(client)
        save(client, URL_OPTION, ADDRESS_B)
        before = sha(settings.file)
        import couchpotato.core.settings as settings_module

        def refuse_replace(src, dst):
            raise OSError('replace faulted by the test')

        with monkeypatch.context() as fault:
            fault.setattr(settings_module.os, 'replace', refuse_replace)
            first = save(client, KEY_OPTION, OTHER_KEY)

        assert first.status_code == 200
        assert first.json()['success'] is False
        assert sha(settings.file) == before
        assert memory(settings, KEY_OPTION) == PLACEHOLDER_KEY
        assert memory(settings, BINDING_OPTION) == BOUND_A

        later = save(client, 'enabled', '1')

        assert later.json()['success'] is True
        assert on_disk(settings, KEY_OPTION) == PLACEHOLDER_KEY
        assert on_disk(settings, BINDING_OPTION) == BOUND_A

    def test_a_save_with_no_companion_is_restored_too(self, world, monkeypatch):
        """The restore is generic: any option with a value hook gets it, not one name."""
        settings, client, _ = world
        before = memory(settings, URL_OPTION)
        import couchpotato.core.settings as settings_module
        addEvent('setting.save.torrentpotato.jackett_url', lambda value: None)
        with monkeypatch.context() as fault:
            fault.setattr(settings_module.os, 'replace',
                          lambda src, dst: (_ for _ in ()).throw(OSError('faulted')))
            save(client, URL_OPTION, ADDRESS_B)

        assert memory(settings, URL_OPTION) == before


class TestEveryAddressShapeStoresItsLiteral:
    """AC-OPS-7, AC-ARCH-5 (normaliser clauses): a key save over each shape stores that literal."""

    @pytest.mark.parametrize('label,saved,expected', NORMALISER_TABLE, ids=[r[0] for r in NORMALISER_TABLE])
    def test_a_key_save_stores_the_tables_string(self, world, label, saved, expected):
        settings, client, _ = world
        settings.p.set(SECTION, URL_OPTION, saved)
        settings.save()

        assert save(client, KEY_OPTION, PLACEHOLDER_KEY).json()['success'] is True

        assert on_disk(settings, BINDING_OPTION) == expected

    @pytest.mark.parametrize('label,saved', UNPARSEABLE, ids=[r[0] for r in UNPARSEABLE])
    def test_an_address_with_no_normal_form_never_blocks_the_save_and_leaves_the_binding_empty(
            self, world, label, saved):
        """AC-DATA-6 (writer clause): the key is stored, an earlier binding is removed."""
        settings, client, _ = world
        bind_to_a(client)
        settings.p.set(SECTION, URL_OPTION, saved)
        settings.save()

        response = save(client, KEY_OPTION, OTHER_KEY)

        assert response.json()['success'] is True
        assert on_disk(settings, KEY_OPTION) == OTHER_KEY
        assert on_disk(settings, BINDING_OPTION) == ''


class TestUpgradeCasesByValue:
    """AC-QA-13 (writer clauses), AC-QA-15 (writer clause): empty and absent are one state."""

    LEGACY = {SECTION: {URL_OPTION: ADDRESS_A, KEY_OPTION: PLACEHOLDER_KEY}}

    def test_a_pre_upgrade_file_has_no_binding_after_start_and_gets_one_from_a_key_save(
            self, tmp_path, monkeypatch):
        with jackett_world(tmp_path, monkeypatch, stored=self.LEGACY) as (settings, client, _):
            # `registerDefaults` has run and been saved, as the loader does at every start.
            assert on_disk(settings, BINDING_OPTION) == ''
            assert memory(settings, KEY_OPTION) == PLACEHOLDER_KEY

            assert save(client, KEY_OPTION, OTHER_KEY).json()['success'] is True

            assert on_disk(settings, BINDING_OPTION) == BOUND_A

    def test_registering_again_does_not_create_or_change_a_binding(self, tmp_path, monkeypatch):
        with jackett_world(tmp_path, monkeypatch, stored=self.LEGACY) as (settings, client, _):
            bind_to_a(client)
            options = {option['name']: option
                       for entry in __import__(
                           'couchpotato.core.media._base.providers.torrent.torrentpotato',
                           fromlist=['config']).config
                       for group in entry['groups'] for option in group['options']}

            settings.registerDefaults(SECTION, options)

            assert on_disk(settings, BINDING_OPTION) == BOUND_A

    def test_no_key_means_no_binding_after_a_save_of_the_address(self, tmp_path, monkeypatch):
        stored = {SECTION: {URL_OPTION: ADDRESS_A}}
        with jackett_world(tmp_path, monkeypatch, stored=stored) as (settings, client, _):
            assert save(client, URL_OPTION, ADDRESS_B).json()['success'] is True

            assert on_disk(settings, BINDING_OPTION) == ''
            assert on_disk(settings, KEY_OPTION) == ''

    def test_an_unparseable_address_with_a_key_gets_an_empty_binding(self, tmp_path, monkeypatch):
        stored = {SECTION: {URL_OPTION: 'localhost:99999', KEY_OPTION: PLACEHOLDER_KEY}}
        with jackett_world(tmp_path, monkeypatch, stored=stored) as (settings, client, _):
            assert save(client, KEY_OPTION, OTHER_KEY).json()['success'] is True

            assert on_disk(settings, BINDING_OPTION) == ''
            assert on_disk(settings, KEY_OPTION) == OTHER_KEY

    def test_a_bytes_literal_address_is_unwrapped_in_the_binding(self, tmp_path, monkeypatch):
        stored = {SECTION: {URL_OPTION: "b'http://jackett-a.local:9117/'", KEY_OPTION: "b'placeholder-old'"}}
        with jackett_world(tmp_path, monkeypatch, stored=stored) as (settings, client, _):
            assert save(client, KEY_OPTION, OTHER_KEY).json()['success'] is True

            binding = on_disk(settings, BINDING_OPTION)
            assert binding == BOUND_A
            assert "b'" not in binding


class TestSingleFileStorage:
    """AC-DATA-10 (single-file storage)"""

    def test_the_binding_lives_beside_the_key_in_config_ini_and_nowhere_else(self, world, tmp_path):
        settings, client, _ = world
        before = sorted(p.name for p in tmp_path.rglob('*'))

        bind_to_a(client)

        assert sorted(p.name for p in tmp_path.rglob('*')) == before
        assert on_disk(settings, BINDING_OPTION, section=SECTION) == BOUND_A
        assert on_disk(settings, KEY_OPTION, section=SECTION) == PLACEHOLDER_KEY
        for section in settings.p.sections():
            if section != SECTION:
                assert not settings.p.has_option(section, BINDING_OPTION)

    def test_the_stored_binding_is_not_a_digest(self, world):
        settings, client, _ = world

        bind_to_a(client)

        assert json.dumps(on_disk(settings, BINDING_OPTION)) == json.dumps(BOUND_A)
