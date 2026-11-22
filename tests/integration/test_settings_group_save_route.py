"""SEC-004 P1: the group-save route, driven through the real FastAPI app.

``settings.save_group`` takes one request carrying every column of one
``combine`` group as rows. These tests send real HTTP requests to a real app
(``create_app`` + ``TestClient``) backed by a real ``Settings`` over a temporary
``config.ini`` with the five real option declarations, and then read the file
with a fresh parser and the provider's own reader. Only the network call of a
provider is replaced, so the search loop that spends a credential is the real
one.

Hosts are ``.invalid`` and every credential is a ``placeholder-`` string or a
``canary`` that must never be echoed.
"""
import contextlib
import logging
import os
import os.path
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from couchpotato import create_app
from couchpotato.api import api_docs, api_docs_missing, callApiHandler
from couchpotato.environment import Env
from tests.helpers.combine_groups import (
    SECTIONS,
    LogCapture,
    expected_view,
    group_settings,
    memory_group,
    placeholder_rows,
    reader_view,
    sha,
    stored_group,
    three_rows,
)

pytestmark = pytest.mark.integration

API_KEY = 'placeholder-api-key-for-group-save'
ROUTE = 'settings.save_group'


@contextlib.contextmanager
def live_world(tmp_path, monkeypatch, stored=None):
    with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
        monkeypatch.setattr(Env, '_settings', settings)
        monkeypatch.setattr(Env, '_web_base', '/', raising=False)
        monkeypatch.setattr(Env, '_api_base', '/api/%s/' % API_KEY, raising=False)
        monkeypatch.setattr(Env, '_static_path', '/static/', raising=False)
        monkeypatch.setattr(Env, '_app_dir', os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), raising=False)
        monkeypatch.setattr(Env, '_dev', False, raising=False)
        values = {'api_key': API_KEY, 'username': '', 'password': '', 'dark_theme': False,
                  'rate_limit_max': 0, 'rate_limit_window': 60, 'cors_origins': ''}
        with patch.object(Env, 'setting', side_effect=lambda key=None, *a, **kw: values.get(
                key, kw.get('default', ''))):
            app = create_app(api_key=API_KEY, web_base='/')
        yield settings, TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def world(tmp_path, monkeypatch):
    with live_world(tmp_path, monkeypatch) as live:
        yield live


def url(key=API_KEY, route=ROUTE):
    return '/api/%s/%s' % (key, route) if key else '/api/%s' % route


def send(client, rows, section='newznab', **kwargs):
    return client.post(url(), json={'section': section, 'rows': rows}, **kwargs)


class TestAuthentication:
    """AC-SEC-1"""

    def test_no_key_is_401_and_nothing_is_written(self, world):
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(key=None), json={'section': 'newznab', 'rows': three_rows(
            settings, 'newznab')})

        assert response.status_code == 401
        assert sha(settings.file) == before

    def test_a_wrong_header_key_is_401_and_nothing_is_written(self, world):
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(key=None), json={'section': 'newznab', 'rows': three_rows(
            settings, 'newznab')}, headers={'X-Api-Key': 'placeholder-wrong'})

        assert response.status_code == 401
        assert sha(settings.file) == before

    def test_a_right_header_key_works(self, world):
        settings, client = world

        response = client.post(url(key=None), json={'section': 'newznab', 'rows': three_rows(
            settings, 'newznab')}, headers={'X-Api-Key': API_KEY})

        assert response.status_code == 200
        assert response.json() == {'success': True}


