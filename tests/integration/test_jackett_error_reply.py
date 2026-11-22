"""A Jackett reply that is an error is an error, wherever the `<error>` element sits.

Jackett answers an invalid API key with a document whose ROOT is
`<error code="100" description="Invalid API Key"/>`. Owner decision D9: an error whose `code` is
exactly "100" says the key was not accepted; every other error keeps the generic text. Only the
`code` attribute is read, and nothing of the reply is returned or logged. The real provider runs over
a real `Settings`; only the HTTP session is replaced (`Transport`, which
records every request and answers with a chosen body). The key is bound through
the production writer, a `settings.save` of the key, as in the key-guard tests.

Hosts are `.invalid` names and the key is a `placeholder-` string.
"""
import pytest

from tests.helpers.combine_groups import LogCapture, sha
from tests.helpers.jackett_binding import (
    INDEXERS_XML,
    KEY_REJECTED,
    OPERATIONS,
    PLACEHOLDER_KEY,
    guarded_world,
)
from tests.integration.test_jackett_key_guard import ADDRESS_A, HOST_A, bind, run

pytestmark = pytest.mark.integration

ERROR_TEXT = 'Jackett returned an error response'
ROOT_ERROR = '<error code="100" description="Invalid API Key"/>'
NESTED_ERROR = '<results><error code="100" description="Invalid API Key"/></results>'
# Errors that are not the invalid-key code: the generic text, as before D9.
OTHER_ROOT_ERROR = '<error code="201" description="Indexer unavailable"/>'
OTHER_NESTED_ERROR = '<results><error code="201" description="Indexer unavailable"/></results>'
NO_CODE_ERROR = '<error description="Something"/>'
PARSE_TEXT = 'Failed to parse Jackett response XML'
EMPTY_INDEXERS = '<indexers/>'
# (label, the description as written in the XML, a distinctive part of it as it
# reads once parsed). Every row must show its OWN marker absent from the log.
HOSTILE_DESCRIPTIONS = [
    ('html tags', '&lt;script&gt;alert(1)&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;', 'onerror=alert'),
    ('5000 characters', 'A' * 5000, 'A' * 50),
    ('control characters XML allows', 'qzx&#127;&#133;[31mred&#9;tab', 'qzx'),
    ('crlf', 'line one&#13;&#10;Set-Cookie: x=1', 'Set-Cookie'),
]
DESCRIPTION = 'Invalid API Key'


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


def assert_error_reply(result, logs, settings, text=ERROR_TEXT):
    assert result == {'success': False, 'error': text}
    for private in (PLACEHOLDER_KEY, ADDRESS_A, HOST_A, 'apikey=', DESCRIPTION):
        assert private not in str(result)
        assert private not in logs.text()


@pytest.mark.parametrize('operation', OPERATIONS)
class TestAnErrorReply:

    @pytest.mark.parametrize('label,body,text', [
        ('root, invalid-key code', ROOT_ERROR, KEY_REJECTED),
        ('nested, invalid-key code', NESTED_ERROR, KEY_REJECTED),
        ('root, another code', OTHER_ROOT_ERROR, ERROR_TEXT),
        ('nested, another code', OTHER_NESTED_ERROR, ERROR_TEXT),
        ('root, no code', NO_CODE_ERROR, ERROR_TEXT),
    ])
    def test_an_error_reply_is_a_failure_with_its_fixed_text_and_nothing_written(
            self, world, operation, label, body, text):
        settings = world[0]
        before = sha(settings.file)

        result, logs = answer(world, operation, body)

        assert_error_reply(result, logs, settings, text)
        assert sha(settings.file) == before

    @pytest.mark.parametrize('code', ['100 ', ' 100', '1000', '10', '0100', 'abc', '\u0661\u0660\u0660',
                                      '100.0', '', '99999999999999999999999999'])
    def test_a_code_that_is_not_exactly_100_is_the_generic_error(self, world, operation, code):
        result, logs = answer(world, operation, f'<error code="{code}" description="x"/>')

        assert result == {'success': False, 'error': ERROR_TEXT}

    @pytest.mark.parametrize('marker,code', [
        ('onerror=alert', '&lt;img src=x onerror=alert(1)&gt;'),
        ('Set-Cookie', '100&#13;&#10;Set-Cookie: x=1'),
        ('Z' * 50, 'Z' * 5000),
    ])
    def test_a_hostile_code_never_reaches_the_response_or_the_log(self, world, operation, marker, code):
        settings = world[0]
        before = sha(settings.file)

        result, logs = answer(world, operation, f'<error code="{code}" description="x"/>')

        assert result == {'success': False, 'error': ERROR_TEXT}
        assert marker not in str(result)
        assert logs.records
        assert marker not in logs.text()
        assert sha(settings.file) == before

    def test_the_invalid_key_code_among_other_errors_is_still_the_rejected_key(self, world, operation):
        body = '<results><error code="201"/><error code="100"/></results>'

        result, _ = answer(world, operation, body)

        assert result == {'success': False, 'error': KEY_REJECTED}

    def test_a_root_error_is_logged_as_the_nested_one_is(self, world, operation):
        _, nested_logs = answer(world, operation, NESTED_ERROR)
        _, root_logs = answer(world, operation, ROOT_ERROR)

        assert [(r.levelname, r.getMessage()) for r in root_logs.at_or_above(40)] == \
               [(r.levelname, r.getMessage()) for r in nested_logs.at_or_above(40)]
        assert len(root_logs.at_or_above(40)) == 1
        for logs in (root_logs, nested_logs):
            assert DESCRIPTION not in logs.text()
            assert all(DESCRIPTION not in r.getMessage() for r in logs.records)

    @pytest.mark.parametrize('label,description,marker', HOSTILE_DESCRIPTIONS,
                             ids=[row[0] for row in HOSTILE_DESCRIPTIONS])
    def test_a_hostile_description_never_reaches_the_response_or_the_log(
            self, world, operation, label, description, marker):
        settings = world[0]
        before = sha(settings.file)
        body = f'<error code="100" description="{description}"/>'

        result, logs = answer(world, operation, body)

        assert result == {'success': False, 'error': KEY_REJECTED}
        assert marker not in str(result)
        assert logs.records, 'the capture saw nothing, so an absent marker proves nothing'
        assert marker not in logs.text()
        assert all(marker not in r.getMessage() for r in logs.records)
        assert sha(settings.file) == before

    @pytest.mark.parametrize('label,description,marker', HOSTILE_DESCRIPTIONS,
                             ids=[row[0] for row in HOSTILE_DESCRIPTIONS])
    def test_a_hostile_description_on_another_error_is_the_generic_text_and_leaks_nowhere(
            self, world, operation, label, description, marker):
        result, logs = answer(world, operation, f'<error code="201" description="{description}"/>')

        assert result == {'success': False, 'error': ERROR_TEXT}
        assert marker not in str(result)
        assert marker not in logs.text()

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
