"""A key Jackett itself does not accept says so (SEC-005 owner decision D9).

Two triggers, both recalled from Jackett's documented behaviour and NOT observed against a real
Jackett: the request is answered with HTTP 401, or the reply has an `<error>` whose `code` is exactly
"100" (covered with the other reply shapes in test_jackett_error_reply.py). Everything else keeps the
text it had. The real provider and `HttpClient` run over a real `Settings`; only the HTTP session is
replaced (`Transport`). `Reply` raises the way `requests` does, with the request URL (which carries
the key) in the exception's own text, so a report that used that text would show it.

Hosts are `.invalid` names and the key is a `placeholder-` string.
"""
import pytest
import requests

from tests.helpers.combine_groups import LogCapture, sha
from tests.helpers.jackett_binding import KEY_REJECTED, OPERATIONS, PLACEHOLDER_KEY, guarded_world
from tests.integration.test_jackett_key_guard import ADDRESS_A, HOST_A, bind, run

pytestmark = pytest.mark.integration

CONNECT_TEXT = 'Failed to connect to Jackett: HTTPError'


@pytest.fixture
def world(tmp_path, monkeypatch):
    with guarded_world(tmp_path, monkeypatch) as live:
        settings, client, provider, transport = live
        bind(client)
        transport.requests.clear()
        yield live


def answer(world, operation, status):
    settings, client, provider, transport = world
    transport.status = status
    transport.body = '<error code="100" description="ignored"/>'
    transport.requests.clear()
    with LogCapture() as logs:
        result = run(provider, operation)
    assert len(transport.requests) == 1
    return result, logs


@pytest.mark.parametrize('operation', OPERATIONS)
class TestAnHttpStatus:

    def test_a_401_is_the_rejected_key_and_nothing_is_written_or_leaked(self, world, operation):
        settings = world[0]
        before = sha(settings.file)

        result, logs = answer(world, operation, 401)

        assert result == {'success': False, 'error': KEY_REJECTED}
        assert sha(settings.file) == before
        assert logs.records, 'the capture saw nothing, so an absent value proves nothing'
        for private in (PLACEHOLDER_KEY, ADDRESS_A, HOST_A, 'apikey=', 'Client Error'):
            assert private not in str(result)
            assert private not in logs.text()
            assert all(private not in record.getMessage() for record in logs.records)

    @pytest.mark.parametrize('status', [400, 403, 404, 429, 500, 502, 503])
    def test_every_other_status_keeps_the_connection_text(self, world, operation, status):
        result, logs = answer(world, operation, status)

        assert result == {'success': False, 'error': CONNECT_TEXT}
        for private in (PLACEHOLDER_KEY, HOST_A, 'apikey='):
            assert private not in str(result)
            assert private not in logs.text()

    def test_an_error_that_is_not_an_http_status_keeps_the_connection_text(self, world, operation):
        settings, client, provider, transport = world

        def refuse(method, url, **kwargs):
            raise requests.exceptions.ConnectionError(f'cannot reach {url}')

        transport.request = refuse
        with LogCapture() as logs:
            result = run(provider, operation)

        assert result == {'success': False, 'error': 'Failed to connect to Jackett: ConnectionError'}
        assert PLACEHOLDER_KEY not in logs.text()
