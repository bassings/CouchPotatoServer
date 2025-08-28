import os
from couchpotato.environment import Env


def test_env_get_set_roundtrip():
    original = Env.get('appname')
    Env.set('appname', 'TESTAPP')
    try:
        assert Env.get('appname') == 'TESTAPP'
    finally:
        Env.set('appname', original)


def test_env_get_permission_parsing(monkeypatch):
    # Simulate settings returning specific permission strings
    class DummySettings:
        def get(self, key, default='', section='core', type=None):
            return '0755'

    orig = Env.get('settings')
    Env.set('settings', DummySettings())
    try:
        perm = Env.getPermission('dir')
        assert perm == 0o755
    finally:
        Env.set('settings', orig)


def test_env_getpid_has_pid():
    pid_info = Env.getPid()
    assert isinstance(pid_info, str)
    assert str(os.getpid()) in pid_info
