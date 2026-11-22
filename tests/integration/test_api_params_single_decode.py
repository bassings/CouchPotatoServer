"""API parameters reach a handler decoded once, by the framework, and never again.

`getParams` used to run `unquote` over every string it was handed, after the web
framework had already decoded the query string and the form body (and a JSON
body was never encoded). These tests send real HTTP requests to a real app and
read what the handler received (an echo route registered for the test), what
`settings.save` stored (read back with a fresh parser), and what the login form
accepts.

Values are placeholders; hosts are `.invalid`.
"""
from urllib.parse import quote

import pytest

from couchpotato.api import addApiView
from couchpotato.core.helpers.variable import check_password, md5
from couchpotato.core.softchroot import SoftChroot
from couchpotato.environment import Env
from tests.helpers.jackett_binding import BINDING_OPTION, KEY_OPTION, SECTION, URL_OPTION, on_disk
from tests.integration.test_settings_group_save_route import live_world, url

pytestmark = pytest.mark.integration

ECHO = 'test.echo_params'
SAVE = 'settings.save'

#: Text that is already decoded by the time a handler sees it.
DELIVERED = [
    'a%41b',
    'p%25w',
    '%2C',
    '%2c',
    '%252C',
    '%FF',
    '100%',
    'a+b',
    'a&b=c',
    'jack%C3%A9tt',
    'jackétt',
]
TRANSPORTS = ('query', 'form', 'json')


@pytest.fixture
def world(tmp_path, monkeypatch):
    with live_world(tmp_path, monkeypatch) as live:
        # `live_world` restores the registry on exit, so this does not leak.
        addApiView(ECHO, lambda **kwargs: {'success': True, 'got': kwargs})
        yield live


def send(client, route, fields, transport):
    if transport == 'json':
        return client.post(url(route=route), json=fields)
    if transport == 'query':
        return client.get(url(route=route), params=fields)
    return client.post(url(route=route), data=fields)


@pytest.fixture
def core_world(tmp_path, monkeypatch):
    from couchpotato.core._base import _core
    from couchpotato.core._base._core import Core
    with live_world(tmp_path, monkeypatch) as (settings, client):
        for entry in _core.config:
            settings.addOptions(entry['name'], entry)
            options = {o['name']: o for g in entry['groups'] for o in g['options']}
            settings.registerDefaults(entry['name'], options)
        Core()
        monkeypatch.setattr('couchpotato.rotate_session_secret', lambda *a, **k: 'secret')
        yield settings, client


@pytest.mark.parametrize('transport', TRANSPORTS)
@pytest.mark.parametrize('value', DELIVERED)
class TestAValueReachesTheHandlerAsSent:
    """AC-1, through the real route."""

    def test_a_flat_value(self, world, value, transport):
        _, client = world

        got = send(client, ECHO, {'v': value}, transport).json()['got']

        assert got == {'v': value}

    def test_a_nested_bracket_key_value(self, world, value, transport):
        _, client = world

        got = send(client, ECHO, {'rows[0][host]': value}, transport).json()['got']

        assert got == {'rows': [{'host': value}]}


class TestOneDecodeRemains:
    """AC-3: the framework's own decode is the one that stays."""

    def test_a_query_string_encoded_once_arrives_decoded_once(self, world):
        _, client = world

        got = client.get(url(route=ECHO) + '?path=%2Ftmp%2Fa%20b&v=a%2541b').json()['got']

        assert got == {'path': '/tmp/a b', 'v': 'a%41b'}

    def test_a_form_body_encoded_once_arrives_decoded_once(self, world):
        _, client = world

        got = client.post(
            url(route=ECHO), content=b'path=%2Ftmp%2Fa%20b&v=a%2541b&w=a+b',
            headers={'content-type': 'application/x-www-form-urlencoded'}).json()['got']

        assert got == {'path': '/tmp/a b', 'v': 'a%41b', 'w': 'a b'}

    def test_a_real_directory_list_of_an_encoded_path_is_handled_as_the_decoded_path(
            self, world, tmp_path, monkeypatch):
        from couchpotato.core.plugins.browser import FileBrowser
        _, client = world
        spaced = tmp_path / 'a b'
        (spaced / 'inner').mkdir(parents=True)
        # No soft chroot configured: initialised and disabled, the default install.
        disabled = SoftChroot()
        disabled.initialize('')
        monkeypatch.setattr(Env, '_softchroot', disabled)
        FileBrowser()

        body = client.get(url(route='directory.list') + '?path=' + quote(str(spaced) + '/', safe='')
                          ).json()

        assert body['dirs'] == [str(spaced / 'inner') + '/'], body


