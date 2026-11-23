"""SEC-006 P1c: `settings.reveal_cell`, the one route that returns a stored credential cell.

A POST of exactly `section`, `column`, `row` and `token` as JSON. The gate is the API key
and the Origin check and nothing else (owner decision D4). It returns the stored text of
secret cell `row` and nothing more, and refuses without a value for a column that is not a
declared secret, a stale or missing token and a row outside the column.

The real app (`create_app` with the real CORS middleware) over a real `Settings` and a
temporary `config.ini`. Hostile probes first prove the CORS preflight for their header set
succeeds. Placeholder values and `.invalid` hosts only.
"""
import logging
import os

import pytest

from couchpotato import JSONP_REFUSED_API_ROUTES, ORIGIN_CHECKED_API_ROUTES
from couchpotato.core import settings as settings_module
from couchpotato.core.helpers.variable import md5
from tests.helpers.combine_groups import LogCapture, sha
from tests.integration.test_settings_keep_restore_route import (
    API_KEY,
    FORWARDED,
    HOSTILE,
    LISTED,
    OWN,
    REFUSED,
    world_with,
)
from tests.unit.test_settings_keep_restore import KEYS, keep, keyed_rows, seeded, token_of, with_forms

pytestmark = pytest.mark.integration

ROUTE = 'settings.reveal_cell'
URL = '/api/%s/%s' % (API_KEY, ROUTE)
NON_ASCII = 'placéholder-kéy-ü☃'


@pytest.fixture
def world(tmp_path, monkeypatch):
    with world_with(tmp_path, monkeypatch) as live:
        yield live


def reveal(client, section='newznab', column='api_key', row=0, token=None, headers=OWN, **extra):
    body = {'section': section, 'column': column, 'row': row, 'token': token, **extra}
    return client.post(URL, json=body, headers=headers)


def preflight_allowed(client):
    response = client.options(URL, headers={
        'origin': LISTED, 'access-control-request-method': 'POST',
        'access-control-request-headers': 'content-type,x-forwarded-host'})
    assert response.status_code == 200, response.text
    assert response.headers.get('access-control-allow-origin') == LISTED


def refused_without_value(response, *needles):
    assert response.status_code in (200, 400, 403), response.status_code
    body = response.text
    assert response.json().get('success') is False, body
    assert 'value' not in response.json()
    for needle in needles:
        assert needle.strip() not in body