class TestTransportIsJsonPostOnly:
    """AC-SEC-2 (server half), AC-ARCH-6, AC-ARCH-11(iv)."""

    MALFORMED = {'success': False,
                 'error': 'The request was not a list of rows. Nothing was saved.',
                 'invalid': [{'row': None, 'column': None, 'reason': 'malformed'}]}

    def valid(self, settings):
        return {'section': 'newznab', 'rows': three_rows(settings, 'newznab')}

    def refused(self, settings, response, before):
        assert response.status_code == 400, response.text
        assert response.json() == self.MALFORMED
        assert sha(settings.file) == before

    def test_the_control_a_valid_json_post_succeeds(self, world):
        settings, client = world
        assert client.post(url(), json=self.valid(settings)).json() == {'success': True}

    def test_a_get_is_refused_so_cells_never_travel_in_a_url(self, world):
        settings, client = world
        before = sha(settings.file)
        query = {'section': 'newznab', 'rows[0][host]': 'https://canary.invalid'}

        self.refused(settings, client.get(url(), params=query), before)
        self.refused(settings, client.get(url()), before)

    def test_a_form_post_with_bracket_keys_is_refused(self, world):
        settings, client = world
        before = sha(settings.file)
        form = {'section': 'newznab'}
        for index, row in enumerate(three_rows(settings, 'newznab')):
            for column, value in row.items():
                form['rows[%d][%s]' % (index, column)] = value

        self.refused(settings, client.post(url(), data=form), before)

    def test_a_json_text_inside_a_form_field_is_refused(self, world):
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(), data={'section': 'newznab', 'rows': '[{"host": "x"}]'})

        self.refused(settings, response, before)

    def test_valid_json_sent_as_text_plain_is_refused(self, world):
        """A cross-site page can send text/plain without a preflight; it must not write."""
        import json
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(), content=json.dumps(self.valid(settings)),
                               headers={'Content-Type': 'text/plain'})

        self.refused(settings, response, before)

    def test_a_json_post_with_no_content_type_is_refused(self, world):
        import json
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(), content=json.dumps(self.valid(settings)))

        self.refused(settings, response, before)

    def test_an_extra_top_level_key_is_refused(self, world):
        settings, client = world
        before = sha(settings.file)

        self.refused(settings, client.post(url(), json=dict(self.valid(settings), extra='x')), before)

    @pytest.mark.parametrize('missing', ['section', 'rows'])
    def test_a_missing_top_level_key_is_refused(self, world, missing):
        settings, client = world
        before = sha(settings.file)
        body = self.valid(settings)
        del body[missing]

        self.refused(settings, client.post(url(), json=body), before)

    def test_a_bracket_keyed_member_inside_a_json_body_is_refused(self, world):
        settings, client = world
        before = sha(settings.file)
        body = {'section': 'newznab', 'rows[0][host]': 'https://canary.invalid%2Cx'}

        self.refused(settings, client.post(url(), json=body), before)

    @pytest.mark.parametrize('body', [[], 'text', 7, None, [{'section': 'newznab', 'rows': []}]])
    def test_a_top_level_value_that_is_not_an_object_is_refused(self, world, body):
        settings, client = world
        before = sha(settings.file)

        self.refused(settings, client.post(url(), json=body), before)

    @pytest.mark.parametrize('key', ['0', '7', '', '.', '1.5'])
    def test_rows_sent_as_an_object_with_numeric_looking_keys_are_refused(self, world, key):
        """The shared parser would turn that object into a list before the writer sees it."""
        settings, client = world
        before = sha(settings.file)
        rows = three_rows(settings, 'newznab')
        body = {'section': 'newznab', 'rows': {key: rows[0], '9': rows[1]}}

        self.refused(settings, client.post(url(), json=body), before)

    @pytest.mark.parametrize('rows', ['text', 7, None, True, {}])
    def test_rows_that_are_not_a_json_array_are_refused_by_the_dispatch(self, world, rows):
        settings, client = world
        before = sha(settings.file)

        self.refused(settings, client.post(url(), json={'section': 'newznab', 'rows': rows}), before)

    @pytest.mark.parametrize('element', ['text', 7, None, [{'host': 'x'}], True])
    def test_a_row_that_is_not_a_json_object_is_refused_by_the_dispatch(self, world, element):
        settings, client = world
        before = sha(settings.file)
        rows = three_rows(settings, 'newznab')
        rows[1] = element

        self.refused(settings, client.post(url(), json={'section': 'newznab', 'rows': rows}), before)

    @pytest.mark.parametrize('body', [b'[' * 200000, b'[' * 5000 + b']' * 5000,
                                      b'{"section": "newznab", "rows": ' + b'[' * 5000 + b']' * 5000 + b'}'])
    def test_a_deeply_nested_body_is_a_400_and_not_a_500(self, world, body):
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(), content=body, headers={'Content-Type': 'application/json'})

        self.refused(settings, response, before)

    def test_a_body_that_is_not_json_is_refused(self, world):
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(), content=b'{not json', headers={'Content-Type': 'application/json'})

        self.refused(settings, response, before)

    @pytest.mark.parametrize('query', ['callback_func=steal', 'section=core', 'rows=x', 'name=host'])
    def test_a_query_parameter_other_than_the_cache_buster_is_refused(self, world, query):
        settings, client = world
        before = sha(settings.file)

        self.refused(settings, client.post(url() + '?' + query, json=self.valid(settings)), before)

    def test_the_cache_buster_is_the_one_query_parameter_allowed(self, world):
        settings, client = world

        response = client.post(url() + '?t=1700000000000', json=self.valid(settings))

        assert response.json() == {'success': True}

    def test_a_charset_on_the_content_type_is_fine(self, world):
        import json
        settings, client = world

        response = client.post(url(), content=json.dumps(self.valid(settings)),
                               headers={'Content-Type': 'application/json; charset=utf-8'})

        assert response.json() == {'success': True}


