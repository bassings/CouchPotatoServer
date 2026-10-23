"""Outbound HTTP diagnostics must not disclose private request targets."""

import io
import logging
import time

import pytest
import requests

from couchpotato.core import http_client
from couchpotato.core.logger import PrivacyFilter


PRIVATE_URL = (
    'http://nas.private:9117/potato/example/api'
    '?passkey=TOP_SECRET&search=Private+Movie'
)
PRIVATE_VALUES = ('nas.private', '/potato/example', 'TOP_SECRET', 'Private+Movie')


class _Transport:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def emitted_http_logs(monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
    privacy_filter = PrivacyFilter()
    privacy_filter._is_develop = False
    privacy_filter._api_key = 'UNRELATED_API_KEY'
    handler.addFilter(privacy_filter)

    logger = http_client.log.logger
    old_level = logger.level
    old_propagate = logger.propagate
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    monkeypatch.setattr(http_client.Env, 'setting', lambda *args, **kwargs: None)

    def use_transport(result):
        transport = _Transport(result)
        monkeypatch.setattr(http_client.Env, 'get', lambda *args, **kwargs: transport)
        return transport

    try:
        yield stream, use_transport
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate


def _response(status):
    response = requests.Response()
    response.status_code = status
    response.url = PRIVATE_URL
    response._content = b'ok'
    return response


def _assert_private_values_absent(text):
    for value in PRIVATE_VALUES:
        assert value not in text


def test_request_start_log_keeps_method_without_private_target(emitted_http_logs):
    stream, use_transport = emitted_http_logs
    transport = use_transport(_response(200))

    assert http_client.HttpClient().request(PRIVATE_URL) == b'ok'

    assert transport.calls == [('get', PRIVATE_URL)]
    assert 'Opening url' in stream.getvalue()
    assert 'get' in stream.getvalue()
    _assert_private_values_absent(stream.getvalue())


@pytest.mark.parametrize('status', [400, 500])
def test_http_error_logs_status_without_private_target(emitted_http_logs, status):
    stream, use_transport = emitted_http_logs
    transport = use_transport(_response(status))
    client = http_client.HttpClient()

    with pytest.raises(requests.HTTPError):
        client.request(PRIVATE_URL)

    assert transport.calls == [('get', PRIVATE_URL)]
    assert client.failed_request['nas.private:9117'] == 1
    assert str(status) in stream.getvalue()
    _assert_private_values_absent(stream.getvalue())


@pytest.mark.parametrize('error', [
    requests.ConnectionError('Connection failed for ' + PRIVATE_URL),
    requests.TooManyRedirects('Redirected from ' + PRIVATE_URL),
])
def test_transport_error_logs_class_without_private_target(emitted_http_logs, error):
    stream, use_transport = emitted_http_logs
    use_transport(error)

    expected_error = type(error)
    client = http_client.HttpClient()
    with pytest.raises(expected_error):
        client.request(PRIVATE_URL)

    assert type(error).__name__ in stream.getvalue()
    _assert_private_values_absent(stream.getvalue())


def test_open_circuit_log_omits_private_host(emitted_http_logs):
    stream, use_transport = emitted_http_logs
    transport = use_transport(_response(200))
    client = http_client.HttpClient()
    client.failed_disabled['nas.private:9117'] = time.time()

    assert client.request(PRIVATE_URL) == ''

    assert transport.calls == []
    assert 'Disabled calls' in stream.getvalue()
    _assert_private_values_absent(stream.getvalue())
