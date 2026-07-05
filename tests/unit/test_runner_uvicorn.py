"""Regression test for REG-003 item 3: api_key must not be leaked via uvicorn's
access log.

CouchPotato authenticates the API via a key embedded in the URL path (see
CLAUDE.md "Known Technical Debt"). Uvicorn's default access log writes every
request path -- including that key -- to stdout, which lands in `docker
logs`. `couchpotato/runner.py` must start uvicorn with `access_log=False`.
"""
import uvicorn

from couchpotato.runner import _run_uvicorn


def test_run_uvicorn_disables_access_log(monkeypatch):
    calls = {}

    def fake_run(application, **kwargs):
        calls['application'] = application
        calls.update(kwargs)

    monkeypatch.setattr(uvicorn, 'run', fake_run)

    config = {
        'host': '0.0.0.0',
        'port': 5050,
        'use_reloader': False,
        'ssl_cert': None,
        'ssl_key': None,
    }

    _run_uvicorn(application=object(), config=config, debug=False)

    assert calls.get('access_log') is False


def test_run_uvicorn_passes_through_ssl_kwargs_when_configured(monkeypatch):
    calls = {}

    def fake_run(application, **kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(uvicorn, 'run', fake_run)

    config = {
        'host': '0.0.0.0',
        'port': 5050,
        'use_reloader': False,
        'ssl_cert': '/tmp/cert.pem',
        'ssl_key': '/tmp/key.pem',
    }

    _run_uvicorn(application=object(), config=config, debug=True)

    assert calls.get('access_log') is False
    assert calls.get('ssl_certfile') == '/tmp/cert.pem'
    assert calls.get('ssl_keyfile') == '/tmp/key.pem'
    assert calls.get('log_level') == 'debug'