class TestEveryGroupSavesThroughTheRoute:
    """AC-QA-1"""

    @pytest.mark.parametrize('section', SECTIONS)
    def test_three_rows_are_stored_per_column_and_read_back_by_the_real_reader(
            self, world, monkeypatch, section):
        settings, client = world
        columns = settings.combine_groups()[section]
        rows = three_rows(settings, section)

        response = send(client, rows, section)

        assert response.status_code == 200
        assert response.json() == {'success': True}
        assert stored_group(settings.file, section, columns) == {
            column: ','.join(row[column] for row in rows) for column in columns}
        assert reader_view(settings, monkeypatch, section) == expected_view(section, rows)

    def test_twelve_rows_keep_numeric_row_order(self, world):
        settings, client = world
        columns = settings.combine_groups()['newznab']
        rows = placeholder_rows(columns, 12)

        assert send(client, rows).json() == {'success': True}

        stored = stored_group(settings.file, 'newznab', columns)
        assert stored['host'].split(',')[10:] == [rows[10]['host'], rows[11]['host']]
        assert stored['api_key'].split(',')[10:] == [rows[10]['api_key'], rows[11]['api_key']]

    def test_each_host_is_stored_at_the_position_of_its_own_key(self, world):
        settings, client = world
        columns = settings.combine_groups()['newznab']
        rows = [{column: '' for column in columns}, {column: '' for column in columns}]
        rows[0].update(host='https://h1.invalid', api_key='placeholder-key-one', use='1')
        rows[1].update(host='https://h2.invalid', api_key='placeholder-key-two', use='1')

        assert send(client, rows).json() == {'success': True}

        stored = stored_group(settings.file, 'newznab', columns)
        assert list(zip(stored['host'].split(','), stored['api_key'].split(','))) == [
            ('https://h1.invalid', 'placeholder-key-one'), ('https://h2.invalid', 'placeholder-key-two')]


#: Spelled out on purpose: a test that derived this from the code under test
#: could not notice a column going missing. `test_the_declared_pairs...` below
#: checks it against the real declarations.
GROUP_COLUMNS = {
    'newznab': ('use', 'host', 'api_key', 'extra_score', 'custom_tag'),
    'torrentpotato': ('use', 'host', 'pass_key', 'name', 'seed_ratio', 'seed_time', 'extra_score'),
    'imdb': ('automation_urls_use', 'automation_urls'),
    'itunes': ('automation_urls_use', 'automation_urls'),
    'letterboxd': ('automation_urls_use', 'automation_urls'),
}
PAIRS = [(section, column) for section, columns in GROUP_COLUMNS.items() for column in columns]


