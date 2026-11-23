"""The settings read is not available as JSONP (FIX-2026-11-23).

`GET /api/<key>/settings?callback_func=f` used to answer `f({...})` as
`text/javascript`, which a `<script src>` on any origin can run. The reply holds
every stored setting, so a page that knew the API key could read them. These
tests drive the real app and the real `Settings.view` over a temporary
`config.ini`; the only wrapper is a counter around the registered handler, which
still calls the real one. Values are placeholders and hosts are `.invalid`.
"""
import pytest

from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from tests.integration.test_settings_group_save_route import API_KEY, live_world, url

pytestmark = pytest.mark.integration

SENTINEL = 'placeholder-sentinel-key'
SENTINEL_HOST = 'https://sentinel-host.invalid'
STORED = {'newznab': {'api_key': SENTINEL, 'host': SENTINEL_HOST}}
SAME_ORIGIN = 'http://testserver'
ORIGINS = {'none': None, 'same-origin': SAME_ORIGIN, 'foreign': 'http://evil.invalid'}
REFUSAL = {'success': False, 'error': 'JSONP is not available for this route'}


REGISTRIES = (api, api_locks, api_nonblock, api_docs)


@pytest.fixture(scope='module', autouse=True)
def registry_is_left_as_found():
    """A route a test registers (`test.jsonp_other`) must not outlive the module.

    `group_settings`, which `live_world` builds on, restores the registries on
    teardown; this makes that a checked fact rather than an assumption.
    """
    before = [dict(registry) for registry in REGISTRIES]
    missing_before = list(api_docs_missing)
    yield
    assert [dict(registry) for registry in REGISTRIES] == before
    assert api_docs_missing == missing_before


@pytest.fixture
def world(tmp_path, monkeypatch):
    with live_world(tmp_path, monkeypatch, stored=STORED) as live:
        yield live


@pytest.fixture
def view_calls(world):
    """Count calls to the registered `settings` handler, which is still the real one."""
    real = api['settings']
    calls = []

    def counting(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    api['settings'] = counting
    try:
        yield calls
    finally:
        api['settings'] = real


def headers_for(origin):
    return {} if origin is None else {'Origin': origin}


def send(client, transport, origin, callback='steal'):
    headers = headers_for(origin)
    path = url(route='settings')
    if transport == 'query':
        return client.get(path, params={'callback_func': callback}, headers=headers)
    if transport == 'form':
        return client.post(path, data={'callback_func': callback}, headers=headers)
    return client.post(path, json={'callback_func': callback}, headers=headers)


def assert_refused_and_silent(response):
    assert response.status_code == 400, response.text[:200]
    assert response.headers['content-type'].startswith('application/json')
    assert not response.headers['content-type'].startswith('text/javascript')
    assert response.json() == REFUSAL
    everything = response.text + repr(dict(response.headers))
    assert SENTINEL not in everything
    assert SENTINEL_HOST not in everything


@pytest.mark.parametrize('transport', ['query', 'form', 'json'])
@pytest.mark.parametrize('origin', list(ORIGINS))
class TestSettingsReadRefusesJsonp:
    def test_refused_with_no_setting_value_in_the_reply(self, world, transport, origin):
        _, client = world
        assert_refused_and_silent(send(client, transport, ORIGINS[origin]))

    def test_the_handler_is_not_called(self, world, view_calls, transport, origin):
        _, client = world
        send(client, transport, ORIGINS[origin])
        assert view_calls == []


class TestControls:
    """The fixture really holds the sentinel, so the refusal above is not vacuous."""

    def test_plain_read_is_unchanged_and_holds_the_sentinel(self, world, view_calls):
        _, client = world
        response = client.get(url(route='settings'))
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('application/json')
        assert set(response.json()) >= {'options', 'values', 'combine_state'}
        assert SENTINEL in response.text
        assert len(view_calls) == 1

    def test_plain_read_with_the_cache_buster_is_unchanged(self, world):
        _, client = world
        response = client.get(url(route='settings'), params={'t': '1700000000000'})
        assert response.status_code == 200
        assert SENTINEL in response.text

    def test_an_empty_callback_is_not_a_jsonp_request(self, world):
        _, client = world
        response = client.get(url(route='settings'), params={'callback_func': ''})
        assert response.status_code == 200
        assert SENTINEL in response.text

    def test_the_header_key_route_is_refused_too(self, world, view_calls):
        _, client = world
        response = client.get('/api/settings', params={'callback_func': 'steal'},
                              headers={'X-Api-Key': API_KEY})
        assert_refused_and_silent(response)
        assert view_calls == []

    def test_jsonp_on_another_route_still_works(self, world):
        _, client = world
        from couchpotato.api import addApiView
        addApiView('test.jsonp_other', lambda **kw: {'data': 1})
        response = client.get(url(route='test.jsonp_other'), params={'callback_func': 'myFunc'})
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/javascript')
        assert response.text.startswith('myFunc(')

    def test_an_invalid_callback_on_another_route_is_still_refused_as_before(self, world):
        _, client = world
        from couchpotato.api import addApiView
        addApiView('test.jsonp_other', lambda **kw: {'data': 1})
        response = client.get(url(route='test.jsonp_other'), params={'callback_func': 'a b'})
        assert response.status_code == 400
        assert response.json() == {'success': False, 'error': 'Invalid callback'}


class TestRefusalIsLogged:
    def test_one_warning_naming_the_route_only(self, world, caplog):
        _, client = world
        with caplog.at_level('WARNING'):
            send(client, 'query', 'http://evil.invalid', callback='steal-callback-name')
        records = [r for r in caplog.records if 'JSONP' in r.getMessage()]
        assert len(records) == 1
        assert records[0].levelname == 'WARNING'
        text = records[0].getMessage()
        assert 'settings' in text
        for secret in ('evil.invalid', 'steal-callback-name', API_KEY, SENTINEL):
            assert secret not in text
