"""Regression test for REG-003 item 3: api_key must not be leaked via uvicorn's
access log.

CouchPotato authenticates the API via a key embedded in the URL path (see
CLAUDE.md "Known Technical Debt"). Uvicorn's default access log writes every
request path -- including that key -- to stdout, which lands in `docker
logs`. `couchpotato/runner.py` must start uvicorn with `access_log=False`.

Also covers the `--port` CLI argument (T1.7 prerequisite, AC-OPS-20/21,
AC-SEC-16): a server-per-worker E2E harness cannot express "start on port N"
otherwise, because the port has only ever come from config.ini.
"""
from unittest.mock import MagicMock

import pytest
import uvicorn

from couchpotato.runner import (
    _resolve_port,
    _run_uvicorn,
    _start_uvicorn_or_exit,
    getOptions,
)


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


class TestGetOptionsPortArgument:
    """`--port` (AC-OPS-20/21). Omitting it must be byte-identical to today:
    `options.port` is `None`, and nothing downstream can tell `--port` was
    ever added -- config.ini keeps deciding the port, exactly as before this
    change.
    """

    def test_port_omitted_defaults_to_none(self):
        options = getOptions(['--data_dir', '/tmp/cp-test-data'])
        assert options.port is None

    def test_port_accepts_a_valid_value(self):
        options = getOptions(['--data_dir', '/tmp/cp-test-data', '--port', '5099'])
        assert options.port == 5099

    def test_port_rejects_a_non_integer_and_names_it(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            getOptions(['--data_dir', '/tmp/cp-test-data', '--port', 'not-a-port'])
        assert exc_info.value.code != 0
        stderr = capsys.readouterr().err
        assert 'not-a-port' in stderr

    @pytest.mark.parametrize('bad_port', ['0', '-1', '65536', '999999'])
    def test_port_rejects_out_of_range_values_and_names_them(self, bad_port, capsys):
        with pytest.raises(SystemExit) as exc_info:
            getOptions(['--data_dir', '/tmp/cp-test-data', '--port', bad_port])
        assert exc_info.value.code != 0
        stderr = capsys.readouterr().err
        assert bad_port in stderr


class TestResolvePort:
    """`_resolve_port` is the precedence rule itself, isolated from argparse
    and from Env/config.ini so it is trivial to pin both directions
    (AC-OPS-21).
    """

    def test_cli_port_wins_when_given(self):
        assert _resolve_port(cli_port=5099, configured_port=5050) == 5099

    def test_configured_port_wins_when_cli_port_omitted(self):
        # The byte-identical-when-omitted contract (AC-OPS-20): None means
        # "no --port was given", so config.ini's value must pass through
        # completely unchanged -- including values a real install might have,
        # not just the 5050 default.
        assert _resolve_port(cli_port=None, configured_port=8118) == 8118


class TestStartUvicornOrExit:
    """AC-OPS-21: an invalid or already-bound port must fail LOUDLY at
    startup, naming the port, rather than uvicorn.run's exception being
    logged and swallowed while the process exits 0 as if it had started.

    A silent "logged but exit 0" failure is exactly what would reintroduce
    the shared-server coupling `--port` exists to remove: an E2E harness
    spawning one server per worker would see every worker report success
    and only discover the missing server when specs start timing out,
    naming a URL instead of the real cause (AC-QA-58's failure mode).
    """

    def _config(self, port=5099):
        return {
            'use_reloader': False,
            'port': port,
            'host': '0.0.0.0',
            'ssl_cert': None,
            'ssl_key': None,
        }

    def test_exits_nonzero_and_names_the_port_on_bind_conflict(self, monkeypatch):
        def fake_run(application, config, debug):
            err = OSError('Address already in use')
            err.errno = 48
            raise err

        monkeypatch.setattr(
            'couchpotato.runner._run_uvicorn', fake_run
        )
        log = MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            _start_uvicorn_or_exit(object(), self._config(port=5099), False, log)

        assert exc_info.value.code != 0
        logged = ' '.join(
            '%s' % (call.args,) for call in log.error.call_args_list
        )
        assert '5099' in logged

    def test_exits_nonzero_rather_than_silently_returning_on_any_start_failure(self, monkeypatch):
        # Not just the errno-48 case: ANY failure to start must not look
        # like a successful, silent no-op -- that is the "falls back
        # silently" failure mode AC-OPS-21 explicitly rejects.
        def fake_run(application, config, debug):
            raise RuntimeError('boom')

        monkeypatch.setattr(
            'couchpotato.runner._run_uvicorn', fake_run
        )
        log = MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            _start_uvicorn_or_exit(object(), self._config(port=6100), False, log)

        assert exc_info.value.code != 0

    def test_does_not_exit_when_uvicorn_starts_cleanly(self, monkeypatch):
        monkeypatch.setattr('couchpotato.runner._run_uvicorn', lambda *a, **k: None)
        log = MagicMock()

        # Must not raise.
        _start_uvicorn_or_exit(object(), self._config(), False, log)
        log.error.assert_not_called()
