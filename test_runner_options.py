import os
from couchpotato.runner import getOptions


def test_get_options_defaults_tmpdir(tmp_path):
    # No args -> derives defaults from getDataDir() but ensures config/pid under expanded data_dir
    # Simulate with explicit data_dir to avoid relying on user env
    data_dir = tmp_path.as_posix()
    opts = getOptions(['--data_dir', data_dir])

    assert opts.data_dir == data_dir
    assert opts.config_file == os.path.join(data_dir, 'settings.conf')
    assert opts.pid_file == os.path.join(data_dir, 'couchpotato.pid')
    assert not opts.debug
    assert opts.console_log in (False, None)
    assert opts.quiet in (False, None)
    assert opts.daemon in (False, None)


def test_get_options_custom_paths(tmp_path):
    data_dir = tmp_path.as_posix()
    conf = tmp_path.joinpath('my.conf').as_posix()
    pid = tmp_path.joinpath('my.pid').as_posix()
    opts = getOptions(['--data_dir', data_dir, '--config_file', conf, '--pid_file', pid, '--debug', '--console_log'])

    assert opts.data_dir == data_dir
    assert opts.config_file == conf
    assert opts.pid_file == pid
    assert opts.debug is True
    assert opts.console_log is True

