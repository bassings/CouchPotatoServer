"""Auth is gated on an explicit setting, not inferred from two other fields.

`get_current_user` used to gate on `if username and password:` and return
`True` -- fully public -- otherwise. Driven directly, that gives:

    username='admin' password='secret'  -> denied without a cookie
    username=''      password='secret'  -> PUBLIC
    username='admin' password=''        -> PUBLIC
    username=''      password=''        -> PUBLIC

So an operator who set a password but left the username blank had a wide-open
server and no indication of it. The settings copy made that the likely
mistake rather than an unlikely one: "Leave empty to disable authentication"
sat on the **username** field, so the field that silently disabled auth was the
one whose own description promised it would.

The gate is now the explicit `auth_required` setting:

  - ON  -> a valid session cookie is required, whatever username/password hold.
  - OFF -> open, which is now a state someone chose rather than one they
           stumbled into.
  - A blank username means "any username is accepted", not "auth off".

The default is a plain `0` rather than a tri-state `None`. Spec-verified, and
worth restating because the tidy-looking version is broken: `registerDefaults`
materialises the literal `auth_required = None` into `config.ini` on first
boot, and `Env.setting`'s own default is `''`, so `Env.setting('auth_required',
type='bool')` reads falsy and auth stays OFF on every install, silently, with
no failing test and no log line. A one-shot startup migration writes an
explicit `1` when the key is absent and a password is set, so existing
password-protected installs stay protected and the value is greppable
afterwards -- which matters because grepping `config.ini` is the documented
lock-out recovery path.
"""
import types

import pytest

from couchpotato.environment import Env


@pytest.fixture
def settings():
    """Env.setting backed by a plain dict, restored afterwards."""
    data = {'api_key': 'THEKEY'}
    original = Env.setting

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            data[key] = kwargs['value']
            return
        return data.get(key, kwargs.get('default', ''))

    Env.setting = staticmethod(mock_setting)
    yield data
    Env.setting = original


def _request(cookie=None):
    return types.SimpleNamespace(cookies=({'user': cookie} if cookie else {}))


def _current_user(request):
    from couchpotato import get_current_user
    return get_current_user(request)


class TestAuthRequiredOn:
    """Six cases: both auth_required states across the credential combinations."""

    @pytest.mark.parametrize('username,password', [
        ('admin', 'secret'),
        ('', 'secret'),      # the trap: password set, username blank
        ('admin', ''),
        ('', ''),
    ])
    def test_no_cookie_is_denied(self, settings, username, password):
        settings.update({'username': username, 'password': password, 'auth_required': 1})

        assert _current_user(_request()) is None, (
            'auth_required is ON but a request with no session cookie was '
            'served (username=%r password=%r)' % (username, password)
        )

    def test_a_valid_cookie_is_accepted(self, settings):
        settings.update({'username': 'admin', 'password': 'secret', 'auth_required': 1})

        assert _current_user(_request('THEKEY')) == 'THEKEY'

    def test_a_wrong_cookie_is_denied(self, settings):
        settings.update({'username': 'admin', 'password': 'secret', 'auth_required': 1})

        assert _current_user(_request('not-the-key')) is None

    def test_a_blank_username_does_not_disable_auth(self, settings):
        """The whole point. This combination was PUBLIC before."""
        settings.update({'username': '', 'password': 'secret', 'auth_required': 1})

        assert _current_user(_request()) is None, (
            'a blank username disabled authentication even with auth_required '
            'ON -- the exact trap the old `if username and password` gate set'
        )
        assert _current_user(_request('THEKEY')) == 'THEKEY', (
            'a blank username must mean "any username is accepted", not '
            '"nobody can log in"'
        )


class TestAuthRequiredOff:
    """Open is a state someone chose, and it must actually be open."""

    @pytest.mark.parametrize('username,password', [
        ('admin', 'secret'),
        ('', 'secret'),
        ('', ''),
    ])
    def test_everything_is_public(self, settings, username, password):
        settings.update({'username': username, 'password': password, 'auth_required': 0})

        assert _current_user(_request()) is True


class TestTheDefault:

    def test_absent_auth_required_with_a_password_is_treated_as_ON(self, settings):
        """Existing password-protected installs must not fall open on upgrade.

        `auth_required` is absent from every config.ini written before this
        change. Reading it as falsy would silently unprotect exactly the
        installs that had bothered to set a password.
        """
        settings.update({'username': 'admin', 'password': 'secret'})
        settings.pop('auth_required', None)

        assert _current_user(_request()) is None, (
            'an upgraded install with a password set became PUBLIC because '
            'auth_required was absent'
        )

    def test_absent_auth_required_without_a_password_stays_open(self, settings):
        """An install with no password never had auth; do not lock it out."""
        settings.update({'username': '', 'password': ''})
        settings.pop('auth_required', None)

        assert _current_user(_request()) is True
