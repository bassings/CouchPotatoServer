"""SEC-005 P1: the binding cannot be written or read over HTTP.

If whoever can change the address could also re-point the binding in the same
breath, or read it back, the control would be decorative. These tests drive the
real ``settings.save``, ``settings.save_group`` and ``settings`` routes with the
real ``torrentpotato`` declaration, over every transport, with a binding already
stored for address A and read the file and the parser afterwards.

Hosts are ``.local`` or ``.invalid`` and every key is a ``placeholder-`` string.
"""
import json

import pytest

from tests.helpers.combine_groups import sha
from tests.helpers.jackett_binding import (
    BINDING_FLAG_OPTION,
    BINDING_OPTION,
    KEY_OPTION,
    PLACEHOLDER_KEY,
    SECTION,
    URL_OPTION,
    jackett_world,
    on_disk,
)
from tests.integration.test_settings_group_save_route import url

pytestmark = pytest.mark.integration

ROUTE = 'settings.save'
GROUP_ROUTE = 'settings.save_group'
ADDRESS_A = 'http://jackett-a.local:9117'
ADDRESS_B = 'http://jackett-b.local:9117'
EVIL = 'http://evil.invalid:9117'
TRANSPORTS = ('form', 'json', 'query')

# Every spelling that the parser's `optionxform` (lower case) plus `strip()` folds
# onto the stored name.
BINDING_SPELLINGS = [
    BINDING_OPTION,
    BINDING_OPTION.upper(),
    'Jackett_Key_Binding',
    ' ' + BINDING_OPTION,
    BINDING_OPTION + ' ',
    '\t' + BINDING_OPTION,
]
# The flag's own name in the same spellings; the case rows are the ones the
# prerequisite (#612) fixed, so they go red if its refusal is reverted. The
# whitespace and tab rows are refused by the unsafe-name rule either way.
FLAG_SPELLINGS = [
    ('lower case', BINDING_FLAG_OPTION),
    ('upper case', BINDING_FLAG_OPTION.upper()),
    ('mixed case', 'Jackett_Key_Binding_Internal_Meta'),
    ('leading space', ' ' + BINDING_FLAG_OPTION),
    ('trailing space', BINDING_FLAG_OPTION + ' '),
    ('leading tab', '\t' + BINDING_FLAG_OPTION),
    ('trailing tab', BINDING_FLAG_OPTION + '\t'),
]


@pytest.fixture
def world(tmp_path, monkeypatch):
    with jackett_world(tmp_path, monkeypatch) as (settings, client, provider):
        client.post(url(route=ROUTE), data={'section': SECTION, 'name': URL_OPTION, 'value': ADDRESS_A})
        client.post(url(route=ROUTE), data={'section': SECTION, 'name': KEY_OPTION, 'value': PLACEHOLDER_KEY})
        assert on_disk(settings, BINDING_OPTION) == ADDRESS_A
        yield settings, client


def send(client, name, value, transport, section=SECTION):
    fields = {'section': section, 'name': name, 'value': value}
    if transport == 'json':
        return client.post(url(route=ROUTE), json=fields)
    if transport == 'query':
        return client.get(url(route=ROUTE), params=fields)
    return client.post(url(route=ROUTE), data=fields)


def held(settings, option):
    return settings.p.get(SECTION, option)


@pytest.mark.parametrize('transport', TRANSPORTS)
class TestTheBindingCannotBeWritten:
    """AC-SEC-4"""

    @pytest.mark.parametrize('name', BINDING_SPELLINGS, ids=repr)
    @pytest.mark.parametrize('value', [EVIL, ''], ids=['another address', 'empty'])
    def test_a_save_of_the_binding_is_refused_and_nothing_changes(self, world, transport, name, value):
        settings, client = world
        before = sha(settings.file)

        response = send(client, name, value, transport)

        assert response.json()['success'] is False
        assert sha(settings.file) == before
        assert held(settings, BINDING_OPTION) == ADDRESS_A

    def test_the_flag_is_unchanged_afterwards(self, world, transport):
        settings, client = world

        send(client, BINDING_OPTION, EVIL, transport)

        assert held(settings, BINDING_FLAG_OPTION) == 'hidden'

    def test_the_binding_cannot_be_written_into_another_section(self, world, transport):
        """A save of the same name elsewhere must not reach this section's binding."""
        settings, client = world
        before = held(settings, BINDING_OPTION)

        send(client, BINDING_OPTION, EVIL, transport, section='core')

        assert held(settings, BINDING_OPTION) == before


