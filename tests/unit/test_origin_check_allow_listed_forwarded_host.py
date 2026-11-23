"""`X-Forwarded-Host` cannot vouch for an origin on the CORS allow-list.

Helper-level proof for FIX-2026-11-23 (specs/FIX-2026-11-23-origin-check-
allow-listed-forwarded-host.md). With `cors_origins` set, a page on a listed
origin CAN send `X-Forwarded-Host` (the CORS preflight succeeds), so for that
origin only `Host` may count as this app's identity. The route-level proof
through the real app is in tests/integration/.

Requests are plain header maps with lower-case keys, the same shape Starlette's
`request.headers` offers to `.get`. Hosts end in `.invalid`.
"""
from types import SimpleNamespace

import pytest

from couchpotato import (
    _cross_origin_guarded_route,
    _cross_origin_post,
    _parse_cors_origins,
)

LISTED = 'http://dash.invalid'
HELPERS = {
    'post': _cross_origin_post,
    'guarded': _cross_origin_guarded_route,
}


def request(**headers):
    return SimpleNamespace(headers={k.replace('_', '-'): v for k, v in headers.items()})


def on_app(req, cors_origins):
    """Attach the allow-list the way `create_app` does: on `app.state`."""
    req.app = SimpleNamespace(state=SimpleNamespace(cors_origins=cors_origins))
    return req


@pytest.fixture(params=sorted(HELPERS))
def helper(request):
    return HELPERS[request.param]


class TestAListedOriginCannotBeVouchedForByForwardedHost:
    def test_origin_header(self, helper):
        req = request(origin=LISTED, host='cp.invalid:5050',
                      x_forwarded_host='dash.invalid')
        assert helper(on_app(req, [LISTED])) is True

    def test_referer_only(self, helper):
        req = request(referer=LISTED + '/some/page?x=1', host='cp.invalid:5050',
                      x_forwarded_host='dash.invalid')
        assert helper(on_app(req, [LISTED])) is True

    def test_comma_list_containing_the_listed_host(self, helper):
        req = request(origin=LISTED, host='cp.invalid:5050',
                      x_forwarded_host='dash.invalid, inner.invalid')
        assert helper(on_app(req, [LISTED])) is True

    def test_comma_list_with_the_listed_host_last(self, helper):
        req = request(origin=LISTED, host='cp.invalid:5050',
                      x_forwarded_host='inner.invalid,dash.invalid')
        assert helper(on_app(req, [LISTED])) is True

    def test_listed_with_a_port(self, helper):
        req = request(origin='http://dash.invalid:8080', host='cp.invalid:5050',
                      x_forwarded_host='dash.invalid:8080')
        assert helper(on_app(req, ['http://dash.invalid:8080'])) is True

    def test_entry_with_surrounding_spaces_and_a_neighbour(self, helper):
        listed = _parse_cors_origins(' http://other.invalid ,  %s  ' % LISTED)
        req = request(origin=LISTED, host='cp.invalid:5050',
                      x_forwarded_host='dash.invalid')
        assert helper(on_app(req, listed)) is True


class TestAListedOriginThatIsTheRealHostIsSameOrigin:
    """AC-5: the own origin is listed and `Host` is preserved by the proxy."""

    def test_host_equal_to_the_listed_origin(self, helper):
        req = request(origin='https://media.invalid', host='media.invalid')
        assert helper(on_app(req, ['https://media.invalid'])) is False

    def test_with_a_port(self, helper):
        req = request(origin='http://dash.invalid:5050', host='dash.invalid:5050',
                      x_forwarded_host='dash.invalid:5050')
        assert helper(on_app(req, ['http://dash.invalid:5050'])) is False

    def test_referer_only(self, helper):
        req = request(referer='https://media.invalid/movies', host='media.invalid')
        assert helper(on_app(req, ['https://media.invalid'])) is False


class TestEverythingElseIsJudgedAsBefore:
    def test_empty_allow_list_reverse_proxy_case(self, helper):
        req = request(origin='https://media.invalid', host='127.0.0.1:5050',
                      x_forwarded_host='media.invalid')
        assert helper(on_app(req, [])) is False

    def test_unlisted_origin_is_still_vouched_for_by_forwarded_host(self, helper):
        req = request(origin='https://media.invalid', host='127.0.0.1:5050',
                      x_forwarded_host='media.invalid')
        assert helper(on_app(req, [LISTED])) is False

    def test_unlisted_origin_via_referer_is_still_vouched_for(self, helper):
        req = request(referer='https://media.invalid/x', host='127.0.0.1:5050',
                      x_forwarded_host='media.invalid')
        assert helper(on_app(req, [LISTED])) is False

    def test_unlisted_foreign_origin_is_still_cross_origin(self, helper):
        req = request(origin='http://evil.invalid', host='cp.invalid:5050',
                      x_forwarded_host='media.invalid')
        assert helper(on_app(req, [LISTED])) is True

    def test_a_wrong_port_variant_of_a_listed_origin_is_not_listed(self, helper):
        # Starlette matches by exact string, so the middleware would not allow
        # this origin to send the header; it is judged as before.
        req = request(origin='http://dash.invalid:9999', host='cp.invalid:5050',
                      x_forwarded_host='dash.invalid:9999')
        assert helper(on_app(req, [LISTED])) is False

    def test_a_scheme_variant_of_a_listed_origin_is_not_listed(self, helper):
        req = request(origin='https://dash.invalid', host='cp.invalid:5050',
                      x_forwarded_host='dash.invalid')
        assert helper(on_app(req, [LISTED])) is False

    def test_a_case_variant_of_a_listed_origin_is_not_listed(self, helper):
        req = request(origin='http://DASH.invalid', host='cp.invalid:5050',
                      x_forwarded_host='DASH.invalid')
        assert helper(on_app(req, [LISTED])) is False

    def test_a_trailing_slash_entry_never_matches(self, helper):
        # The middleware keeps the slash and so never matches either.
        listed = _parse_cors_origins(LISTED + '/')
        assert listed == [LISTED + '/']
        req = request(origin=LISTED, host='cp.invalid:5050',
                      x_forwarded_host='dash.invalid')
        assert helper(on_app(req, listed)) is False

    def test_a_wildcard_entry_never_counts(self, helper):
        listed = _parse_cors_origins('*')
        assert listed == []
        req = request(origin='https://media.invalid', host='127.0.0.1:5050',
                      x_forwarded_host='media.invalid')
        assert helper(on_app(req, listed)) is False

    def test_no_evidence_post_allows_and_guarded_route_refuses(self):
        req = request(host='cp.invalid:5050', x_forwarded_host='dash.invalid')
        assert _cross_origin_post(on_app(req, [LISTED])) is False
        assert _cross_origin_guarded_route(on_app(req, [LISTED])) is True


class TestOneParseServesTheMiddlewareAndTheCheck:
    @pytest.mark.parametrize('raw, expected', [
        ('', []),
        (None, []),
        ('*', []),
        (' * , http://dash.invalid ', ['http://dash.invalid']),
        ('http://a.invalid,,http://b.invalid/ ', ['http://a.invalid', 'http://b.invalid/']),
    ])
    def test_parse(self, raw, expected):
        assert _parse_cors_origins(raw) == expected
