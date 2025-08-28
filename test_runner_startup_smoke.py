import os
import types

from couchpotato.runner import runCouchPotato, getOptions
from couchpotato.environment import Env


class _DummyHTTPServer:
    def __init__(self, application, no_keep_alive=True, ssl_options=None):
        self.application = application

    def add_socket(self, sock):
        pass

    def listen(self, port, host):
        pass

    def close_all_connections(self):
        pass

    def stop(self):
        pass


class _DummyLoop:
    def start(self):
        # Abort immediately to avoid running the real server loop
        raise SystemExit

    def close(self, all_fds=True):
        pass


def test_runner_prepares_dirs_and_env(monkeypatch, tmp_path):
    base_path = os.path.abspath(os.path.dirname(__file__))
    data_dir = tmp_path.as_posix()
    log_dir = tmp_path.joinpath('logs').as_posix()
    os.makedirs(log_dir, exist_ok=True)

    # Prepare options
    opts = getOptions(['--data_dir', data_dir, '--console_log'])

    # Monkeypatch server + ioloop to prevent real startup
    monkeypatch.setattr('couchpotato.runner.HTTPServer', _DummyHTTPServer)

    dummy_mod = types.SimpleNamespace(current=lambda: _DummyLoop())
    monkeypatch.setattr('tornado.ioloop', dummy_mod, raising=True)

    # Execute and expect SystemExit from dummy loop
    try:
        runCouchPotato(opts, base_path, [], data_dir=data_dir, log_dir=log_dir, Env=Env)
    except SystemExit:
        pass

    # Validate directories were created
    assert os.path.isdir(os.path.join(data_dir, 'database'))
    assert os.path.isdir(os.path.join(data_dir, 'cache'))
    assert os.path.isdir(os.path.join(data_dir, 'cache', 'python'))

    # Validate Env has expected paths
    assert Env.get('data_dir') == data_dir
    assert Env.get('app_dir')
    assert Env.get('log_path').endswith('CouchPotato.log')

