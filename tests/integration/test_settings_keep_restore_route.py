"""SEC-006 P1b, D9: a save that carries a non-text cell is refused when it is cross-origin.

`settings.save_group` accepts `{"keep": i}` and `{"restore": {...}}` cells only with a
token. A page in a browser on another origin, an origin listed in `cors_origins`
included, must not be able to keep, restore or move a stored key, so a save whose
parsed body carries any non-string member in any row is refused 403 when
`_cross_origin_post(request)` is true. All-string saves are unchanged, and a request
with neither Origin nor Referer (a script) is not refused by this rule.

The real app (`create_app` with the real CORS middleware) over a real `Settings` and a
temporary `config.ini`. Hostile probes first prove the CORS preflight for their header
set succeeds, so they are requests a browser could really send. Placeholder values and
`.invalid` hosts only.
"""
import contextlib
import json
import logging
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from couchpotato import create_app
from couchpotato.environment import Env
from tests.helpers.combine_groups import LogCapture, group_settings, sha, stored_group
from tests.unit.test_settings_keep_restore import KEYS, keep, keyed_rows, restore, seeded, token_of, with_forms

pytestmark = pytest.mark.integration

API_KEY = 'placeholder-api-key-for-keep-restore'
LISTED = 'http://dash.invalid'
URL = '/api/%s/settings.save_group' % API_KEY
REFUSED = {'success': False, 'error': 'Cross-origin request refused'}
OWN = {'origin': 'http://testserver'}
HOSTILE = {'origin': LISTED}
FORWARDED = {'origin': LISTED, 'x-forwarded-host': 'dash.invalid'}


@contextlib.contextmanager
def world_with(tmp_path, monkeypatch, cors=LISTED, **settings_values):
    with group_settings(tmp_path, monkeypatch) as settings:
        monkeypatch.setattr(Env, '_settings', settings)
        monkeypatch.setattr(Env, '_web_base', '/', raising=False)
        monkeypatch.setattr(Env, '_api_base', '/api/%s/' % API_KEY, raising=False)
        monkeypatch.setattr(Env, '_static_path', '/static/', raising=False)
        monkeypatch.setattr(Env, '_app_dir', os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), raising=False)
        monkeypatch.setattr(Env, '_dev', False, raising=False)
        values = {'api_key': API_KEY, 'username': '', 'password': '', 'dark_theme': False,
                  'rate_limit_max': 0, 'rate_limit_window': 60, 'cors_origins': cors, **settings_values}
        with patch.object(Env, 'setting', side_effect=lambda key=None, *a, **kw: values.get(
                key, kw.get('default', ''))):
            app = create_app(api_key=API_KEY, web_base='/')
        yield settings, TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def world(tmp_path, monkeypatch):
    with world_with(tmp_path, monkeypatch) as live:
        yield live


def preflight_allowed(client):
    response = client.options(URL, headers={
        'origin': LISTED, 'access-control-request-method': 'POST',
        'access-control-request-headers': 'content-type,x-forwarded-host'})
    assert response.status_code == 200, response.text
    assert response.headers.get('access-control-allow-origin') == LISTED


def post(client, settings, forms, token, headers=None, section_rows=None):
    rows = with_forms(section_rows if section_rows is not None else keyed_rows(settings), forms)
    return client.post(URL, json={'section': 'newznab', 'rows': rows, 'token': token}, headers=headers or {})


