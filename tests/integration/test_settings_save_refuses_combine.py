"""SEC-004 P6: ``settings.save`` refuses the columns of a combine group.

A combine group is saved as one unit through ``settings.save_group``. The old
per-column route would write one column and leave the others as they were, which
is how a row ends up with another row's key. These tests drive the real
endpoint over every transport (POST form, POST JSON, GET query) against a real
``Settings`` over a temporary ``config.ini`` with the five real declarations,
and read the file back with a fresh parser.

Every refusal is measured on the file (sha256), on the event bus (no
``setting.save.<section>.<option>`` hook fires) and on the log (one WARNING that
names ``section.option`` and no value). The submitted value is a canary that
must never come back in a body or a log line.
"""
import configparser
import logging

import pytest

from couchpotato.core.event import addEvent
from tests.helpers.combine_groups import LogCapture, sha
from tests.integration.test_settings_group_save_route import API_KEY, live_world, url

pytestmark = pytest.mark.integration

ROUTE = 'settings.save'
CANARY = 'canary-value-must-never-come-back'
TRANSPORTS = ('form', 'json', 'query')


@pytest.fixture
def world(tmp_path, monkeypatch):
    with live_world(tmp_path, monkeypatch) as live:
        yield live


def send(client, section, name, value=CANARY, transport='form'):
    """One per-column save over the named transport, the way a browser or a script sends it."""
    fields = {'section': section, 'name': name, 'value': value}
    if transport == 'json':
        return client.post(url(route=ROUTE), json=fields)
    if transport == 'query':
        return client.get(url(route=ROUTE), params=fields)
    return client.post(url(route=ROUTE), data=fields)


def declared(settings):
    """Every (section, column) of every registered group, read from the loaded settings."""
    return [(section, column) for section, columns in sorted(settings.combine_groups().items())
            for column in columns]


def hooks_for(*names):
    """Register a recorder on each event name and return the list it appends to."""
    fired = []
    for name in names:
        addEvent(name, lambda *args, _name=name, **kwargs: fired.append(_name))
    return fired


def stored(settings, section, option):
    parser = configparser.RawConfigParser()
    parser.read(settings.file, encoding='utf-8')
    return parser.get(section, option, fallback=None)


def spellings(column):
    """The column as a caller might spell it: case and whitespace variants."""
    return [column, column.upper(), column.title(), ' ' + column, column + ' ',
            '\t%s\n' % column, ' %s ' % column.upper()]


class TestEveryColumnOfEveryGroupIsRefused:
    """AC-SEC-3, AC-SEC-8 (refused clause), AC-OPS-2."""

    def test_the_refused_set_is_the_registered_groups_not_a_list_in_the_test(self, world):
        settings, _ = world
        pairs = declared(settings)

        assert {section for section, _ in pairs} == {
            'newznab', 'torrentpotato', 'imdb', 'itunes', 'letterboxd'}
        assert len(pairs) >= 15

    @pytest.mark.parametrize('transport', TRANSPORTS)
    def test_every_column_is_refused_with_the_file_untouched(self, world, transport):
        settings, client = world
        for section, column in declared(settings):
            before = sha(settings.file)

            response = send(client, section, column, transport=transport)

            assert response.json()['success'] is False, (section, column)
            assert sha(settings.file) == before, (section, column)
            assert CANARY not in response.text, (section, column)

    @pytest.mark.parametrize('transport', TRANSPORTS)
    @pytest.mark.parametrize('section, column', [
        ('newznab', 'host'), ('newznab', 'api_key'), ('torrentpotato', 'pass_key'),
        ('imdb', 'automation_urls'), ('letterboxd', 'automation_urls_use')])
    def test_case_and_whitespace_variants_are_refused_as_the_column_they_would_become(
            self, world, transport, section, column):
        settings, client = world
        for name in spellings(column):
            before = sha(settings.file)
            fired = hooks_for('setting.save.%s.%s' % (section, name),
                              'setting.save.%s.%s' % (section, column))

            response = send(client, section, name, transport=transport)

            body = response.json()
            assert body['success'] is False, repr(name)
            assert sha(settings.file) == before, repr(name)
            assert fired == [], 'a save hook ran for a refused save: %r' % (name,)
            assert CANARY not in response.text, repr(name)
            assert column in body['error'], repr(name)

    def test_a_refusal_changes_nothing_in_memory_either(self, world):
        settings, client = world
        columns = settings.combine_groups()['newznab']
        before = {column: settings.p.get('newznab', column) for column in columns}

        send(client, 'newznab', 'API_KEY')
        settings.addSection('core')
        settings.set('core', 'zz_later_unrelated', '1')
        settings.save()

        assert {column: stored(settings, 'newznab', column) for column in columns} == before

    def test_no_hook_fires_for_a_refused_save_on_any_transport(self, world):
        settings, client = world
        fired = hooks_for(*('setting.save.%s.%s%s' % (section, column, suffix)
                            for section, column in declared(settings)
                            for suffix in ('', '.after', '.committed')))

        for transport in TRANSPORTS:
            send(client, 'newznab', 'host', transport=transport)

        assert fired == []