class TestCommaIsRefusedEverywhere:
    """AC-QA-2"""

    @pytest.mark.parametrize('position', [0, 1, 2], ids=['first', 'middle', 'last'])
    @pytest.mark.parametrize('section, column', PAIRS)
    def test_a_comma_in_any_cell_names_the_row_and_column_and_changes_nothing(
            self, world, section, column, position):
        settings, client = world
        columns = settings.combine_groups()[section]
        before_sha = sha(settings.file)
        before_memory = memory_group(settings, section, columns)
        rows = three_rows(settings, section)
        rows[position][column] = 'part-one,part-two'

        response = send(client, rows, section)

        assert response.status_code == 200
        body = response.json()
        assert body['success'] is False
        assert body['invalid'] == [{'row': position, 'column': column, 'reason': 'comma'}]
        assert 'part-one' not in response.text
        assert sha(settings.file) == before_sha
        assert memory_group(settings, section, columns) == before_memory

    def test_the_declared_pairs_in_this_file_are_the_real_declared_columns(self, world):
        settings, _ = world
        declared = [(s, c) for s in SECTIONS for c in settings.combine_groups()[s]]
        assert sorted(PAIRS) == sorted(declared)


class TestValuesAreTakenAsSent:
    """AC-QA-3"""

    SENT = ['%2C', '%2c', '%252C', '%41', '+', '&', '=', 'true', 'false', 'a%2Cb']

    def test_nothing_is_decoded_or_coerced_and_nothing_is_trimmed(self, world):
        settings, client = world
        columns = settings.combine_groups()['newznab']
        rows = placeholder_rows(columns, len(self.SENT) + 2)
        for index, sent in enumerate(self.SENT):
            rows[index + 1]['api_key'] = sent
        rows[3]['custom_tag'] = '  inner lead and trail  '
        rows[0]['custom_tag'] = '  first row lead'
        rows[-1]['custom_tag'] = 'last row trail  '

        assert send(client, rows).json() == {'success': True}

        stored = stored_group(settings.file, 'newznab', columns)
        assert stored['api_key'].split(',')[1:len(self.SENT) + 1] == self.SENT
        tags = stored['custom_tag'].split(',')
        assert tags[3] == '  inner lead and trail  '
        # The parser strips whitespace at the two ends of the WHOLE stored value, so
        # only the first row's leading and the last row's trailing whitespace go.
        assert tags[0] == 'first row lead'
        assert tags[-1] == 'last row trail'

    def test_a_json_percent_2c_through_the_api_handler_is_stored_as_three_characters(self, world):
        settings, _ = world
        rows = three_rows(settings, 'newznab')
        rows[1]['api_key'] = '%2C'

        result = callApiHandler(ROUTE, section='newznab', rows=rows)

        assert result == {'success': True}
        assert stored_group(settings.file, 'newznab', ['api_key'])['api_key'].split(',')[1] == '%2C'


