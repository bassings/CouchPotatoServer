"""SEC-006 P1a: the group token over the real HTTP route.

The strict-JSON entry for `settings.save_group` allows exactly `section` and
`rows`, and optionally `token` as a string. These tests send real requests to a
real app (`create_app` + `TestClient`) over a real `Settings` and a temporary
`config.ini`, and read the file back with a fresh parser.

Placeholder values only; hosts are `.invalid`.
"""
import json

import pytest

from tests.helpers.combine_groups import LogCapture, sha, three_rows
from tests.integration.test_settings_group_save_route import API_KEY, live_world, url  # noqa: F401

pytestmark = pytest.mark.integration

MALFORMED_REASON = 'malformed'


@pytest.fixture
def world(tmp_path, monkeypatch):
    with live_world(tmp_path, monkeypatch) as live:
        yield live


def read_token(client, section='newznab'):
    response = client.get(url(route='settings/'))
    assert response.status_code == 200
    return response.json()['combine_state'][section]['token']


def body(settings, token=None, section='newznab', tag='a'):
    payload = {'section': section, 'rows': three_rows(settings, section, tag=tag)}
    if token is not None:
        payload['token'] = token
    return payload


class TestTheReadCarriesTheToken:
    def test_the_settings_read_returns_a_token_for_each_credential_group(self, world):
        settings, client = world

        payload = client.get(url(route='settings/')).json()

        assert payload['combine_state']['newznab']['token'] == settings.combine_state()['newznab']['token']
        assert payload['combine_state']['torrentpotato']['token']
        assert 'token' not in payload['combine_state']['imdb']


class TestATokenBearingBody:
    def test_a_body_of_section_rows_and_token_is_accepted_and_written(self, world):
        settings, client = world

        response = client.post(url(), json=body(settings, read_token(client)))

        assert response.status_code == 200, response.text
        reply = response.json()
        assert reply['success'] is True
        assert set(reply) == {'success', 'token'}
        assert reply['token'] == read_token(client)
        assert settings.get('host', 'newznab').split(',')[0] == 'https://placeholder-a-0.invalid/path'

    def test_the_reply_token_lets_the_next_save_land_with_no_re_read(self, world):
        settings, client = world
        first = client.post(url(), json=body(settings, read_token(client))).json()

        second = client.post(url(), json=body(settings, first['token'], tag='b')).json()

        assert second['success'] is True
        assert settings.get('host', 'newznab').split(',')[0] == 'https://placeholder-b-0.invalid/path'

    def test_a_stale_token_is_refused_through_the_route_with_nothing_written(self, world):
        settings, client = world
        stale = read_token(client)
        assert client.post(url(), json=body(settings)).json() == {'success': True}
        before = sha(settings.file)

        response = client.post(url(), json=body(settings, stale, tag='z'))

        assert response.json()['success'] is False
        assert response.json()['invalid'] == [{'row': None, 'column': None, 'reason': 'stale'}]
        assert 'token' not in response.json()
        assert sha(settings.file) == before

    def test_a_save_with_no_token_replies_exactly_as_on_master(self, world):
        settings, client = world

        assert client.post(url(), json=body(settings)).json() == {'success': True}

    def test_the_token_is_in_no_log_record(self, world):
        settings, client = world
        with LogCapture() as logs:
            first = read_token(client)
            accepted = client.post(url(), json=body(settings, first)).json()
            # `first` is stale: the accepted save above changed the group.
            stale = client.post(url(), json=body(settings, first, tag='b')).json()
            assert stale['invalid'][0]['reason'] == 'stale'

        text = logs.text()
        assert 'reason=stale' in text
        assert first not in text
        assert accepted['token'] not in text
        assert settings._token_key.hex() not in text


class TestTheTransportStillRefusesEverythingElse:
    @pytest.mark.parametrize('token', [123, None, True, ['x'], {'a': 1}, 1.5])
    def test_a_token_that_is_not_a_string_is_a_400_with_nothing_written(self, world, token):
        settings, client = world
        before = sha(settings.file)
        payload = body(settings)
        payload['token'] = token

        response = client.post(url(), json=payload)

        assert response.status_code == 400
        assert response.json()['invalid'][0]['reason'] == MALFORMED_REASON
        assert sha(settings.file) == before

    @pytest.mark.parametrize('extra', ['keep', 'restore', 'tokens', 'Token', 'token '])
    def test_any_other_extra_key_is_still_a_400(self, world, extra):
        settings, client = world
        before = sha(settings.file)
        payload = body(settings, read_token(client))
        payload[extra] = 'x'

        response = client.post(url(), json=payload)

        assert response.status_code == 400
        assert sha(settings.file) == before

    def test_a_token_with_a_missing_section_or_rows_is_a_400(self, world):
        settings, client = world
        before = sha(settings.file)
        for missing in ('section', 'rows'):
            payload = body(settings, read_token(client))
            del payload[missing]
            assert client.post(url(), json=payload).status_code == 400
        assert sha(settings.file) == before

    def test_a_token_in_a_form_body_is_a_400(self, world):
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(), data={'section': 'newznab', 'token': read_token(client)})

        assert response.status_code == 400
        assert sha(settings.file) == before

    def test_a_token_in_the_query_string_is_a_400(self, world):
        settings, client = world
        before = sha(settings.file)

        response = client.post(url() + '?token=' + read_token(client), json=body(settings))

        assert response.status_code == 400
        assert sha(settings.file) == before

    def test_a_token_in_a_text_plain_body_is_a_400(self, world):
        settings, client = world
        before = sha(settings.file)

        response = client.post(url(), content=json.dumps(body(settings, read_token(client))),
                               headers={'Content-Type': 'text/plain'})

        assert response.status_code == 400
        assert sha(settings.file) == before

    def test_the_t_query_parameter_is_still_the_only_one_allowed(self, world):
        settings, client = world

        assert client.post(url() + '?t=1', json=body(settings)).status_code == 200
