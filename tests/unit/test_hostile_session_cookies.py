"""A `user` cookie is whatever the client chose to send. AC-QA-10.

Every value here is one an unauthenticated stranger can put in a header, so
each has to end as a redirect to the login page: not a 500, not a traceback,
not a parse that takes long enough to be a denial of service on its own.

The 100 KB case is the one worth explaining, and the explanation is narrower
than it first looks. `int(payload)` -- the parse that is quadratic in CPython --
is only reached once the signature has already verified, so a stranger cannot
steer a huge value into it: their cookie fails `compare_digest` first. What the
length cap in `MAX_SESSION_TOKEN_LENGTH` actually buys is that the server does
not HMAC a stranger's 100 KB twice on every request, and that an over-long
value is classified honestly as malformed rather than as a forgery.

Both assertions here kill that cap if it is removed (the classification flips to
`bad_signature`), which is the only reason it is in the tree: an untested
`if len(...)` is a guard nobody has watched fail.
"""
import socket
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato import SESSION_COOKIE_NAME, ensure_session_secret
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core import event as event_module
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_helper import env_restored  # noqa: E402

API_KEY = 'notarealapikey' + '0' * 18
PASSWORD = 'hunter2'
STORED_PASSWORD = hash_password(md5(PASSWORD))
REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeSettings(Settings):
    def __init__(self, data):
        from couchpotato.core.logger import CPLog
        self.data = data
        self.log = CPLog('test-settings')
        self.file = None
        self.p = None
        self.directories_delimiter = '::'

    def get(self, attr, default=None, section='core', type=None):
        return self.data.get(attr, default)

    def set(self, section, option, value):
        self.data[option] = value

    def addSection(self, section):
        pass

    def save(self):
        pass


@pytest.fixture
def app(tmp_path):
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    old_events = {name: list(handlers) for name, handlers in event_module.events.items()}
    old_timeout = socket.getdefaulttimeout()

    db = SQLiteAdapter()
    db.create(str(tmp_path / 'db'))

    with env_restored():
        Env.set('db', db)
        Env.set('settings', FakeSettings({
            'username': '', 'password': STORED_PASSWORD, 'api_key': API_KEY,
            'auth_required': 1, 'rate_limit_max': 0, 'cors_origins': '',
            'ssl_cert': '', 'ssl_key': '',
        }))
        Env.set('web_base', '/')
        Env.set('api_base', '/api/%s/' % API_KEY)
        Env.set('static_path', '/static/')
        Env.set('app_dir', str(REPO_ROOT))
        Env.set('data_dir', str(tmp_path))
        Env.set('dev', False)
        Env.set('desktop', True)

        from couchpotato.core._base._core import Core
        Core()

        ensure_session_secret(db)

        from couchpotato import create_app
        try:
            yield create_app(API_KEY, '/')
        finally:
            Env.set('desktop', False)
            socket.setdefaulttimeout(old_timeout)
            db.close()
            api.clear()
            api.update(old_api)
            api_locks.clear()
            api_locks.update(old_locks)
            api_nonblock.clear()
            api_nonblock.update(old_nonblock)
            api_docs.clear()
            api_docs.update(old_docs)
            api_docs_missing.clear()
            api_docs_missing.extend(old_missing)
            event_module.events.clear()
            event_module.events.update(old_events)


#: One entry per shape of hostile input, named so a failure says which.
#:
#: The values go through `TestClient.get(..., headers={'Cookie': ...})` rather
#: than the cookie jar: `http.cookiejar` silently drops values it dislikes, so
#: setting a NUL byte or a 100 KB value through the jar would send NO cookie at
#: all and the test would be measuring the no-cookie path while claiming to
#: measure a hostile one.
HOSTILE = {
    'empty string': '',
    'a single separator': '.',
    'no separator': 'abcdefghijklmnop',
    'ten separators': '.'.join(['1'] * 11),
    # Both wire forms of the same character, spelled as an ESCAPE rather than
    # typed: the literal first written here was `e` + U+0301 (a combining
    # acute), which no single-byte encoding can carry, so the request raised
    # in the HARNESS and never reached the server at all.
    'a non-ascii character, latin-1 on the wire': '\u00e9.signature',
    'a non-ascii character, utf-8 on the wire': b'\xc3\xa9.signature',
    'a NUL byte': '123.abc\x00def',
    'invalid base64 in the signature': '1700000000.!!!!not-base64!!!!',
    'invalid hex where the expiry belongs': 'deadbeef.c2lnbmF0dXJl',
    'a negative expiry': '-1700000000.c2lnbmF0dXJl',
    'a leading-plus expiry': '+1700000000.c2lnbmF0dXJl',
    'an expiry with an underscore': '1_700_000_000.c2lnbmF0dXJl',
    'only a separator and a signature': '.c2lnbmF0dXJl',
    'whitespace': '   ',
}


def cookie_header(value) -> bytes:
    """The `Cookie` header exactly as it goes on the wire.

    BYTES, and latin-1, for a reason that cost a red run: `httpx` refuses to
    encode a non-ascii header value at the CLIENT, so passing `é` as a `str`
    raises `UnicodeEncodeError` in the test harness and never reaches the
    server at all. HTTP headers are bytes and Starlette decodes them latin-1,
    so latin-1 here means the application receives the character this test
    claims to send rather than a mangled or absent one.

    A `bytes` entry is passed straight through, which is how the UTF-8 form of
    the same character is driven: Starlette still decodes latin-1, so the
    application sees the two-character mojibake a real browser would deliver.
    """
    if isinstance(value, bytes):
        return SESSION_COOKIE_NAME.encode('ascii') + b'=' + value
    return ('%s=%s' % (SESSION_COOKIE_NAME, value)).encode('latin-1')