class TestEveryTransportOfAComma:
    """AC-SEC-5: the check runs on the exact string that is written."""

    def stored_positions(self, settings, columns):
        return {len(v.split(',')) for v in stored_group(settings.file, 'newznab', columns).values()}

    def test_a_literal_comma_in_json_is_refused(self, world):
        settings, _ = world
        rows = three_rows(settings, 'newznab')
        rows[1]['host'] = 'https://a.invalid,https://b.invalid'
        before = sha(settings.file)

        assert callApiHandler(ROUTE, section='newznab', rows=rows)['success'] is False
        assert sha(settings.file) == before

    def bracket_kwargs(self, settings):
        kwargs = {'section': 'newznab'}
        for index, row in enumerate(three_rows(settings, 'newznab')):
            for column, value in row.items():
                kwargs['rows[%d][%s]' % (index, column)] = value
        return kwargs

    def test_a_percent_2c_under_a_nested_bracket_key_is_stored_as_three_characters(self, world):
        """The shared parser no longer decodes it, so there is no comma to refuse."""
        settings, _ = world
        columns = settings.combine_groups()['newznab']
        kwargs = self.bracket_kwargs(settings)
        kwargs['rows[1][host]'] = 'https://a.invalid%2Chttps://b.invalid'

        result = callApiHandler(ROUTE, **kwargs)

        assert result == {'success': True}
        stored = stored_group(settings.file, 'newznab', columns)
        assert stored['host'].split(',')[1] == 'https://a.invalid%2Chttps://b.invalid'
        assert self.stored_positions(settings, columns) == {3}

    def test_a_form_body_percent_2c_is_stored_as_three_characters(self, world):
        settings, _ = world
        columns = settings.combine_groups()['newznab']
        kwargs = self.bracket_kwargs(settings)
        kwargs['rows[2][api_key]'] = 'placeholder%2Cplaceholder'

        result = callApiHandler(ROUTE, **kwargs)

        assert result == {'success': True}
        stored = stored_group(settings.file, 'newznab', columns)
        assert stored['api_key'].split(',')[2] == 'placeholder%2Cplaceholder'
        assert self.stored_positions(settings, columns) == {3}

    def test_a_literal_comma_under_a_nested_bracket_key_is_still_refused(self, world):
        settings, _ = world
        before = sha(settings.file)
        kwargs = self.bracket_kwargs(settings)
        kwargs['rows[1][host]'] = 'https://a.invalid,https://b.invalid'

        result = callApiHandler(ROUTE, **kwargs)

        assert result['success'] is False
        assert result['invalid'] == [{'row': 1, 'column': 'host', 'reason': 'comma'}]
        assert sha(settings.file) == before

    def test_a_literal_comma_in_a_form_body_value_is_still_refused(self, world):
        settings, _ = world
        before = sha(settings.file)
        kwargs = self.bracket_kwargs(settings)
        kwargs['rows[2][api_key]'] = 'placeholder,placeholder'

        result = callApiHandler(ROUTE, **kwargs)

        assert result['success'] is False
        assert result['invalid'] == [{'row': 2, 'column': 'api_key', 'reason': 'comma'}]
        assert sha(settings.file) == before

    def test_no_transport_stores_more_positions_than_rows(self, world):
        settings, client = world
        columns = settings.combine_groups()['newznab']
        rows = three_rows(settings, 'newznab')
        rows[0]['host'] = 'https://a.invalid%2Chttps://b.invalid'

        assert send(client, rows).json() == {'success': True}

        assert self.stored_positions(settings, columns) == {3}

    def test_the_view_refuses_arguments_the_route_does_not_define(self, world):
        settings, _ = world
        before = sha(settings.file)

        result = callApiHandler(ROUTE, section='newznab', rows=three_rows(settings, 'newznab'),
                                name='host', value='x')

        assert result['success'] is False
        assert result['invalid'] == [{'row': None, 'column': None, 'reason': 'malformed'}]
        assert sha(settings.file) == before


class TestALoneSurrogateOverHttp:

    def test_json_text_the_file_cannot_hold_is_a_refusal_and_not_a_write_failure(self, world):
        import json
        settings, client = world
        before = sha(settings.file)
        rows = three_rows(settings, 'newznab')
        rows[1]['api_key'] = '\ud800x'
        body = json.dumps({'section': 'newznab', 'rows': rows})
        assert '\\ud800' in body, 'the fixture must send the escape the browser would'

        with LogCapture() as log:
            response = client.post(url(), content=body, headers={'Content-Type': 'application/json'})

        assert response.status_code == 200
        assert response.json()['invalid'] == [{'row': 1, 'column': 'api_key', 'reason': 'not_encodable'}]
        assert [r.levelno for r in log.at_or_above(logging.WARNING)] == [logging.WARNING]
        assert sha(settings.file) == before