class TestAGroupSaveCannotWriteIt:
    """AC-SEC-4"""

    def test_a_group_save_with_the_binding_as_an_extra_column_is_refused(self, world):
        settings, client = world
        columns = list(settings.combine_groups()[SECTION])
        row = {column: '1' if column == 'use' else '0' if column in ('extra_score',) else 'placeholder-' + column
               for column in columns}
        row.update({'host': 'http://indexer.invalid/api', 'seed_ratio': '1', 'seed_time': '40'})
        # Control: the same row without the extra column is a valid save, so the
        # refusal below is about the binding and nothing else in the row.
        control = client.post(url(route=GROUP_ROUTE), json={'section': SECTION, 'rows': [row]})
        assert control.json()['success'] is True
        row[BINDING_OPTION] = EVIL
        before = sha(settings.file)

        response = client.post(url(route=GROUP_ROUTE), json={'section': SECTION, 'rows': [row]})

        assert response.json()['success'] is False
        assert sha(settings.file) == before
        assert held(settings, BINDING_OPTION) == ADDRESS_A

    @pytest.mark.parametrize('section', ['newznab', 'core', 'imdb'])
    def test_a_group_save_naming_it_in_any_other_section_is_refused(self, world, section):
        settings, client = world
        before = sha(settings.file)
        row = {BINDING_OPTION: EVIL}

        response = client.post(url(route=GROUP_ROUTE), json={'section': section, 'rows': [row]})

        assert response.json()['success'] is False
        assert sha(settings.file) == before
        assert held(settings, BINDING_OPTION) == ADDRESS_A


@pytest.mark.parametrize('transport', TRANSPORTS)
class TestTheFlagNameCannotBeUsedToUnlockIt:
    """AC-SEC-15. Under a revert of #612 the upper-case and mixed-case rows go red."""

    @pytest.mark.parametrize('label,name', FLAG_SPELLINGS, ids=[r[0] for r in FLAG_SPELLINGS])
    def test_the_flag_name_is_refused_unchanged_and_the_binding_stays_unwritable(
            self, world, transport, label, name):
        settings, client = world
        before = sha(settings.file)

        response = send(client, name, 'rw', transport)

        assert response.json()['success'] is False
        assert sha(settings.file) == before
        assert held(settings, BINDING_FLAG_OPTION) == 'hidden'
        # The variants were written first; now the binding itself.
        follow_up = send(client, BINDING_OPTION, EVIL, transport)
        assert follow_up.json()['success'] is False
        assert held(settings, BINDING_OPTION) == ADDRESS_A
        assert on_disk(settings, BINDING_OPTION) == ADDRESS_A

    def test_all_the_variants_one_after_another_still_leave_it_unwritable(self, world, transport):
        settings, client = world
        for _, name in FLAG_SPELLINGS:
            send(client, name, 'rw', transport)

        response = send(client, BINDING_OPTION, EVIL, transport)

        assert response.json()['success'] is False
        assert held(settings, BINDING_OPTION) == ADDRESS_A


class TestTheBindingCannotBeRead:
    """AC-SEC-5"""

    def test_neither_its_name_nor_its_value_is_in_the_settings_read(self, world):
        settings, client = world
        # The address is now another one, so A can only come from the binding.
        client.post(url(route=ROUTE), data={'section': SECTION, 'name': URL_OPTION, 'value': ADDRESS_B})
        text = open(settings.file, encoding='utf-8').read()
        assert text.count(ADDRESS_A) == 1, 'A must occur in config.ini only as the binding'
        assert text.split(ADDRESS_A)[0].splitlines()[-1].startswith(BINDING_OPTION)
        assert ADDRESS_A not in ADDRESS_B
        assert not any(host for host in settings.p.get(SECTION, 'host').split(','))

        response = client.get(url(route='settings'))

        body = json.dumps(response.json())
        assert response.json()['values'][SECTION][URL_OPTION] == ADDRESS_B
        assert BINDING_OPTION not in body
        assert ADDRESS_A not in body

    def test_it_is_not_in_the_rendered_options_either(self, world):
        settings, client = world

        options = client.get(url(route='settings')).json()['options']

        assert BINDING_OPTION not in json.dumps(options)

    def test_the_read_is_not_empty_for_the_rest_of_the_section(self, world):
        """The filter drops one option, not the section: the address and the (masked) key are still read."""
        settings, client = world

        values = client.get(url(route='settings')).json()['values'][SECTION]

        assert values[URL_OPTION] == ADDRESS_A
        assert values[KEY_OPTION] == '*' * len(PLACEHOLDER_KEY)


class TestTheDeclaration:
    """AC-ARCH-2"""

    def test_the_option_is_declared_hidden_in_the_providers_own_config(self):
        from couchpotato.core.media._base.providers.torrent.torrentpotato import config
        declared = {option['name']: option for entry in config
                    for group in entry['groups'] for option in group['options']}

        assert declared[BINDING_OPTION]['ui-meta'] == 'hidden'
        assert declared[BINDING_OPTION]['default'] == ''
        assert set(declared[BINDING_OPTION]) == {'name', 'default', 'ui-meta'}

    def test_it_is_not_a_combine_column(self, world):
        settings, _ = world

        assert BINDING_OPTION not in settings.combine_groups()[SECTION]
        assert not settings.is_combine_option(SECTION, BINDING_OPTION)
