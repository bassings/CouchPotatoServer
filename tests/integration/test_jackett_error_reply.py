"""A Jackett reply that is an error is an error, wherever the `<error>` element sits.

Jackett answers an invalid API key with a document whose ROOT is
`<error code="100" description="Invalid API Key"/>`. The real provider runs over
a real `Settings`; only the HTTP session is replaced (`Transport`, which
records every request and answers with a chosen body). The key is bound through
the production writer, a `settings.save` of the key, as in the key-guard tests.

Hosts are `.invalid` names and the key is a `placeholder-` string.
"""
import pytest

from tests.helpers.combine_groups import LogCapture, sha
from tests.helpers.jackett_binding import (
    INDEXERS_XML,
    OPERATIONS,
    PLACEHOLDER_KEY,
    guarded_world,
)
from tests.integration.test_jackett_key_guard import ADDRESS_A, HOST_A, bind, run

pytestmark = pytest.mark.integration

ERROR_TEXT = 'Jackett returned an error response'
ROOT_ERROR = '<error code="100" description="Invalid API Key"/>'
NESTED_ERROR = '<results><error code="100" description="Invalid API Key"/></results>'
PARSE_TEXT = 'Failed to parse Jackett response XML'
EMPTY_INDEXERS = '<indexers/>'
HOSTILE_DESCRIPTIONS = [
    ('html tags', '&lt;script&gt;alert(1)&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;'),
    ('5000 characters', 'A' * 5000),
    ('control characters XML allows', 'bad&#127;&#133;[31mred&#9;tab'),
    ('crlf', 'line one&#13;&#10;Set-Cookie: x=1'),
]


@pytest.fixture
def world(tmp_path, monkeypatch):
    with guarded_world(tmp_path, monkeypatch) as live:
        settings, client, provider, transport = live
        bind(client)
        transport.requests.clear()
        yield live


def answer(world, operation, body):
    settings, client, provider, transport = world
    transport.body = body
    transport.requests.clear()
    with LogCapture() as logs:
        result = run(provider, operation)
    assert len(transport.requests) == 1
    return result, logs


def assert_error_reply(result, logs, settings):
    assert result == {'success': False, 'error': ERROR_TEXT}
    for private in (PLACEHOLDER_KEY, ADDRESS_A, HOST_A, 'apikey='):
        assert private not in str(result)
        assert private not in logs.text()


@pytest.mark.parametrize('operation', OPERATIONS)
class TestAnErrorReply:

    @pytest.mark.parametrize('label,body', [('root', ROOT_ERROR), ('nested', NESTED_ERROR)])
    def test_an_error_reply_is_a_failure_with_the_one_error_text_and_nothing_written(
            self, world, operation, label, body):
        settings = world[0]
        before = sha(settings.file)

        result, logs = answer(world, operation, body)

        assert_error_reply(result, logs, settings)
        assert sha(settings.file) == before

    def test_a_root_error_is_logged_as_the_nested_one_is(self, world, operation):
        _, nested_logs = answer(world, operation, NESTED_ERROR)
        _, root_logs = answer(world, operation, ROOT_ERROR)

        assert [(r.levelname, r.getMessage()) for r in root_logs.at_or_above(40)] == \
               [(r.levelname, r.getMessage()) for r in nested_logs.at_or_above(40)]
        assert len(root_logs.at_or_above(40)) == 1

    @pytest.mark.parametrize('label,description', HOSTILE_DESCRIPTIONS,
                             ids=[row[0] for row in HOSTILE_DESCRIPTIONS])
    def test_a_hostile_description_never_reaches_the_response_or_the_log(
            self, world, operation, label, description):
        settings = world[0]
        before = sha(settings.file)
        body = f'<error code="100" description="{description}"/>'

        result, logs = answer(world, operation, body)

        assert result == {'success': False, 'error': ERROR_TEXT}
        assert 'script' not in logs.text()
        assert 'Set-Cookie' not in logs.text()
        assert 'AAAA' not in logs.text()
        assert sha(settings.file) == before

    def test_a_description_with_a_control_character_xml_forbids_is_a_parse_failure_not_a_success(
            self, world, operation):
        result, logs = answer(world, operation, '<error code="100" description="bad&#1;x"/>')

        assert result == {'success': False, 'error': PARSE_TEXT}
        assert 'bad' not in logs.text()


class TestRepliesThatAreNotErrors:

    def test_a_normal_reply_is_unchanged(self, world):
        result, _ = answer(world, 'jackettTest', INDEXERS_XML)

        assert result['success'] is True
        assert result['count'] == 1
        assert [i['id'] for i in result['indexers']] == ['alpha']

    def test_an_empty_indexers_reply_is_still_a_genuine_empty_list(self, world):
        test_result, _ = answer(world, 'jackettTest', EMPTY_INDEXERS)
        sync_result, _ = answer(world, 'jackettSync', EMPTY_INDEXERS)

        assert test_result == {'success': True, 'indexers': [], 'count': 0}
        assert sync_result == {'success': False, 'error': 'No configured indexers found in Jackett'}
