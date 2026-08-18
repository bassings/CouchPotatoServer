"""Shared pytest fixtures for CouchPotatoServer test suite."""
import os as _os

# ---------------------------------------------------------------------------
# Remove git's location variables from the ENTIRE test process, once, before
# anything is collected.
#
# This is the layer that actually closes the class, and it exists because
# per-call sanitisation did not. Git exports GIT_DIR into hook subprocesses
# launched from a linked worktree; pre-push runs the suite; and a test that
# shells out to git then operates on the REAL repository instead of its cwd
# -- `git init` in a tmp dir silently re-inits the repo GIT_DIR names. That
# corrupted this repository twice on 2026-08-18.
#
# The first fix sanitised each call site and added an AST guard to enforce it.
# That guard was then wrong FOUR times: it missed aliased imports
# (`subprocess as sp`), it missed a subdirectory, it accepted any `env=`
# whether sanitised or not, and it could not see argv built by an
# `*args`-forwarding lambda -- a shape with a live unsanitised instance
# sitting in `test_next_beta_version.py`. Policing call SHAPES is a losing
# game: every wrapper, alias and lambda is a new spelling.
#
# So remove the hazard instead of policing the callers. With these unset in
# `os.environ`, every subprocess inherits a clean environment by construction,
# whatever shape the call takes and whether or not its author ever heard of
# this module. `sanitized_git_env()` and the AST guard remain as defence in
# depth, not as the primary protection.
#
# Safe to do unconditionally: nothing in this suite reads GIT_DIR, and git
# falls back to discovery from `cwd`, which is what every call already
# intends. Tests that mean to query the real repo pass `cwd=REPO_ROOT` and
# keep working.
for _var in (
    'GIT_DIR',
    'GIT_WORK_TREE',
    'GIT_INDEX_FILE',
    'GIT_OBJECT_DIRECTORY',
    'GIT_COMMON_DIR',
    'GIT_ALTERNATE_OBJECT_DIRECTORIES',
):
    _os.environ.pop(_var, None)

import json
import os
import sys
import tempfile
import shutil
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root and libs are on path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, 'libs'))

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


@pytest.fixture
def fixtures_dir():
    """Return the path to the test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def sample_data():
    """Load and return the sample_data.json fixture."""
    with open(os.path.join(FIXTURES_DIR, 'sample_data.json'), 'r') as f:
        return json.load(f)


@pytest.fixture
def temp_dir():
    """Provide a temporary directory, cleaned up after test."""
    d = tempfile.mkdtemp(prefix='cp_test_')
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def temp_db_path(temp_dir):
    """Provide a path for a temporary database directory."""
    db_path = os.path.join(temp_dir, 'database')
    os.makedirs(db_path, exist_ok=True)
    return db_path


@pytest.fixture
def mock_event_system():
    """Mock the CouchPotato event system (addEvent/fireEvent)."""
    fired = []
    listeners = {}

    def mock_add_event(name, handler, priority=100):
        if name not in listeners:
            listeners[name] = []
        listeners[name].append({'handler': handler, 'priority': priority})

    def mock_fire_event(name, *args, **kwargs):
        fired.append({'name': name, 'args': args, 'kwargs': kwargs})
        results = []
        for listener in listeners.get(name, []):
            try:
                results.append(listener['handler'](*args, **kwargs))
            except Exception:
                pass
        if kwargs.get('single'):
            return results[0] if results else None
        return results

    mock = MagicMock()
    mock.addEvent = mock_add_event
    mock.fireEvent = mock_fire_event
    mock.fired = fired
    mock.listeners = listeners
    return mock


@pytest.fixture
def mock_http(monkeypatch):
    """Mock HTTP requests via unittest.mock. Returns a configurable mock."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{}'
    mock_response.json.return_value = {}
    mock_response.content = b'{}'

    mock_urlopen = MagicMock(return_value=mock_response)
    return {'response': mock_response, 'urlopen': mock_urlopen}


@pytest.fixture
def config_file(temp_dir):
    """Create a temporary settings.conf file."""
    config_path = os.path.join(temp_dir, 'settings.conf')
    with open(config_path, 'w') as f:
        f.write('[core]\n')
        f.write('debug = 0\n')
        f.write('development = 0\n')
        f.write('data_dir = %s\n' % temp_dir)
        f.write('permission_file = 0644\n')
        f.write('permission_folder = 0755\n')
    return config_path