class TestAKeepFromAnotherOrigin:
    def test_a_keep_from_a_listed_origin_is_refused_403_and_nothing_is_written(self, world):
        settings, client = world
        rows, token = seeded(settings)
        before = sha(settings.file)
        preflight_allowed(client)

        response = post(client, settings, {0: keep(0), 1: keep(1), 2: keep(2)}, token, HOSTILE, rows)

        assert response.status_code == 403
        assert response.json() == REFUSED
        assert sha(settings.file) == before

    def test_the_same_body_from_the_servers_own_origin_is_accepted(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = post(client, settings, {0: keep(0), 1: keep(1), 2: keep(2)}, token, OWN, rows)

        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_a_keep_with_neither_origin_nor_referer_is_not_refused_by_this_rule(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = post(client, settings, {0: keep(0), 1: keep(1), 2: keep(2)}, token, None, rows)

        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_a_keep_from_a_listed_referer_is_refused(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = post(client, settings, {0: keep(0)}, token, {'referer': LISTED + '/page'}, rows)

        assert response.status_code == 403

    def test_a_keep_true_from_a_listed_origin_is_refused_here_and_not_passed_on(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = post(client, settings, {0: {'keep': True}}, token, HOSTILE, rows)

        assert response.status_code == 403
        assert response.json() == REFUSED

    def test_the_forwarded_host_regression_a_listed_origin_cannot_vouch_for_itself(self, world):
        settings, client = world
        rows, token = seeded(settings)
        before = sha(settings.file)
        preflight_allowed(client)

        response = post(client, settings, {0: keep(0)}, token, {**FORWARDED, 'host': 'cp.invalid:5050'}, rows)

        assert response.status_code == 403
        assert sha(settings.file) == before

    def test_an_unlisted_foreign_origin_is_refused_too(self, tmp_path, monkeypatch):
        with world_with(tmp_path, monkeypatch, cors='') as (settings, client):
            rows, token = seeded(settings)

            response = post(client, settings, {0: keep(0)}, token, {'origin': 'http://evil.invalid'}, rows)

            assert response.status_code == 403


class TestARestoreFromAnotherOrigin:
    def test_a_restore_from_a_listed_origin_is_refused_and_the_entry_is_still_restorable_after(self, world):
        settings, client = world
        rows, token = seeded(settings)
        removed = settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)
        sent = [rows[0], rows[1]]
        before = sha(settings.file)

        # A restore and nothing else non-text: the rule must not look for `keep` only.
        response = post(client, settings, {1: restore(token, 1)}, removed['token'], HOSTILE, sent)

        assert response.status_code == 403
        assert sha(settings.file) == before
        again = post(client, settings, {1: restore(token, 1)}, removed['token'], OWN, sent)
        assert again.json()['success'] is True
        # In memory byte for byte; a file read back strips whitespace at its very edges.
        assert settings._stored_text('newznab', 'api_key') == KEYS[0] + ',' + KEYS[1]


class TestAnyNonTextMemberOfAnyRowCounts:
    @pytest.mark.parametrize('member', [3, 1.5, True, None, ['x'], {'a': 1}])
    def test_a_non_string_member_in_any_column_from_a_listed_origin_is_refused(self, world, member):
        settings, client = world
        rows, token = seeded(settings)
        before = sha(settings.file)
        sent = with_forms(rows, {})
        sent[2]['host'] = member

        response = client.post(URL, json={'section': 'newznab', 'rows': sent}, headers=HOSTILE)

        assert response.status_code == 403
        assert sha(settings.file) == before

    def test_the_same_body_from_the_servers_own_origin_reaches_the_writer_and_is_refused_as_on_master(
            self, world):
        settings, client = world
        rows, token = seeded(settings)
        sent = with_forms(rows, {})
        sent[2]['host'] = 3

        response = client.post(URL, json={'section': 'newznab', 'rows': sent}, headers=OWN)

        assert response.status_code == 200
        assert response.json()['invalid'] == [{'row': 2, 'column': 'host', 'reason': 'not_string'}]

    def test_an_all_string_save_from_a_listed_origin_behaves_as_on_master(self, world):
        settings, client = world
        rows, token = seeded(settings)
        sent = keyed_rows(settings, tag='b')

        response = client.post(URL, json={'section': 'newznab', 'rows': sent}, headers=HOSTILE)

        assert response.status_code == 200
        assert response.json() == {'success': True}
        assert stored_group(settings.file, 'newznab', ['host'])['host'].startswith('https://placeholder-b-0')

    def test_an_all_string_save_with_a_token_from_a_listed_origin_is_unchanged(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = post(client, settings, {}, token, HOSTILE, keyed_rows(settings, tag='b'))

        assert response.status_code == 200
        assert response.json()['success'] is True

    def test_an_empty_row_object_has_no_member_and_is_left_to_the_writer(self, world):
        settings, client = world

        response = client.post(URL, json={'section': 'newznab', 'rows': [{}]}, headers=HOSTILE)

        assert response.status_code == 200
        assert response.json()['success'] is False


class TestTheRefusalIsLoggedOnceAndSafely:
    def test_one_warning_names_the_route_and_carries_no_cell_value_or_token(self, world):
        settings, client = world
        rows, token = seeded(settings)

        with LogCapture() as logs:
            post(client, settings, {0: keep(0), 1: restore('canary-reference-token', 1)}, token, HOSTILE, rows)

        warnings = [r.getMessage() for r in logs.at_or_above(logging.WARNING)]
        assert len(warnings) == 1
        assert 'settings.save_group' in warnings[0]
        text = logs.text()
        assert token not in text
        assert 'canary-reference-token' not in text
        assert not any(key.strip() in text for key in KEYS)


class TestTheBodyIsParsedOnce:
    def test_the_refusal_is_decided_on_the_object_the_strict_check_parsed(self, world):
        settings, client = world
        rows, token = seeded(settings)
        body = json.dumps({'section': 'newznab', 'rows': with_forms(rows, {0: keep(0)}), 'token': token}).encode()
        real = json.loads
        parses = []

        def counting(text, *args, **kwargs):
            if text == body:
                parses.append(1)
            return real(text, *args, **kwargs)

        with patch('json.loads', counting):
            response = client.post(URL, content=body, headers={**HOSTILE, 'content-type': 'application/json'})

        assert response.status_code == 403
        assert len(parses) == 1


class TestTheRealRouteCarriesKeepAndRestore:
    def test_a_keep_save_through_the_real_route_stores_the_key_and_replies_with_a_token(self, world):
        settings, client = world
        rows, token = seeded(settings)

        response = post(client, settings, {0: keep(2), 1: keep(0), 2: keep(1)}, token, OWN, rows)

        assert response.status_code == 200
        assert set(response.json()) == {'success', 'token'}
        assert settings._stored_text('newznab', 'api_key') == ','.join([KEYS[2], KEYS[0], KEYS[1]])
        assert response.json()['token'] == token_of(settings)

    def test_a_stale_refusal_carries_held_through_the_real_route(self, world):
        settings, client = world
        rows, token = seeded(settings)
        settings.save_group('newznab', with_forms(rows[:1], {0: keep(0)}), token)

        response = post(client, settings, {0: keep(0)}, token, OWN, rows)

        assert response.status_code == 200
        assert response.json()['held'] == [{'column': 'api_key', 'row': 1}, {'column': 'api_key', 'row': 2}]

    def test_a_forced_hold_failure_after_the_write_still_gives_the_accepted_reply(self, world, monkeypatch):
        from couchpotato.core import settings as settings_module
        settings, client = world
        rows, token = seeded(settings)
        monkeypatch.setattr(settings_module._RemovedKeyHold, 'add',
                            lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError('canary-held-text')))

        with LogCapture() as logs:
            response = post(client, settings, {0: keep(0)}, token, OWN, rows[:1])

        assert response.status_code == 200
        assert response.json()['success'] is True
        assert 'canary-held-text' not in logs.text() + response.text
        assert token not in logs.text()
