"""What the `Set-Cookie` header actually says. AC-SEC-39 / D4.

Asserted on the RAW header, not on `response.cookies`: httpx's jar normalises,
drops and re-renders attributes, so a cookie the jar happily stores can be one
a browser would refuse. The thing under test is the bytes on the wire.

`Secure` is the dangerous one, and it is dangerous in the direction people do
not expect. Setting it on a plain-HTTP deployment does not weaken anything --
it makes the cookie UNDELIVERABLE. The browser drops it, the redirect to `/`
bounces straight back to `/login/`, and the operator is locked out of their own
server by an upgrade, with no error message anywhere and nothing in the log.
This project's production instance is `http://homemedia.maeewing.com:5050`, and
the parent plan already has one near-miss of exactly that shape.

So D4: `Secure` if and only if THIS server terminates TLS itself, meaning both
`ssl_cert` and `ssl_key` are configured -- the same pair `runner.py` hands to
uvicorn. Never from `X-Forwarded-Proto`, never from `Host`, never from the
request URL scheme. All three are attacker-settable on a plain-HTTP LAN box,
which turns "correct cookie hardening" into a remote denial of service against
the owner's own login.

The plain-HTTP case therefore drives the FULL flow rather than reading a
header: POST /login/, follow the 302, land on `/` with 200 inside a bounded
number of hops. A cookie the client refuses to store shows up there as a login
loop. A header assertion alone would pass while the server was unusable.
"""
import os
from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato import SESSION_COOKIE_NAME, ensure_session_secret, mint_session_token
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

API_KEY = 'notarealapikey' + '0' * 18
REPO_ROOT = Path(__file__).resolve().parents[2]

PASSWORD = 'hunter2'
STORED_PASSWORD = hash_password(md5(PASSWORD))


class FakeSettings(Settings):
    """The REAL `getProperty` / `setProperty` over an in-memory config."""

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


def build(tmp_path, web_base='/', ssl_cert='', ssl_key=''):
    db = SQLiteAdapter()
    db.create(str(tmp_path / 'db'))

    settings = FakeSettings({
        'username': '',
        'password': STORED_PASSWORD,
        'api_key': API_KEY,
        'auth_required': 1,
        'rate_limit_max': 0,
        'cors_origins': '',
        'ssl_cert': ssl_cert,
        'ssl_key': ssl_key,
    })

    Env.set('db', db)
    Env.set('settings', settings)
    Env.set('web_base', web_base)
    Env.set('api_base', '%sapi/%s/' % (web_base, API_KEY))
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(REPO_ROOT))
    Env.set('data_dir', str(tmp_path))
    Env.set('dev', False)

    secret = ensure_session_secret(db)

    from couchpotato import create_app
    return db, settings, secret, create_app(API_KEY, web_base)


@pytest.fixture(autouse=True)
def clean_api_registry():
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    yield
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


def login_header(app, web_base='/', base_url='http://testserver'):
    """The raw `Set-Cookie` a real successful login emits."""
    client = TestClient(app, follow_redirects=False, base_url=base_url)
    response = client.post('%slogin/' % web_base,
                           data={'username': '', 'password': PASSWORD})
    assert response.status_code == 302, response.text
    header = response.headers.get('set-cookie')
    assert header, 'a successful login emitted no Set-Cookie header'
    return header


def attributes(header):
    """`{attribute: value}` for the session cookie, parsed as a browser would."""
    jar = SimpleCookie()
    jar.load(header)
    assert SESSION_COOKIE_NAME in jar, header
    return jar[SESSION_COOKIE_NAME]


