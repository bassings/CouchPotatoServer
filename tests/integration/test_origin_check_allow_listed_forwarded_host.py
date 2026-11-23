"""An origin on the CORS allow-list cannot vouch for itself with `X-Forwarded-Host`.

FIX-2026-11-23 (specs/FIX-2026-11-23-origin-check-allow-listed-forwarded-host.md).
Driven through the real app from `create_app` with the real CORS middleware, the
real logout route over a real `SQLiteAdapter`, and the real dispatch for the
real route name `renamer.operator_replace`, whose handler is replaced by a spy
that deletes nothing. Every hostile probe first proves the CORS preflight for the
header set is allowed, so the request is one a browser really could send.
Hosts end in `.invalid`.
"""
import pytest

from couchpotato import SESSION_COOKIE_NAME, SESSION_SECRET_PROPERTY
from couchpotato.api import addApiView, api, api_locks
from tests.unit.test_session_revocation import API_KEY, _build_env, log_in

pytestmark = pytest.mark.integration

LISTED = 'http://dash.invalid'
HOSTILE = {
    'origin': LISTED,
    'host': 'cp.invalid:5050',
    'x-forwarded-host': 'dash.invalid',
}
ROUTE = 'renamer.operator_replace'
ROUTE_URL = '/api/%s/%s' % (API_KEY, ROUTE)
PREFLIGHT_HEADERS = 'content-type,x-forwarded-host'


@pytest.fixture
def listed(tmp_path):
    yield from _build_env(tmp_path, {'cors_origins': LISTED})


@pytest.fixture
def unlisted(tmp_path):
    yield from _build_env(tmp_path, {'cors_origins': ''})


_ABSENT = object()


@pytest.fixture(scope='module', autouse=True)
def the_route_registry_is_left_as_found():
    """The stand-in handler must not outlive this module as the real route."""
    before = (api.get(ROUTE, _ABSENT), api_locks.get(ROUTE, _ABSENT))
    yield
    assert (api.get(ROUTE, _ABSENT), api_locks.get(ROUTE, _ABSENT)) == before


@pytest.fixture
def spy():
    """Register a spy under the real route name and put back what was there.

    Restores the exact previous entries itself, because it may be set up before
    the environment fixture snapshots the registry (that snapshot would then
    contain the spy and "restore" it).
    """
    previous = (api.get(ROUTE, _ABSENT), api_locks.get(ROUTE, _ABSENT))
    calls = []
    addApiView(ROUTE, lambda **kwargs: calls.append(kwargs) or {'success': True})
    yield calls
    for registry, value in zip((api, api_locks), previous):
        if value is _ABSENT:
            registry.pop(ROUTE, None)
        else:
            registry[ROUTE] = value


def client_for(env):
    from fastapi.testclient import TestClient
    return TestClient(env.app, follow_redirects=False)


def assert_preflight_allowed(client, path, origin=LISTED):
    """The probe is hostile only if a browser could really send the header."""
    response = client.options(path, headers={
        'origin': origin,
        'access-control-request-method': 'POST',
        'access-control-request-headers': PREFLIGHT_HEADERS,
    })
    assert response.status_code == 200, response.text
    assert response.headers.get('access-control-allow-origin') == origin
    assert response.headers.get('access-control-allow-credentials') == 'true'


def evidence(kind):
    """`origin` header or `referer` header carrying the same listed origin."""
    headers = dict(HOSTILE)
    if kind == 'referer':
        del headers['origin']
        headers['referer'] = LISTED + '/some/page'
    return headers


@pytest.mark.parametrize('kind', ['origin', 'referer'])
class TestTheLogoutPost:
    def test_a_listed_origin_with_a_forwarded_host_is_refused_and_nothing_rotates(
            self, listed, kind):
        before = listed.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(listed)
        assert_preflight_allowed(client, '/logout/')

        response = client.post('/logout/', headers=evidence(kind))

        assert response.status_code == 403, response.status_code
        assert listed.settings.getProperty(SESSION_SECRET_PROPERTY) == before

    def test_the_comma_list_form_is_refused_too(self, listed, kind):
        before = listed.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(listed)
        headers = evidence(kind)
        headers['x-forwarded-host'] = 'dash.invalid, inner.invalid'

        response = client.post('/logout/', headers=headers)

        assert response.status_code == 403
        assert listed.settings.getProperty(SESSION_SECRET_PROPERTY) == before


