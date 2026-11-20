"""``settings.save`` refuses the access-flag name of an option, in any spelling.

An option's access flag (`ro`, `hidden`, `rw`) is stored as
``<option>_internal_meta``. The config parser lower-cases names, so
``API_KEY_INTERNAL_META`` was stored over the real flag and the read-only
``core.api_key`` could then be overwritten. These tests drive the real endpoint
over every transport, with ``core`` registered from its live declaration.
"""
import logging

import pytest

from couchpotato.core._base import _core
from couchpotato.core.event import addEvent
from tests.helpers.combine_groups import LogCapture, sha
from tests.integration.test_settings_group_save_route import API_KEY, live_world, url

pytestmark = pytest.mark.integration

ROUTE = 'settings.save'
CANARY = 'canary-value-must-never-come-back'
TRANSPORTS = ('form', 'json', 'query')
FLAG_NAME = 'API_KEY_INTERNAL_META'
FLAG_TEXT = 'An option flag cannot be changed through settings.save. Nothing was saved.'
FLAG_WARNING = "Refused a settings save: the option name is an access flag (section='core')"


@pytest.fixture
def world(tmp_path, monkeypatch):
    with live_world(tmp_path, monkeypatch) as live:
        settings, client = live
        options = {option['name']: option
                   for entry in _core.config if entry['name'] == 'core'
                   for group in entry['groups'] for option in group['options']}
        settings.registerDefaults('core', options)
        yield settings, client


def send(client, section, name, value=CANARY, transport='form'):
    fields = {'section': section, 'name': name, 'value': value}
    if transport == 'json':
        return client.post(url(route=ROUTE), json=fields)
    if transport == 'query':
        return client.get(url(route=ROUTE), params=fields)
    return client.post(url(route=ROUTE), data=fields)


def ours(logs):
    return [record.getMessage().split('] ', 1)[-1] for record in logs.at_or_above(logging.WARNING)
            if record.name.startswith('couchpotato')]


@pytest.mark.parametrize('transport', TRANSPORTS)
class TestTheFlagNameIsRefusedOverEveryTransport:

    def test_it_is_refused_and_config_ini_is_byte_identical(self, world, transport):
        settings, client = world
        before = sha(settings.file)

        response = send(client, 'core', FLAG_NAME, value='rw', transport=transport)

        assert response.json() == {'success': False, 'error': FLAG_TEXT}
        assert sha(settings.file) == before

    def test_memory_is_unchanged_and_no_hook_fires(self, world, transport):
        settings, client = world
        fired = []
        for suffix in ('', '.after', '.committed'):
            name = 'setting.save.core.%s%s' % (FLAG_NAME, suffix)
            addEvent(name, lambda *args, _name=name, **kwargs: fired.append(_name))
            lowered = name.lower()
            addEvent(lowered, lambda *args, _name=lowered, **kwargs: fired.append(_name))

        send(client, 'core', FLAG_NAME, value='rw', transport=transport)

        assert settings.p.get('core', 'api_key_internal_meta') == 'ro'
        assert fired == []

    def test_the_read_only_api_key_cannot_be_overwritten_afterwards(self, world, transport):
        settings, client = world
        key = settings.p.get('core', 'api_key')
        send(client, 'core', FLAG_NAME, value='rw', transport=transport)
        before = sha(settings.file)

        response = send(client, 'core', 'api_key', value='placeholder-key-two', transport=transport)

        assert response.json() == {'success': False}
        assert settings.p.get('core', 'api_key') == key
        assert sha(settings.file) == before

    def test_one_warning_with_neither_the_spelling_nor_the_value(self, world, transport):
        settings, client = world

        with LogCapture() as logs:
            response = send(client, 'core', FLAG_NAME, value=CANARY, transport=transport)

        assert ours(logs) == [FLAG_WARNING]
        assert CANARY not in '\n'.join(ours(logs)) + response.text
        assert 'INTERNAL' not in '\n'.join(ours(logs)) + response.text