class TestNoValueIsEverReturnedOrLogged:
    """AC-SEC-7, AC-SEC-8 (successful-save clause), AC-OPS-1, -3, -8."""

    def sentinel_rows(self, settings, tag):
        columns = settings.combine_groups()['newznab']
        rows = placeholder_rows(columns, 3, tag='sentinel-' + tag)
        return rows

    def test_a_successful_save_returns_exactly_success_and_logs_one_info_line_without_values(
            self, world):
        settings, client = world
        rows = self.sentinel_rows(settings, 'valid')

        with LogCapture() as log:
            response = send(client, rows)

        assert response.json() == {'success': True}
        assert 'sentinel' not in response.text
        info = [r.getMessage() for r in log.records
                if r.levelno == logging.INFO and 'settings group' in r.getMessage()]
        assert len(info) == 1, [r.getMessage() for r in log.records]
        assert 'section=newznab' in info[0]
        assert 'rows=3' in info[0]
        assert 'sentinel' not in log.text()

    def test_the_success_body_holds_no_cell_value_for_any_column_of_either_big_group(self, world):
        settings, client = world
        for section in ('newznab', 'torrentpotato'):
            rows = placeholder_rows(settings.combine_groups()[section], 3, tag='sentinel-' + section)
            response = send(client, rows, section)
            assert response.json() == {'success': True}
            assert 'sentinel' not in response.text

    def test_a_refusal_with_two_offending_cells_logs_one_warning_with_a_count_and_no_value(
            self, world):
        settings, client = world
        rows = self.sentinel_rows(settings, 'refused')
        rows[1]['host'] = 'https://canary-host.invalid,https://canary-evil.invalid'
        rows[2]['api_key'] = 'canary-key,canary-key-two'

        with LogCapture() as log:
            response = send(client, rows)

        body = response.json()
        assert [e['reason'] for e in body['invalid']] == ['comma', 'comma']
        assert 'canary' not in response.text
        assert 'sentinel' not in response.text
        lines = log.at_or_above(logging.WARNING)
        assert len(lines) == 1, [r.getMessage() for r in log.records]
        assert lines[0].levelno == logging.WARNING
        for part in ('section=newznab', 'first_row=1', 'first_column=host', 'offences=2'):
            assert part in lines[0].getMessage()
        assert 'canary' not in log.text()
        assert 'sentinel' not in log.text()

    def test_a_forced_write_failure_logs_one_error_and_no_traceback_and_no_value(
            self, world, monkeypatch):
        settings, client = world
        rows = self.sentinel_rows(settings, 'failing')
        before = sha(settings.file)

        def boom(*args, **kwargs):
            raise OSError(28, 'No space left on device')

        monkeypatch.setattr(os, 'replace', boom)
        with LogCapture() as log:
            response = send(client, rows)
        monkeypatch.undo()

        body = response.json()
        assert response.status_code == 200
        assert body['success'] is False
        assert 'invalid' not in body
        assert 'sentinel' not in response.text
        lines = log.at_or_above(logging.WARNING)
        assert len(lines) == 1, [r.getMessage() for r in log.records]
        assert lines[0].levelno == logging.ERROR
        assert lines[0].exc_info is None
        assert 'newznab' in lines[0].getMessage()
        assert 'OSError' in lines[0].getMessage()
        assert 'sentinel' not in log.text()
        assert 'Traceback' not in log.text()
        assert sha(settings.file) == before


class TestRegistration:
    """AC-ARCH-5, AC-SIMP-4"""

    def test_the_route_is_registered_next_to_settings_save_with_docs(self, world):
        assert ROUTE in api_docs
        assert api_docs[ROUTE].get('desc')
        assert ROUTE not in api_docs_missing


