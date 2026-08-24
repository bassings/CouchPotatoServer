"""Shared pytest fixtures for CouchPotatoServer test suite."""
import os as _os

# ---------------------------------------------------------------------------
# Remove git's entire GIT_* namespace from the ENTIRE test process, once,
# before anything is collected -- except the commit-identity variables in
# GIT_IDENTITY_ENV_PREFIXES.
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
# this module. `sanitized_git_env()` (in `tests/unit/conftest.py`) and the
# AST guard remain as defence in depth, not as the primary protection.
#
# T57 follow-up: this loop originally denied the same six "location"
# variables `sanitized_git_env()` used to deny, on the same wrong axis --
# "what redirects the repository". That missed GIT_CONFIG_PARAMETERS
# (exported by `git -c foo=bar <cmd>` into every subprocess it spawns) and
# GIT_TEMPLATE_DIR (arbitrary code execution via a hook copied from the
# template dir and run during the next commit -- not a location variable at
# all, so no denylist on that axis would ever have named it). See the T57
# comment in `tests/unit/conftest.py` above GIT_IDENTITY_ENV_PREFIXES for the
# full argument and the measurement behind it.
#
# The rule -- strip the whole GIT_* namespace, keep only commit identity --
# is defined ONCE, in GIT_IDENTITY_ENV_PREFIXES below, and both this
# process-wide pop and `sanitized_git_env()`'s per-call copy apply it. The
# two APPLICATIONS stay separate on purpose: this one mutates `os.environ`
# directly for the whole process and must run before anything else is
# imported or collected, while `sanitized_git_env()` returns a fresh copy on
# each call for an explicit `env=`. Forcing them into one shared function
# would make one of the two shapes wrong; sharing the tuple is what actually
# matters, because that is the part that would otherwise drift.
#
# Safe to do unconditionally: nothing in this suite reads ANY GIT_* variable
# -- swept 2026-08-20 across the whole tree with
# `grep -rn "GIT_" --include='*.py' --include='*.sh' --include='*.yml' \
#   --include='*.yaml' .`, excluding `.venv`/`.git`, and again with no
# extension filter at all; every hit outside the conftest/guard files
# themselves is documentation in `specs/REMEDIATION-2026-08.md` -- and git
# falls back to discovery from `cwd`, which is what every call already
# intends. Tests that mean to query the real repo pass `cwd=REPO_ROOT` and
# keep working. Commit identity is kept back because the RULE says it is
# safe to (it changes what a commit records, not where an operation lands or
# what runs), not because anything currently measured relies on inheriting
# it ambiently -- every commit this suite scripts today sets identity
# explicitly via `git config user.*` or `-c`, so the allowlist is a floor
# for a future caller, not a fix for an existing dependency.
#
# What that carve-out COSTS, recorded because review measured it rather than
# leaving it implied. `git commit` exports GIT_AUTHOR_NAME/EMAIL/DATE into
# its own hook environment, and for git, environment beats `git config`. So
# in that one scenario the allowlist lets an ambient identity OVERRIDE the
# identity a fixture set explicitly, and an ambient malformed
# GIT_COMMITTER_DATE fails every scripted commit outright. Neither is live:
# `.githooks/` holds only `pre-push`, nothing in the tree sets these, and no
# test asserts on the author, committer or date of a commit made by `git`.
# `test_updater.py:112` does assert on `author_time`, which looks like a
# counter-example and is not: that commit is made by dulwich in-process with
# author and committer passed explicitly, and dulwich was measured ignoring
# the ambient values outright. The strict alternative --
# strip GIT_* with no exception at all -- is one rule instead of a rule plus
# an exception, and closes the last GIT_* class that can alter a fixture
# commit. It is not taken here because T57 specified the identity carve-out
# and it is the honest reading of the axis this rule is built on, but the
# trade is real and belongs in writing rather than in a reviewer's head.
GIT_IDENTITY_ENV_PREFIXES = (
    'GIT_AUTHOR_',
    'GIT_COMMITTER_',
)
for _var in list(_os.environ):
    if _var.startswith('GIT_') and not _var.startswith(GIT_IDENTITY_ENV_PREFIXES):
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
