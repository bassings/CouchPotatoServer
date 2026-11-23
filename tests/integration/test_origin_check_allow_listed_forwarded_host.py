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

from couchpotato import SESSION_SECRET_PROPERTY
from couchpotato.api import addApiView
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


@pytest.fixture
def spy():
    calls = []
    addApiView(ROUTE, lambda **kwargs: calls.append(kwargs) or {'success': True})
    return calls


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