class TestSettingsSaveStoresExactlyWhatWasSent:
    """AC-2: a plain option and a `password` option, by every transport."""

    SENT = ['placeholder-pa%41ss', 'placeholder-p%25w', 'placeholder-%FF-end']

    @pytest.mark.parametrize('transport', TRANSPORTS)
    @pytest.mark.parametrize('sent', SENT)
    def test_a_plain_option(self, core_world, transport, sent):
        settings, client = core_world

        response = send(client, SAVE, {'section': 'core', 'name': 'proxy_server', 'value': sent},
                        transport)

        assert response.json()['success'] is True
        assert on_disk(settings, 'proxy_server', 'core') == sent
        assert settings.p.get('core', 'proxy_server') == sent

    @pytest.mark.parametrize('transport', TRANSPORTS)
    @pytest.mark.parametrize('sent', SENT)
    def test_a_password_type_option(self, core_world, transport, sent):
        settings, client = core_world

        response = send(client, SAVE, {'section': 'core', 'name': 'proxy_password', 'value': sent},
                        transport)

        assert response.json()['success'] is True
        assert on_disk(settings, 'proxy_password', 'core') == sent


class TestAJackettAddressTypedPercentEncoded:
    """AC-6: the spelling that could not be saved as typed before."""

    ADDRESS = 'http://h.invalid:9117/jack%C3%A9tt'

    @pytest.mark.parametrize('transport', TRANSPORTS)
    def test_it_is_stored_as_typed_and_a_key_saved_after_it_is_bound_to_it(
            self, tmp_path, monkeypatch, transport):
        from tests.helpers.jackett_binding import jackett_world
        with jackett_world(tmp_path, monkeypatch) as (settings, client, _provider):
            first = send(client, SAVE, {'section': SECTION, 'name': URL_OPTION, 'value': self.ADDRESS},
                         transport)
            second = send(client, SAVE, {'section': SECTION, 'name': KEY_OPTION,
                                         'value': 'placeholder-jackett-key-one'}, transport)

            assert first.json()['success'] is True
            assert second.json()['success'] is True
            assert on_disk(settings, URL_OPTION) == self.ADDRESS
            assert on_disk(settings, BINDING_OPTION) == self.ADDRESS


class TestALoginPasswordWithPercentText:
    """AC-7: a password containing `%41` saved through the UI must log in as typed."""

    TYPED = 'placeholder-pa%41ss'

    @pytest.mark.parametrize('transport', TRANSPORTS)
    def test_the_stored_hash_matches_the_typed_text(self, core_world, transport):
        settings, client = core_world

        response = send(client, SAVE, {'section': 'core', 'name': 'password', 'value': self.TYPED},
                        transport)

        assert response.json()['success'] is True
        assert check_password(md5(self.TYPED), settings.p.get('core', 'password'))

    def test_the_login_form_accepts_the_typed_text(self, core_world):
        from tests.unit.session_helper import stored_session_secret
        settings, client = core_world
        send(client, SAVE, {'section': 'core', 'name': 'password', 'value': self.TYPED}, 'form')

        with stored_session_secret():
            response = client.post('/login/', data={'username': '', 'password': self.TYPED},
                                   follow_redirects=False)

        assert 'user' in response.cookies, response.status_code
