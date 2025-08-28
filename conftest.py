import os
import sys
import pytest
import threading

# Compatibility shim for APScheduler 2.x on modern Python
if not hasattr(threading.Thread, 'isAlive') and hasattr(threading.Thread, 'is_alive'):
    threading.Thread.isAlive = threading.Thread.is_alive  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _ensure_libs_on_path(monkeypatch):
    base = os.path.abspath(os.path.dirname(__file__))
    libs = os.path.join(base, 'libs')
    sys.path.insert(0, libs)
    yield
    try:
        sys.path.remove(libs)
    except ValueError:
        pass


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: integration tests")
    config.addinivalue_line("markers", "e2e: end-to-end tests")