class TestTheRefusalTellsTheUserWhatToDo:
    """AC-OPS-2: the field, the group-save route, a reload; never the value."""

    @pytest.mark.parametrize('transport', TRANSPORTS)
    def test_the_error_names_the_field_the_route_and_a_reload(self, world, transport):
        settings, client = world

        body = send(client, 'newznab', 'API_KEY', transport=transport).json()

        assert body['success'] is False
        assert 'newznab.api_key' in body['error']
        assert 'settings.save_group' in body['error']
        assert 'reload' in body['error'].lower()
        assert body['error'] != 'Failed returning results'
        assert set(body) == {'success', 'error'}

    def test_the_text_is_the_one_the_settings_page_test_pins(self, world):
        """`tests/unit/ui/settings-save-single-refusal.spec.ts` carries the same words."""
        settings, client = world

        body = send(client, 'newznab', 'Host ').json()

        assert body['error'] == (
            '"newznab.host" is saved together with the rest of its group, not on its own. '
            'Nothing was saved. Use settings.save_group, or reload the page and edit the rows there.')

    def test_exactly_one_warning_names_section_and_option_and_no_value(self, world):
        settings, client = world

        with LogCapture() as logs:
            send(client, 'newznab', ' Host ', value=CANARY)

        warnings = logs.at_or_above(logging.WARNING)
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert warnings[0].levelno == logging.WARNING
        assert 'newznab.host' in warnings[0].getMessage()
        assert CANARY not in logs.text()

    def test_the_caller_s_spelling_is_never_echoed_in_the_log_or_the_body(self, world):
        settings, client = world

        with LogCapture() as logs:
            response = send(client, 'newznab', '\tHOST\x1f\n', value=CANARY)

        assert response.json()['success'] is False
        assert '\x1f' not in response.text and '\x1f' not in logs.text()
        assert 'newznab.host' in logs.text()


class TestAnyNameWithWhitespaceOrAControlCharacterIsRefused:
    """AC-SEC-3, second half: for every section, combine or not."""

    BAD_NAMES = ['enabled ', ' enabled', 'en abled', 'enabled\t', 'enabled\n', 'enabled\r',
                 'enab\x00led', 'enab\x1fled', '\x01enabled', 'enab\x0bled', 'enab\x0cled']

    @pytest.mark.parametrize('transport', TRANSPORTS)
    @pytest.mark.parametrize('section', ['core', 'newznab', 'torrentpotato', 'imdb', 'zz_unregistered'])
    def test_each_bad_name_is_refused_and_the_file_is_unchanged(self, world, transport, section):
        settings, client = world
        for name in self.BAD_NAMES:
            before = sha(settings.file)
            fired = hooks_for('setting.save.%s.%s' % (section, name),
                              'setting.save.%s.enabled' % section)

            response = send(client, section, name, value='1', transport=transport)

            assert response.json()['success'] is False, (section, repr(name))
            assert sha(settings.file) == before, (section, repr(name))
            assert fired == [], (section, repr(name))

    def test_the_file_still_loads_after_a_trailing_space_name_was_sent(self, world):
        settings, client = world

        send(client, 'newznab', 'custom_categories ', value='placeholder-categories')

        reloaded = configparser.RawConfigParser()
        reloaded.read(settings.file, encoding='utf-8')
        assert reloaded.has_section('newznab')

    def test_a_combine_column_with_whitespace_gets_the_combine_text_not_the_name_text(self, world):
        settings, client = world

        combine = send(client, 'newznab', 'host ').json()['error']
        other = send(client, 'newznab', 'ho st').json()['error']

        assert 'settings.save_group' in combine
        assert 'settings.save_group' not in other
        assert combine != other

    def test_the_name_refusal_logs_one_warning_without_the_value_or_raw_control_characters(self, world):
        settings, client = world

        with LogCapture() as logs:
            send(client, 'core', 'bad\x1bname', value=CANARY)

        warnings = logs.at_or_above(logging.WARNING)
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert CANARY not in logs.text()
        assert '\x1b' not in logs.text()