class TestTheGateIsTheApiKeyAndTheOriginCheck:
    def test_the_route_is_origin_checked_and_never_offered_as_jsonp(self):
        assert ROUTE in ORIGIN_CHECKED_API_ROUTES
        assert ROUTE in JSONP_REFUSED_API_ROUTES

    def test_the_forwarded_host_regression_a_listed_origin_cannot_vouch_for_itself(self, world):
        settings, client = world
        rows, token = seeded(settings)
        preflight_allowed(client)

        response = reveal(client, token=token, headers={**FORWARDED, 'host': 'cp.invalid:5050'})

        assert response.status_code == 403
        assert response.json() == REFUSED
        assert all(key.strip() not in response.text for key in KEYS)

    @pytest.mark.parametrize('headers', [None, {}, {'origin': 'http://evil.invalid'},
                                         {'referer': 'http://evil.invalid/page'}, HOSTILE,
                                         {'referer': LISTED + '/page'}])
    def test_neither_header_or_a_foreign_one_is_refused_403_with_no_value(self, world, headers):
        settings, client = world
        rows, token = seeded(settings)

        response = reveal(client, token=token, headers=headers)

        assert response.status_code == 403
        assert response.json() == REFUSED

    def test_the_servers_own_origin_with_a_current_token_is_answered(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = reveal(client, row=0, token=token, headers=OWN)

        assert response.status_code == 200
        assert response.json() == {'success': True, 'value': KEYS[0]}

    def test_the_servers_own_referer_is_enough_too(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = reveal(client, token=token, headers={'referer': 'http://testserver/settings/'})

        assert response.json() == {'success': True, 'value': KEYS[0]}

    @pytest.mark.parametrize('key', [None, 'wrong-key'])
    def test_no_or_a_wrong_api_key_is_401_with_no_value(self, world, key):
        settings, client = world
        rows, token = seeded(settings)
        path = '/api/%s' % ROUTE if key is None else '/api/%s/%s' % (key, ROUTE)

        response = client.post(path, json={'section': 'newznab', 'column': 'api_key', 'row': 0,
                                           'token': token}, headers=OWN)

        assert response.status_code == 401
        assert all(k.strip() not in response.text for k in KEYS)

    def test_a_password_with_no_session_cookie_is_enough_when_the_api_key_is_right(self, tmp_path, monkeypatch):
        """Owner decision D4, pinned as the recorded decision: the API key is the gate.

        With a web-interface password set and no session cookie at all, a reveal whose
        URL carries the API key is answered. A password on the web interface does not
        protect indexer keys from a holder of the API key.
        """
        with world_with(tmp_path, monkeypatch, username='admin', password=md5('placeholder-pass'),
                        auth_required=True) as (settings, client):
            rows, token = seeded(settings)
            assert not client.cookies

            response = reveal(client, token=token)

            assert response.status_code == 200
            assert response.json() == {'success': True, 'value': KEYS[0]}


class TestTheTransportIsStrictJson:
    def test_a_get_is_refused_400_with_no_value(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = client.get(URL, params={'section': 'newznab', 'column': 'api_key', 'row': 0,
                                           'token': token}, headers=OWN)

        assert response.status_code == 400
        assert all(k.strip() not in response.text for k in KEYS)

    @pytest.mark.parametrize('how', ['get', 'post'])
    def test_a_jsonp_callback_is_refused_400_with_no_value(self, world, how):
        settings, client = world
        rows, token = seeded(settings)
        body = {'section': 'newznab', 'column': 'api_key', 'row': 0, 'token': token}
        query = {'callback_func': 'steal'}

        response = (client.get(URL, params={**body, **query}, headers=OWN) if how == 'get'
                    else client.post(URL, params=query, json=body, headers=OWN))

        assert response.status_code == 400
        assert 'steal(' not in response.text
        assert all(k.strip() not in response.text for k in KEYS)

    def test_the_t_cache_buster_is_the_only_query_parameter_allowed(self, world):
        settings, client = world
        rows, token = seeded(settings)

        ok = client.post(URL, params={'t': '1'}, json={'section': 'newznab', 'column': 'api_key',
                                                       'row': 0, 'token': token}, headers=OWN)
        other = client.post(URL, params={'x': '1'}, json={'section': 'newznab', 'column': 'api_key',
                                                          'row': 0, 'token': token}, headers=OWN)

        assert ok.status_code == 200
        assert other.status_code == 400

    def test_a_transport_refusal_says_nothing_was_revealed_not_nothing_was_saved(self, world):
        settings, client = world
        rows, token = seeded(settings)

        for response in (reveal(client, token=token, extra='x'), client.get(URL, headers=OWN),
                         reveal(client, row=True, token=token)):
            assert response.status_code == 400
            assert response.json() == {
                'success': False,
                'error': 'The request was not a reveal of one cell. Nothing was revealed.',
                'invalid': [{'row': None, 'column': None, 'reason': 'malformed'}]}

    def test_the_refusal_text_is_chosen_through_the_table_not_by_a_route_name(self):
        import inspect

        import couchpotato
        source = inspect.getsource(couchpotato._strict_json_refusal) + inspect.getsource(
            couchpotato._strict_json_body_ok)

        assert 'reveal' not in source
        assert 'save_group' not in source
        assert all(len(entry) == 4 and callable(entry[3]) for entry in couchpotato.STRICT_JSON_API_ROUTES.values())

    def test_the_cross_origin_cell_check_has_a_safe_path_for_a_route_with_no_rows(self):
        import couchpotato

        assert couchpotato._rows_carry_non_text(ROUTE, {'section': 'newznab', 'row': 0}) is False

    @pytest.mark.parametrize('drop', ['section', 'column', 'row', 'token'])
    def test_a_missing_key_is_400(self, world, drop):
        settings, client = world
        rows, token = seeded(settings)
        body = {'section': 'newznab', 'column': 'api_key', 'row': 0, 'token': token}
        del body[drop]

        assert client.post(URL, json=body, headers=OWN).status_code == 400

    def test_an_extra_key_is_400(self, world):
        settings, client = world
        rows, token = seeded(settings)

        assert reveal(client, token=token, extra='x').status_code == 400

    def test_a_form_body_and_text_plain_are_400(self, world):
        settings, client = world
        rows, token = seeded(settings)

        form = client.post(URL, data={'section': 'newznab', 'column': 'api_key', 'row': '0', 'token': token},
                           headers=OWN)
        plain = client.post(URL, content='{}', headers={**OWN, 'content-type': 'text/plain'})

        assert form.status_code == 400
        assert plain.status_code == 400

    @pytest.mark.parametrize('row', [True, False, 1.0, 0.5, '1', '0', None, [0], {'a': 0}])
    def test_a_row_that_is_not_a_json_integer_is_refused_without_a_value(self, world, row):
        settings, client = world
        rows, token = seeded(settings)

        response = reveal(client, row=row, token=token)

        assert response.status_code == 400
        refused_without_value(response, *KEYS)

    @pytest.mark.parametrize('field, value', [('section', 5), ('column', ['api_key']), ('token', 5),
                                              ('token', None), ('section', None)])
    def test_a_name_or_token_that_is_not_a_string_is_400(self, world, field, value):
        settings, client = world
        rows, token = seeded(settings)
        body = {'section': 'newznab', 'column': 'api_key', 'row': 0, 'token': token, field: value}

        assert client.post(URL, json=body, headers=OWN).status_code == 400


class TestWhatItReturns:
    def test_exactly_the_stored_text_including_surrounding_spaces_in_a_middle_cell(self, world):
        settings, client = world
        rows, token = seeded(settings)

        replies = [reveal(client, row=row, token=token).json() for row in range(3)]

        assert replies == [{'success': True, 'value': key} for key in KEYS]
        assert replies[1]['value'] == ' placeholder key one '

    def test_a_non_ascii_key_comes_back_byte_for_byte(self, world):
        settings, client = world
        rows, token = seeded(settings, keys=['placeholder-a', NON_ASCII, 'placeholder-c'])

        assert reveal(client, row=1, token=token).json() == {'success': True, 'value': NON_ASCII}

    def test_two_rows_differing_only_in_the_key_each_return_their_own(self, world):
        settings, client = world
        rows = keyed_rows(settings, ['placeholder-x', 'placeholder-y'])
        rows[1] = dict(rows[0], api_key='placeholder-y')
        assert settings.save_group('newznab', rows)['success']
        token = token_of(settings)

        assert reveal(client, row=0, token=token).json()['value'] == 'placeholder-x'
        assert reveal(client, row=1, token=token).json()['value'] == 'placeholder-y'

    def test_an_empty_cell_is_an_empty_string_that_is_not_a_refusal(self, world):
        settings, client = world
        rows, token = seeded(settings, keys=['placeholder-a', '', 'placeholder-c'])

        response = reveal(client, row=1, token=token)

        assert response.status_code == 200
        assert response.json() == {'success': True, 'value': ''}

    def test_the_other_group_works_the_same_way(self, world):
        settings, client = world
        rows, token = seeded(settings, keys=['placeholder-pk-0', 'placeholder-pk-1'], section='torrentpotato',
                             column='pass_key')

        assert reveal(client, section='torrentpotato', column='pass_key', row=1, token=token).json() == {
            'success': True, 'value': 'placeholder-pk-1'}

    def test_the_reply_is_the_one_cell_and_nothing_else(self, world):
        settings, client = world
        rows, token = seeded(settings)

        reply = reveal(client, row=2, token=token).json()

        assert set(reply) == {'success', 'value'}
        assert KEYS[0] not in repr(reply)
        assert token not in repr(reply)

    def test_a_reveal_writes_nothing_moves_no_token_and_holds_nothing(self, world):
        settings, client = world
        rows, token = seeded(settings)
        before = (sha(settings.file), os.stat(settings.file).st_mtime_ns, dict(settings._hold._entries))

        for row in range(3):
            reveal(client, row=row, token=token)

        assert (sha(settings.file), os.stat(settings.file).st_mtime_ns, dict(settings._hold._entries)) == before
        assert token_of(settings) == token

    def test_it_never_reads_the_hold_for_an_empty_cell(self, world):
        settings, client = world
        rows, token = seeded(settings, keys=['placeholder-a', '', 'placeholder-c'])
        settings._hold.add('newznab', 'api_key', token, 1, 'held-secret-text')

        response = reveal(client, row=1, token=token)

        assert response.json() == {'success': True, 'value': ''}
        assert 'held-secret-text' not in response.text

    def test_a_token_from_before_any_write_to_the_group_is_stale(self, world):
        settings, client = world
        rows, token = seeded(settings)
        changed = with_forms(rows, {0: keep(0), 1: keep(1), 2: keep(2)})
        changed[0]['custom_tag'] = 'moved'
        assert settings.save_group('newznab', changed, token)['success']

        response = reveal(client, row=0, token=token)

        assert response.status_code == 200
        assert response.json()['invalid'] == [{'row': None, 'column': None, 'reason': 'stale'}]
        refused_without_value(response, *KEYS)

    def test_another_groups_token_is_stale_for_a_reveal(self, world):
        settings, client = world
        rows, token = seeded(settings)
        other = seeded(settings, keys=['placeholder-pk-0'], section='torrentpotato', column='pass_key')[1]

        response = reveal(client, row=0, token=other)

        assert response.json()['invalid'][0]['reason'] == 'stale'
        refused_without_value(response, *KEYS)

    def test_a_forged_token_is_refused_without_a_value(self, world):
        settings, client = world
        seeded(settings)

        refused_without_value(reveal(client, token='0' * 64), *KEYS)
        refused_without_value(reveal(client, token=''), *KEYS)


class TestWhatIsRefusedWithNoValue:
    CANARY = 'canary-stored-credential-do-not-return'

    def test_a_column_that_is_not_a_declared_secret_is_refused(self, world):
        settings, client = world
        rows, token = seeded(settings)
        pairs = [('newznab', 'host'), ('newznab', 'use'), ('newznab', 'custom_tag'),
                 ('newznab', 'extra_score'), ('newznab', 'pass_key'),
                 ('torrentpotato', 'api_key'), ('torrentpotato', 'host'),
                 ('imdb', 'automation_urls'), ('newznab', 'API_KEY'), ('newznab', 'api_key '),
                 ('newznab', ''), ('newznab', 'nope')]

        for section, column in pairs:
            response = reveal(client, section=section, column=column, token=token)
            refused_without_value(response, *KEYS)
            assert response.json()['invalid'][0]['reason'] in ('bad_reference', 'unknown_section'), (
                section, column)

    @pytest.mark.parametrize('section, column', [
        ('core', 'password'), ('core', 'api_key'), ('torrentpotato', 'jackett_api_key'),
        ('core', 'username'), ('newznab', 'enabled'), ('nosuchsection', 'api_key'), ('', 'api_key')])
    def test_other_credentials_and_unregistered_names_are_refused(self, world, section, column):
        settings, client = world
        rows, token = seeded(settings)
        settings.addSection('core')
        settings.set('core', 'password', self.CANARY)
        settings.set('core', 'api_key', self.CANARY)
        settings.addSection('torrentpotato')
        settings.set('torrentpotato', 'jackett_api_key', self.CANARY)

        response = reveal(client, section=section, column=column, token=token)

        refused_without_value(response, self.CANARY, *KEYS)

    @pytest.mark.parametrize('row', [-1, 3, 4, 99, 10 ** 19, -10 ** 19, 2 ** 70])
    def test_a_negative_or_out_of_range_row_is_refused_without_a_value_and_without_a_500(self, world, row):
        settings, client = world
        rows, token = seeded(settings)

        response = reveal(client, row=row, token=token)

        assert response.status_code == 200
        assert response.json()['invalid'][0]['reason'] == 'bad_reference'
        refused_without_value(response, *KEYS)

    def test_minus_one_does_not_return_the_last_row_and_true_does_not_return_row_one(self, world):
        settings, client = world
        rows, token = seeded(settings)

        assert KEYS[2].strip() not in reveal(client, row=-1, token=token).text
        assert KEYS[1].strip() not in reveal(client, row=True, token=token).text

    def test_a_cell_index_is_checked_against_the_secret_columns_own_count(self, tmp_path, monkeypatch):
        stored = {'newznab': {'use': '1,1,1', 'host': 'https://h0.invalid,https://h1.invalid,https://h2.invalid',
                              'api_key': 'placeholder-k0,placeholder-k1', 'extra_score': '0,0,0',
                              'custom_tag': ',,'}}
        with world_with(tmp_path, monkeypatch) as (settings, client):
            settings.set('newznab', 'use', stored['newznab']['use'])
            settings.set('newznab', 'host', stored['newznab']['host'])
            settings.set('newznab', 'api_key', stored['newznab']['api_key'])
            settings.set('newznab', 'extra_score', stored['newznab']['extra_score'])
            settings.set('newznab', 'custom_tag', stored['newznab']['custom_tag'])
            settings.save()
            assert settings.group_misaligned('newznab') is True
            token = token_of(settings)

            assert reveal(client, row=0, token=token).json()['value'] == 'placeholder-k0'
            assert reveal(client, row=1, token=token).json()['value'] == 'placeholder-k1'
            refused_without_value(reveal(client, row=2, token=token), 'placeholder-k')


class TestLogging:
    def infos(self, logs):
        return [r.getMessage().split('] ', 1)[-1] for r in logs.records if r.levelno == logging.INFO]

    def test_one_info_line_per_successful_reveal_naming_section_column_and_row_only(self, world):
        settings, client = world
        rows, token = seeded(settings)

        with LogCapture() as logs:
            reveal(client, row=1, token=token)

        lines = [m for m in self.infos(logs) if m.startswith('Revealed')]
        assert lines == ['Revealed a stored key: section=newznab column=api_key row=1']
        assert all(key.strip() not in logs.text() for key in KEYS)
        assert token not in logs.text()

    def test_a_refused_reveal_logs_one_warning_with_the_reason_and_never_a_value(self, world):
        settings, client = world
        rows, token = seeded(settings)

        with LogCapture() as logs:
            reveal(client, row=7, token=token)
            reveal(client, row=0, token='0' * 64)

        warnings = [r.getMessage().split('] ', 1)[-1] for r in logs.at_or_above(logging.WARNING)]
        assert warnings == ['Refused a settings reveal: section=newznab reason=bad_reference',
                            'Refused a settings reveal: section=newznab reason=stale']
        assert not [m for m in self.infos(logs) if m.startswith('Revealed')]
        assert all(key.strip() not in logs.text() for key in KEYS)

    def test_an_unregistered_section_or_column_is_logged_as_a_placeholder_and_cannot_forge_a_line(self, world):
        settings, client = world
        rows, token = seeded(settings)

        with LogCapture() as logs:
            reveal(client, section='evil\nINFO forged line', column='x\ny', token=token)
            reveal(client, column='col\nforged', token=token)

        text = logs.text()
        assert 'forged' not in text
        assert 'unregistered' in text
        assert not any('\n' in r.getMessage() for r in logs.at_or_above(logging.WARNING))

    def test_a_handler_that_raises_returns_the_generic_error_and_logs_the_type_only(self, world, monkeypatch):
        settings, client = world
        rows, token = seeded(settings)

        def explode(self, section):
            raise RuntimeError('canary-stored-text-or-token')

        monkeypatch.setattr(settings_module.Settings, 'group_cells', explode)

        with LogCapture() as logs:
            response = reveal(client, token=token)

        assert response.json() == {'success': False,
                                   'error': 'The settings could not be read. Nothing was revealed.'}
        assert 'canary-stored-text-or-token' not in logs.text() + response.text
        assert 'RuntimeError' in logs.text()
        assert 'Could not reveal a stored key: section=newznab column=api_key (RuntimeError).' in logs.text()
        assert token not in logs.text()


class TestThePerColumnSaveStillRefusesASecretColumn:
    @pytest.mark.parametrize('value', ['{"keep": 0}', '{"restore": {"token": "x", "row": 0}}',
                                       'new-key', '', 'x' * 40])
    def test_a_form_encoded_save_of_a_secret_column_is_refused_whatever_the_value(self, world, value):
        settings, client = world
        rows, token = seeded(settings)
        before = sha(settings.file)

        response = client.post('/api/%s/settings.save' % API_KEY, data={
            'section': 'newznab', 'name': 'api_key', 'value': value}, headers=OWN)

        assert response.json()['success'] is False
        assert 'saved together with the rest of its group' in response.json()['error']
        assert sha(settings.file) == before

    @pytest.mark.parametrize('value', [{'keep': 0}, {'restore': {'token': 'x', 'row': 0}}, ['a'], 5])
    def test_a_json_save_of_a_secret_column_with_a_structured_value_is_refused(self, world, value):
        settings, client = world
        rows, token = seeded(settings)
        before = sha(settings.file)

        response = client.post('/api/%s/settings.save' % API_KEY, json={
            'section': 'newznab', 'name': 'api_key', 'value': value}, headers=OWN)

        assert response.json()['success'] is False
        assert sha(settings.file) == before