class TestTheLogoutPostControls:
    """The refusal above must not be a guard that refuses everything."""

    def test_own_origin_listed_with_host_preserved_still_signs_out(self, tmp_path):
        env_iter = _build_env(tmp_path, {'cors_origins': 'http://cp.invalid:5050'})
        env = next(env_iter)
        try:
            before = env.settings.getProperty(SESSION_SECRET_PROPERTY)
            client, _ = log_in(env)

            response = client.post('/logout/', headers={
                'origin': 'http://cp.invalid:5050', 'host': 'cp.invalid:5050'})

            assert response.status_code in (302, 303), response.status_code
            assert env.settings.getProperty(SESSION_SECRET_PROPERTY) != before
        finally:
            list(env_iter)

    def test_an_unlisted_proxied_origin_still_signs_out(self, listed):
        before = listed.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(listed)

        response = client.post('/logout/', headers={
            'origin': 'https://media.invalid', 'host': '127.0.0.1:5050',
            'x-forwarded-host': 'media.invalid'})

        assert response.status_code in (302, 303), response.status_code
        assert listed.settings.getProperty(SESSION_SECRET_PROPERTY) != before

    def test_with_the_list_empty_the_forwarded_host_still_vouches(self, unlisted):
        before = unlisted.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(unlisted)

        response = client.post('/logout/', headers=HOSTILE)

        assert response.status_code in (302, 303), response.status_code
        assert unlisted.settings.getProperty(SESSION_SECRET_PROPERTY) != before

    def test_a_variant_origin_is_not_allowed_by_cors_and_is_judged_as_before(self, listed):
        client, _ = log_in(listed)
        variant = 'http://dash.invalid:9999'
        denied = client.options('/logout/', headers={
            'origin': variant,
            'access-control-request-method': 'POST',
            'access-control-request-headers': PREFLIGHT_HEADERS,
        })
        assert denied.status_code == 400
        assert 'access-control-allow-origin' not in denied.headers

        response = client.post('/logout/', headers={
            'origin': variant, 'host': 'cp.invalid:5050',
            'x-forwarded-host': 'dash.invalid:9999'})

        assert response.status_code in (302, 303), response.status_code


@pytest.mark.parametrize('kind', ['origin', 'referer'])
class TestAnOriginCheckedApiRoute:
    def test_a_listed_origin_with_a_forwarded_host_gets_403_and_the_handler_is_not_called(
            self, listed, spy, kind):
        client = client_for(listed)
        assert_preflight_allowed(client, ROUTE_URL)

        response = client.get(ROUTE_URL, headers=evidence(kind))

        assert response.status_code == 403, response.text
        assert response.json() == {'success': False, 'error': 'Cross-origin request refused'}
        assert spy == []

    def test_a_post_is_refused_too(self, listed, spy, kind):
        client = client_for(listed)

        response = client.post(ROUTE_URL, headers=evidence(kind))

        assert response.status_code == 403
        assert spy == []


class TestAnOriginCheckedApiRouteControls:
    def test_own_origin_listed_with_host_preserved_reaches_the_handler(self, tmp_path, spy):
        env_iter = _build_env(tmp_path, {'cors_origins': LISTED})
        env = next(env_iter)
        try:
            response = client_for(env).get(ROUTE_URL, headers={
                'origin': LISTED, 'host': 'dash.invalid'})
            assert response.status_code == 200, response.text
            assert len(spy) == 1
        finally:
            list(env_iter)

    def test_an_unlisted_proxied_origin_reaches_the_handler(self, listed, spy):
        response = client_for(listed).get(ROUTE_URL, headers={
            'origin': 'https://media.invalid', 'host': '127.0.0.1:5050',
            'x-forwarded-host': 'media.invalid'})
        assert response.status_code == 200, response.text
        assert len(spy) == 1

    def test_with_the_list_empty_the_forwarded_host_still_vouches(self, unlisted, spy):
        response = client_for(unlisted).get(ROUTE_URL, headers=HOSTILE)
        assert response.status_code == 200, response.text
        assert len(spy) == 1

    def test_no_evidence_is_still_refused(self, listed, spy):
        response = client_for(listed).get(ROUTE_URL)
        assert response.status_code == 403
        assert spy == []


class TestTheCheckFollowsTheValueTheMiddlewareWasBuiltWith:
    """AC-6. The middleware is fixed at creation, so the check must be too."""

    def test_removing_the_entry_later_does_not_open_a_window(self, listed, spy):
        client = client_for(listed)
        assert_preflight_allowed(client, ROUTE_URL)

        listed.settings.data['cors_origins'] = ''

        # The middleware still allows the origin ...
        assert_preflight_allowed(client, ROUTE_URL)
        # ... so the check must still know it.
        response = client.get(ROUTE_URL, headers=HOSTILE)
        assert response.status_code == 403
        assert spy == []

    def test_adding_an_entry_later_changes_nothing_until_a_restart(self, unlisted, spy):
        client = client_for(unlisted)
        unlisted.settings.data['cors_origins'] = LISTED

        denied = client.options(ROUTE_URL, headers={
            'origin': LISTED,
            'access-control-request-method': 'POST',
            'access-control-request-headers': PREFLIGHT_HEADERS})
        assert denied.status_code == 400

        response = client.get(ROUTE_URL, headers=HOSTILE)
        assert response.status_code == 200
        assert len(spy) == 1


