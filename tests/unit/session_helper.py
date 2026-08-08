"""The ONE place a Python unit test mints an authenticated session.

AC-ARCH-14. Before this, three test files each constructed the session cookie
by hand -- and could, because the value was just `Env.setting('api_key')`. Now
it is a signed token, so a format change would otherwise have to be chased
through every file that hardcoded one, and the ones that were missed would fail
in a way that reads like a broken auth gate rather than a stale fixture.

Deliberately NOT a stub of `get_current_user` or `get_session_secret`: those
are the functions under test in most callers. Only the STORAGE is doubled
(`Env.prop`), so the production fail-closed logic, the constant-time
comparison, the expiry check and the ERROR path all still execute. The real
property-store round trip is driven end to end in
`tests/unit/test_session_secret_store.py`.
"""
from contextlib import contextmanager

from couchpotato import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    SESSION_SECRET_PROPERTY,
    mint_session_token,
)
from couchpotato.environment import Env

#: A fixed, obviously-fake secret. Shaped like the real thing (64 hex
#: characters = 32 bytes) so nothing accidentally depends on the generator, and
#: constant so a failing test is reproducible.
TEST_SESSION_SECRET = 'f3' * 32


def session_cookie(secret: str = TEST_SESSION_SECRET, lifetime: int = SESSION_LIFETIME,
                   now=None) -> str:
    """A valid `user` cookie value for `secret`."""
    return mint_session_token(secret, lifetime, now=now)


@contextmanager
def stored_session_secret(secret: str = TEST_SESSION_SECRET):
    """Put `secret` in the property store for the duration of the block."""
    original = Env.prop

    def fake_prop(identifier, value=None, default=None):
        if identifier == SESSION_SECRET_PROPERTY and value is None:
            return secret
        return original(identifier, value=value, default=default)

    Env.prop = staticmethod(fake_prop)
    try:
        yield secret
    finally:
        Env.prop = original


def authenticate(client, secret: str = TEST_SESSION_SECRET, **kwargs) -> str:
    """Give a `TestClient` a valid session cookie and return its value."""
    token = session_cookie(secret, **kwargs)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    return token