class TestOptionsOutsideAGroupStillSavePerColumn:
    """AC-QA-7."""

    @pytest.mark.parametrize('section, name, value', [
        ('newznab', 'enabled', '1'),
        ('newznab', 'custom_categories', 'placeholder-categories'),
        ('torrentpotato', 'jackett_url', 'http://jackett.invalid:9117'),
        ('imdb', 'automation_enabled', '1'),
    ])
    @pytest.mark.parametrize('transport', TRANSPORTS)
    def test_it_returns_success_and_writes_the_value(self, world, transport, section, name, value):
        settings, client = world
        before = sha(settings.file)

        body = send(client, section, name, value=value, transport=transport).json()

        assert body['success'] is True
        assert sha(settings.file) != before
        assert stored(settings, section, name) not in (None, '')

    def test_a_per_column_save_leaves_the_group_columns_as_they_were(self, world):
        settings, client = world
        columns = settings.combine_groups()['newznab']
        before = {column: stored(settings, 'newznab', column) for column in columns}

        send(client, 'newznab', 'custom_categories', value='placeholder-categories')

        assert {column: stored(settings, 'newznab', column) for column in columns} == before


class TestAGroupRegisteredLaterIsRefusedWithNoProductionEdit:
    """AC-ARCH-1: the groups come from the registered declarations, nothing else."""

    ZZ = {'name': 'zz_test', 'groups': [{'options': [
        {'name': 'use'},
        {'name': 'host'},
        {'name': 'key', 'type': 'combined', 'combine': ['use', 'host', 'key']},
    ]}]}

    def test_the_group_save_accepts_it_and_the_per_column_save_refuses_it(self, world):
        settings, client = world
        settings.addOptions('zz_test', self.ZZ)
        rows = [{'use': '1', 'host': 'https://zz-a.invalid', 'key': 'placeholder-zz-a'},
                {'use': '0', 'host': 'https://zz-b.invalid', 'key': 'placeholder-zz-b'}]

        saved = client.post(url(route='settings.save_group'),
                            json={'section': 'zz_test', 'rows': rows})
        assert saved.json() == {'success': True}
        after_group = sha(settings.file)

        for name in ('host', 'HOST', 'host ', 'use', 'key'):
            refused = send(client, 'zz_test', name)
            assert refused.json()['success'] is False, name
            assert 'zz_test.' in refused.json()['error']
            assert sha(settings.file) == after_group, name
        assert stored(settings, 'zz_test', 'host') == 'https://zz-a.invalid,https://zz-b.invalid'

    def test_the_same_names_in_an_unregistered_section_are_not_a_group_column(self, world):
        settings, _ = world

        assert settings.is_combine_option('zz_test', 'host') is False


def test_the_api_key_is_still_required(world):
    settings, client = world
    before = sha(settings.file)

    response = client.post('/api/settings.save', data={'section': 'newznab', 'name': 'enabled',
                                                        'value': '0'})

    assert response.status_code == 401
    assert sha(settings.file) == before
    assert API_KEY not in response.text