class TestTheRefusalLogExplainsAListedOrigin:
    """The warning for a listed origin names the real cause and both remedies."""

    LISTED_TEXT = 'is listed in cors_origins'

    def messages(self, caplog):
        return ' '.join(r.getMessage() for r in caplog.records if r.levelname == 'WARNING')

    @pytest.mark.parametrize('kind', ['origin', 'referer'])
    def test_sign_out_for_a_listed_origin(self, listed, caplog, kind):
        client, _ = log_in(listed)
        with caplog.at_level('WARNING'):
            client.post('/logout/', headers=evidence(kind))
        text = self.messages(caplog)
        assert self.LISTED_TEXT in text
        assert 'X-Forwarded-Host is not trusted' in text
        assert 'remove the entry' in text.lower()
        assert 'preserve Host' in text

    @pytest.mark.parametrize('kind', ['origin', 'referer'])
    def test_route_for_a_listed_origin(self, listed, spy, caplog, kind):
        with caplog.at_level('WARNING'):
            client_for(listed).get(ROUTE_URL, headers=evidence(kind))
        text = self.messages(caplog)
        assert self.LISTED_TEXT in text
        assert 'X-Forwarded-Host is not trusted' in text
        assert 'remove the entry' in text.lower()
        assert 'preserve Host' in text

    def test_sign_out_for_an_unlisted_origin_keeps_the_old_advice(self, listed, caplog):
        client, _ = log_in(listed)
        with caplog.at_level('WARNING'):
            client.post('/logout/', headers={'origin': 'http://evil.invalid', 'host': 'cp.invalid:5050'})
        text = self.messages(caplog)
        assert 'Refused a sign-out' in text
        assert self.LISTED_TEXT not in text
        assert 'set it to forward the original host' in text

    def test_route_for_an_unlisted_origin_keeps_the_old_advice(self, listed, spy, caplog):
        with caplog.at_level('WARNING'):
            client_for(listed).get(ROUTE_URL, headers={
                'origin': 'http://evil.invalid', 'host': 'cp.invalid:5050'})
        text = self.messages(caplog)
        assert 'Refused a cross-origin request' in text
        assert self.LISTED_TEXT not in text
        assert 'set it to forward the original host' in text

    def test_the_log_adds_no_new_header_value(self, listed, caplog):
        client, token = log_in(listed)
        assert token
        assert client.cookies.get(SESSION_COOKIE_NAME) == token
        decoys = ('secret-hop.invalid', 'decoy-agent/9.9')
        with caplog.at_level('DEBUG'):
            response = client.post('/logout/', headers={
                **HOSTILE, 'x-forwarded-for': decoys[0], 'user-agent': decoys[1]})
        assert response.status_code == 403
        assert any('Refused a sign-out' in r.getMessage() for r in caplog.records)
        everything = ' '.join(
            '%s %r %r' % (r.getMessage(), r.args, r.__dict__.get('exc_text'))
            for r in caplog.records)
        for value in (token,) + decoys:
            assert value not in everything


PAGES = ['/', '/settings/', '/wizard/', '/logs/', '/add/']


@pytest.mark.parametrize('path', PAGES)
class TestRecordedLimitAListedOriginCanReadUiPagesAndSoTheApiKey:
    """RECORDED LIMIT, not desired behaviour (docs/technical-debt.md).

    Listing an origin in `cors_origins` makes the CORS middleware answer its
    credentialled GET of a UI page with the allow-origin header, and those pages
    embed the API key. A page there can therefore learn the key and call every
    route that is not origin-checked. The pages listed here are a sample, not a
    closed list. This pins the fact so the debt entry is backed; if a fix lands
    this test should be rewritten, not "fixed".

    With a password the request must carry the session cookie (the test client
    sends it; a browser attaches it to a script request only when the origin is
    same-site with this app, because the cookie is `SameSite=Lax`). Without a
    password no cookie is needed at all.
    """

    def assert_key_is_readable(self, response):
        assert response.status_code == 200, response.status_code
        assert response.headers.get('access-control-allow-origin') == LISTED
        assert response.headers.get('access-control-allow-credentials') == 'true'
        assert API_KEY in response.text

    def test_a_listed_origin_reads_the_key_from_a_page(self, listed, path):
        client, _ = log_in(listed)
        self.assert_key_is_readable(client.get(path, headers={'origin': LISTED}))

    def test_with_no_password_a_listed_origin_needs_no_cookie(self, tmp_path, path):
        env_iter = _build_env(tmp_path, {
            'cors_origins': LISTED, 'password': '', 'auth_required': 0})
        env = next(env_iter)
        try:
            client = client_for(env)
            assert not client.cookies
            self.assert_key_is_readable(client.get(path, headers={'origin': LISTED}))
        finally:
            list(env_iter)