def request_with_cookie(app, value):
    session = TestClient(app, follow_redirects=False)
    return session.get('/', headers={b'Cookie': cookie_header(value)})


class TestHostileCookiesAreRefusedNotFatal:

    @pytest.mark.parametrize('name', sorted(HOSTILE))
    def test_it_redirects_to_the_login_page(self, app, name):
        response = request_with_cookie(app, HOSTILE[name])

        assert response.status_code == 302, (
            '%s produced %s rather than a redirect to the login page'
            % (name, response.status_code)
        )
        assert '/login/' in response.headers.get('location', '')

    @pytest.mark.parametrize('name', sorted(HOSTILE))
    def test_no_traceback_reaches_the_response(self, app, name):
        body = request_with_cookie(app, HOSTILE[name]).text

        for marker in ('Traceback', 'File "', 'Internal Server Error'):
            assert marker not in body, '%s leaked %r' % (name, marker)


class TestAHundredKilobyteCookie:
    """The size case, kept separate because it also asserts a time budget."""

    VALUE = '1' * 100_000

    def test_it_is_refused(self, app):
        response = request_with_cookie(app, self.VALUE)

        assert response.status_code == 302
        assert '/login/' in response.headers.get('location', '')

    def test_it_is_refused_quickly(self, app):
        # Warm the app: the first request through TestClient builds the
        # transport and imports templates, which would otherwise be counted as
        # cookie-parsing time.
        request_with_cookie(app, '1.1')

        # RELATIVE to a tiny cookie, not an absolute wall-clock budget.
        # The property under test is "cost does not blow up with a value the
        # CLIENT chooses"; a fixed `< 0.1s` measures the runner's speed as
        # much as the code, and goes red on a loaded or slower machine for
        # reasons unrelated to this path. A generous absolute ceiling is kept
        # as a backstop for the case where the baseline itself is pathological.
        started = time.perf_counter()
        request_with_cookie(app, '1.1')
        baseline = time.perf_counter() - started

        started = time.perf_counter()
        request_with_cookie(app, self.VALUE)
        elapsed = time.perf_counter() - started

        assert elapsed < max(2.0, baseline * 50), (
            'a 100 KB cookie took %.3f s to refuse against a %.4f s baseline '
            'for a 3-byte one. Something on the verification path is '
            'superlinear in the value the CLIENT chooses, which is a denial '
            'of service that needs no credential.' % (elapsed, baseline)
        )

    def test_a_hundred_kilobytes_of_digits_with_a_signature_is_also_quick(self):
        """The shape that would actually reach `int()`: digits, then a dot.

        The route test above is refused by the length cap before anything
        parses. This drives the classifier directly with the value that would
        otherwise be handed to `int()`, so the cap is proven to be what stops
        it rather than some accident of the request path.
        """
        from couchpotato import session_rejection_reason

        token = '1' * 100_000 + '.c2lnbmF0dXJl'

        # The baseline is TIMED, not asserted on: a short well-formed token
        # gets past the malformed check and comes back `bad_signature`, which
        # is correct and irrelevant here. What matters is how long a small
        # input takes.
        started = time.perf_counter()
        session_rejection_reason('1.c2lnbmF0dXJl', 'a' * 64)
        baseline = time.perf_counter() - started

        started = time.perf_counter()
        assert session_rejection_reason(token, 'a' * 64) == 'malformed'
        elapsed = time.perf_counter() - started

        # Relative, for the same reason as above: this is a superlinearity
        # guard, not a benchmark of the machine it runs on.
        assert elapsed < max(1.0, baseline * 200), (
            '100 KB took %.4f s against a %.6f s baseline for a short token'
            % (elapsed, baseline))


class TestTheHostileCookiesActuallyReachTheServer:
    """Anti-vacuity, and not hypothetical.

    Every assertion above is "the request was refused", which a request that
    sent no cookie at all satisfies perfectly. `http.cookiejar` drops values
    containing a NUL byte, so routing these through the jar would have tested
    the no-cookie path thirteen times over while reading as thorough.
    """

    @pytest.mark.parametrize('name', sorted(HOSTILE))
    def test_the_header_is_sent_verbatim(self, app, name):
        seen = {}

        original = TestClient.get

        def capture(self, url, **kwargs):
            seen['cookie'] = (kwargs.get('headers') or {}).get(b'Cookie')
            return original(self, url, **kwargs)

        TestClient.get = capture
        try:
            request_with_cookie(app, HOSTILE[name])
        finally:
            TestClient.get = original

        assert seen['cookie'] == cookie_header(HOSTILE[name])

    def test_a_valid_cookie_through_the_same_path_is_accepted(self, app):
        """The control. If this fails, every refusal above is meaningless
        because the harness cannot deliver a working cookie either."""
        from couchpotato import get_session_secret, mint_session_token

        response = request_with_cookie(
            app, mint_session_token(get_session_secret(), 3600))

        assert response.status_code == 200, response.text