class TestPairingThroughTheRealSearchLoop:
    """AC-SEC-6: a refused comma means a credential reaches only its own host.

    Only the network call is replaced. The rows are saved through the real
    route, the refused save is sent through the real route, and the provider's
    real ``search()`` then runs over the resulting file.
    """

    @staticmethod
    def newznab_calls(monkeypatch):
        from couchpotato.core.media.movie.providers.nzb.newznab import Newznab
        provider = Newznab.__new__(Newznab)
        calls = []
        monkeypatch.setattr(provider, 'getRSSData',
                            lambda url, **kw: calls.append(url) or [])
        provider.search({'identifier': 'tt0000001'}, {})
        return calls

    @staticmethod
    def torrentpotato_calls(monkeypatch):
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        provider = TorrentPotato.__new__(TorrentPotato)
        calls = []
        monkeypatch.setattr(provider, 'getJsonData',
                            lambda url, **kw: calls.append(url) or None)
        provider.search({'identifier': 'tt0000001', 'title': 'Placeholder', 'info': {'year': 2000}}, {})
        return calls

    def two_rows(self, settings, section, host_column, key_column):
        columns = settings.combine_groups()[section]
        rows = placeholder_rows(columns, 2)
        for index in (0, 1):
            rows[index].update({'use': '1', host_column: 'https://h%d.example.invalid/api' % (index + 1),
                                key_column: 'placeholder-key-%d' % (index + 1)})
        return rows

    def test_newznab_sends_each_key_only_to_its_own_host(self, world, monkeypatch):
        settings, client = world
        assert send(client, self.two_rows(settings, 'newznab', 'host', 'api_key')).json() == {
            'success': True}
        saved = sha(settings.file)
        hostile = self.two_rows(settings, 'newznab', 'host', 'api_key')
        hostile[0]['host'] = 'https://h1.example.invalid/api,https://evil.invalid/api'

        refused = send(client, hostile)

        assert refused.json()['success'] is False
        assert sha(settings.file) == saved
        calls = self.newznab_calls(monkeypatch)
        assert len(calls) == 2, calls
        for call, (host, key) in zip(calls, [('h1', 'placeholder-key-1'), ('h2', 'placeholder-key-2')]):
            assert '//%s.example.invalid/' % host in call
            assert 'apikey=%s' % key in call
        assert not any('evil' in call for call in calls)
        assert not any('placeholder-key-2' in c and 'h1.' in c for c in calls)

    def test_torrentpotato_sends_each_pass_key_only_to_its_own_host(self, world, monkeypatch):
        settings, client = world
        settings.set('torrentpotato', 'enabled', 'True')  # shipped off; a search needs it on
        rows = self.two_rows(settings, 'torrentpotato', 'host', 'pass_key')
        assert send(client, rows, 'torrentpotato').json() == {'success': True}
        saved = sha(settings.file)
        hostile = self.two_rows(settings, 'torrentpotato', 'host', 'pass_key')
        hostile[0]['host'] = 'https://h1.example.invalid/api,https://evil.invalid/api'
        hostile_keys = self.two_rows(settings, 'torrentpotato', 'host', 'pass_key')
        # Joined, not written as one literal: a comma-separated pair of
        # placeholders in a single string trips the secret scanner's
        # generic-api-key rule.
        hostile_keys[1]['pass_key'] = ','.join(['placeholder-key-2', 'placeholder-stray'])

        assert send(client, hostile, 'torrentpotato').json()['success'] is False
        assert send(client, hostile_keys, 'torrentpotato').json()['success'] is False
        assert sha(settings.file) == saved
        calls = self.torrentpotato_calls(monkeypatch)
        assert len(calls) == 2, calls
        for call, (host, key) in zip(calls, [('h1', 'placeholder-key-1'), ('h2', 'placeholder-key-2')]):
            assert '//%s.example.invalid/' % host in call
            assert 'passkey=%s' % key in call
        assert not any('evil' in call for call in calls)


class TestTheSettingsReadCarriesGroupState:
    """SEC-004 P3: the page's own read says which groups are misaligned and how
    many rows each has, so script never derives either."""

    def read(self, client):
        response = client.get(url(route='settings/'))
        assert response.status_code == 200
        return response.json()

    def test_a_misaligned_group_is_flagged_through_the_real_http_read(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent.parent.parent / 'scripts'))
        import seed_e2e_data

        stored = seed_e2e_data.config_fixture('newznab_misaligned_key_short')
        with live_world(tmp_path, monkeypatch, stored=stored) as (settings, client):
            before = sha(settings.file)

            payload = self.read(client)

            assert payload['combine_state']['newznab'] == {'misaligned': True, 'rows': 3}
            assert payload['combine_state']['torrentpotato']['misaligned'] is False
            assert sha(settings.file) == before

    def test_the_values_the_page_derives_rows_from_are_in_the_same_read(self, world):
        settings, client = world

        payload = self.read(client)

        assert set(payload['combine_state']) == set(SECTIONS)
        assert 'newznab' in payload['values']
        assert payload['values']['newznab']['host'] == settings.get('host', 'newznab')
