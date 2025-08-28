import os
import sys
import pytest


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