class TestThePlainHttpDeploymentStaysReachable:
    """AC-SEC-39's first direction, and the one that can lock the owner out."""

    def test_the_cookie_is_not_marked_secure_when_this_server_serves_plain_http(self, tmp_path):
        _, _, _, app = build(tmp_path)

        header = login_header(app)

        assert 'secure' not in header.lower(), (
            'a Secure cookie on a plain-HTTP install is dropped by the browser, '
            'so the redirect to / bounces back to /login/ forever and the '
            'operator is locked out by an upgrade: %r' % header
        )

    def test_a_real_login_reaches_a_served_page_within_a_bounded_number_of_hops(self, tmp_path):
        """The assertion a header check cannot make.

        Driven with a REAL cookie jar, so an attribute the client refuses to
        store shows up here as a login loop instead of silently passing. The
        hop count is bounded: an unbounded `follow_redirects=True` would hide
        exactly the bounce this exists to catch behind httpx's own limit.
        """
        _, _, _, app = build(tmp_path)
        client = TestClient(app, follow_redirects=False)

        response = client.post('/login/', data={'username': '', 'password': PASSWORD})

        hops = 0
        while response.status_code in (301, 302, 303, 307, 308):
            hops += 1
            assert hops <= 3, 'login redirect loop: %s' % response.headers.get('location')
            response = client.get(response.headers['location'])

        assert response.status_code == 200, response.status_code
        assert response.request.url.path == '/', (
            'login landed on %s rather than the app root, which is what a '
            'cookie the client would not store looks like'
            % response.request.url.path
        )

    def test_an_https_looking_request_does_not_turn_secure_on(self, tmp_path):
        """D4's explicit prohibition, driven with the headers an attacker sends.

        `X-Forwarded-Proto`, `Host` and the URL scheme are all under the
        caller's control on a plain-HTTP LAN box. Deriving `Secure` from any of
        them means a stranger can make the owner's next login undeliverable by
        sending one header.
        """
        _, _, _, app = build(tmp_path)
        client = TestClient(app, follow_redirects=False)

        response = client.post(
            '/login/',
            data={'username': '', 'password': PASSWORD},
            headers={
                'X-Forwarded-Proto': 'https',
                'X-Forwarded-Ssl': 'on',
                'Host': 'couchpotato.example.com',
            },
        )

        assert 'secure' not in response.headers.get('set-cookie', '').lower()

    def test_a_request_over_https_still_does_not_turn_secure_on_by_itself(self, tmp_path):
        """The scheme is not the signal either; the configuration is.

        A TLS-terminating reverse proxy in front of a plain-HTTP CouchPotato is
        a normal deployment, and the app cannot tell it from an attacker
        claiming the same thing.
        """
        _, _, _, app = build(tmp_path)

        header = login_header(app, base_url='https://testserver')

        assert 'secure' not in header.lower()


class TestTlsTerminatedHereGetsASecureCookie:
    """AC-SEC-39's other direction, so the guard is not one-sided."""

    def test_the_cookie_is_secure_when_both_ssl_cert_and_ssl_key_are_set(self, tmp_path):
        _, _, _, app = build(tmp_path, ssl_cert='/etc/cp/cert.pem', ssl_key='/etc/cp/key.pem')

        header = login_header(app, base_url='https://testserver')

        assert attributes(header)['secure'], header

    @pytest.mark.parametrize('cert,key', [
        ('/etc/cp/cert.pem', ''),
        ('', '/etc/cp/key.pem'),
    ])
    def test_half_a_tls_configuration_is_not_tls(self, tmp_path, cert, key):
        """`runner.py` requires BOTH before it hands uvicorn any TLS at all.

        A half-configured pair therefore still serves plain HTTP, and a Secure
        cookie there is the lockout again.
        """
        _, _, _, app = build(tmp_path, ssl_cert=cert, ssl_key=key)

        assert 'secure' not in login_header(app).lower()


