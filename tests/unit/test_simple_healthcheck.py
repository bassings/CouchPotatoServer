"""Behavioral tests for the standalone localhost health probe."""

from http.client import IncompleteRead
from io import BytesIO
import runpy
from urllib.error import HTTPError, URLError
import urllib.request

import pytest

from couchpotato import simple_healthcheck


class FakeResponse:
    def __init__(self, status=200, body=b"<title>CouchPotato - Sign in</title>"):
        self.status = status
        self.body = BytesIO(body)
        self.closed = False
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def getcode(self):
        return self.status

    def read1(self, size):
        self.read_sizes.append(size)
        return self.body.read(size)


def test_probe_accepts_the_current_login_page_and_closes_the_response():
    response = FakeResponse()
    calls = []

    def open_root(url, *, timeout):
        calls.append((url, timeout))
        return response

    failures = simple_healthcheck.check_health(
        base_url="http://localhost:5050",
        timeout=7,
        max_response_time=5,
        opener=open_root,
        clock=iter([10.0, 10.1, 10.25]).__next__,
    )

    assert failures == []
    assert calls == [("http://localhost:5050/", 5)]
    assert response.closed
    assert response.read_sizes == [simple_healthcheck.READ_CHUNK_BYTES]


@pytest.mark.parametrize("status", [404, 503])
def test_probe_reports_a_non_success_status_without_an_assertion_wrapper(status):
    def http_failure(url, *, timeout):
        raise HTTPError(url, status, "failure", hdrs=None, fp=None)

    failures = simple_healthcheck.check_health(
        opener=http_failure,
        clock=iter([10.0, 10.1]).__next__,
    )

    assert failures == [f"root endpoint returned HTTP {status}"]


def test_probe_closes_an_http_error_response():
    response_body = BytesIO(b"private upstream response")
    retained_errors = [
        HTTPError(
            "http://localhost:5050/",
            503,
            "failure",
            hdrs=None,
            fp=response_body,
        )
    ]

    def http_failure(_url, *, timeout):
        raise retained_errors[0]

    failures = simple_healthcheck.check_health(
        opener=http_failure,
        clock=iter([10.0, 10.1]).__next__,
    )

    assert failures == ["root endpoint returned HTTP 503"]
    assert response_body.closed


def test_probe_reports_when_the_response_is_not_a_couchpotato_page():
    failures = simple_healthcheck.check_health(
        opener=lambda _url, *, timeout: FakeResponse(body=b"<title>Proxy</title>"),
        clock=iter([10.0, 10.02, 10.05, 10.1]).__next__,
    )

    assert failures == ["root endpoint did not return a CouchPotato page"]


@pytest.mark.parametrize(
    "network_error",
    [URLError("private upstream detail")],
)
def test_probe_reports_connection_failure_without_exposing_exception_details(
    network_error,
):
    def unavailable(_url, *, timeout):
        raise network_error

    failures = simple_healthcheck.check_health(opener=unavailable)

    assert failures == ["root endpoint could not be reached"]


def test_probe_sanitizes_a_protocol_failure_while_reading_and_closes_response():
    class BrokenResponse(FakeResponse):
        def read1(self, size):
            raise IncompleteRead(b"private response fragment", 100)

    response = BrokenResponse()

    failures = simple_healthcheck.check_health(
        opener=lambda _url, *, timeout: response,
    )

    assert failures == ["root endpoint could not be reached"]
    assert response.closed


def test_probe_stops_reading_a_trickling_response_after_the_latency_deadline():
    class TricklingResponse(FakeResponse):
        def read1(self, size):
            self.read_sizes.append(size)
            return b"x"

    response = TricklingResponse()

    failures = simple_healthcheck.check_health(
        opener=lambda _url, *, timeout: response,
        max_response_time=5,
        clock=iter([10.0, 12.0, 15.0, 15.0]).__next__,
    )

    assert failures == [
        "root endpoint did not return a CouchPotato page",
        "root endpoint took 5.00s (limit 5.00s)",
    ]
    assert response.closed
    assert response.read_sizes == [simple_healthcheck.READ_CHUNK_BYTES]


def test_probe_never_consumes_more_than_the_bounded_response_prefix():
    expected_limit = 64 * 1024
    response = FakeResponse(body=b"x" * (expected_limit + 1))

    failures = simple_healthcheck.check_health(
        opener=lambda _url, *, timeout: response,
        clock=lambda: 10.0,
    )

    assert failures == ["root endpoint did not return a CouchPotato page"]
    assert response.body.tell() == expected_limit
    assert sum(response.read_sizes) == expected_limit
    assert response.closed


def test_probe_reports_a_slow_response():
    failures = simple_healthcheck.check_health(
        opener=lambda _url, *, timeout: FakeResponse(),
        max_response_time=5,
        clock=iter([10.0, 10.0, 15.0]).__next__,
    )

    assert failures == ["root endpoint took 5.00s (limit 5.00s)"]


def test_runner_returns_success_and_reports_a_concise_result(monkeypatch, capsys):
    monkeypatch.setattr(simple_healthcheck, "check_health", lambda: [])

    assert simple_healthcheck.run_health_check() is True
    assert "CouchPotato is responding correctly" in capsys.readouterr().out


def test_runner_returns_failure_and_prints_each_reason(monkeypatch, capsys):
    monkeypatch.setattr(
        simple_healthcheck,
        "check_health",
        lambda: ["root endpoint could not be reached"],
    )

    assert simple_healthcheck.run_health_check() is False
    assert "root endpoint could not be reached" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("opened", "expected_exit"),
    [
        (FakeResponse(), 0),
        (URLError("private upstream detail"), 1),
    ],
)
def test_script_exit_status_matches_the_probe_result(monkeypatch, opened, expected_exit):
    def open_root(_url, *, timeout):
        if isinstance(opened, Exception):
            raise opened
        return opened

    monkeypatch.setattr(urllib.request, "urlopen", open_root)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(simple_healthcheck.__file__, run_name="__main__")

    assert exit_info.value.code == expected_exit