class TestTheRemainingAttributes:

    def test_the_cookie_is_httponly(self, tmp_path):
        _, _, _, app = build(tmp_path)

        assert attributes(login_header(app))['httponly'], (
            'without HttpOnly any XSS anywhere in the app reads the session '
            'cookie directly'
        )

    def test_samesite_lax_is_written_explicitly(self, tmp_path):
        """Explicit, because the default is browser-dependent.

        Lax rather than Strict: Strict withholds the cookie on a top-level
        navigation from another site, so following a link or a bookmark from
        anywhere else lands the operator on the login page instead of the page
        they asked for.
        """
        _, _, _, app = build(tmp_path)
        header = login_header(app)

        assert attributes(header)['samesite'].lower() == 'lax', header
        assert 'SameSite=Lax' in header, (
            'the attribute is present but not in the canonical spelling: %r'
            % header
        )

    def test_the_path_is_the_apps_web_base(self, tmp_path):
        _, _, _, app = build(tmp_path)

        assert attributes(login_header(app))['path'] == '/'

    def test_the_path_follows_a_non_root_web_base(self, tmp_path):
        """A cookie scoped to `/` on an install served at `/couchpotato/` is
        sent to every other app behind the same host."""
        _, _, _, app = build(tmp_path, web_base='/couchpotato/')
        try:
            header = login_header(app, web_base='/couchpotato/')

            assert attributes(header)['path'] == '/couchpotato/', header
        finally:
            Env.set('web_base', '/')


class TestTheDeletionCannotMismatchTheCookieItDeletes:
    """AC-SEC-39's last clause, and AC-ARCH-7/8's reason for existing.

    A `Set-Cookie` deletion only matches if its `Path` (and `Domain`) match the
    cookie that was set. A mismatch leaves the original cookie in the browser
    while the server believes it cleared it -- which, before D1, was the whole
    of "logging out".
    """

    def test_the_set_and_delete_headers_agree_on_every_attribute(self, tmp_path):
        _, _, secret, app = build(tmp_path, web_base='/couchpotato/')
        try:
            set_header = login_header(app, web_base='/couchpotato/')

            client = TestClient(app, follow_redirects=False)
            client.cookies.set(SESSION_COOKIE_NAME, mint_session_token(secret, 3600),
                               path='/couchpotato/')
            response = client.post('/couchpotato/logout/')
            assert response.status_code in (302, 303), response.status_code
            delete_header = response.headers.get('set-cookie')
            assert delete_header, 'logout emitted no Set-Cookie at all'

            issued = attributes(set_header)
            cleared = attributes(delete_header)
            for attribute in ('path', 'samesite', 'httponly', 'secure'):
                assert issued[attribute] == cleared[attribute], (
                    '%s differs between the set and the delete header '
                    '(%r vs %r), so the browser keeps the original cookie'
                    % (attribute, issued[attribute], cleared[attribute])
                )
        finally:
            Env.set('web_base', '/')

    def test_one_function_produces_the_attributes_for_both_paths(self):
        """Structural: the agreement above must not be two literals that match.

        Two hand-written attribute lists agree until someone edits one of them,
        and the failure is invisible -- the operator sees a login page and
        assumes they are signed out.
        """
        import ast
        import inspect

        from couchpotato import create_app, session_cookie_attributes

        source = inspect.getsource(create_app)
        tree = ast.parse(__import__('textwrap').dedent(source))
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and getattr(node.func, 'attr', None) in ('set_cookie', 'delete_cookie')]

        # One `set_cookie` (login) and two `delete_cookie` (the revoking
        # logout, and the auth-OFF logout of D12 which revokes nothing but
        # still drops a stale cookie). Kept EXACT rather than `>=`: the point
        # is that no cookie is written anywhere this test has not looked at.
        assert len(calls) == 3, (
            'expected one set_cookie and two delete_cookie, found %d: %r'
            % (len(calls), [ast.unparse(c) for c in calls])
        )
        for call in calls:
            unparsed = ast.unparse(call)
            assert 'session_cookie_attributes()' in unparsed, unparsed
            for attribute in ('httponly', 'samesite', 'secure', 'path'):
                assert '%s=' % attribute not in unparsed, (
                    '%r is set inline as well as through '
                    'session_cookie_attributes(), so the two can disagree: %s'
                    % (attribute, unparsed)
                )

        assert callable(session_cookie_attributes)
