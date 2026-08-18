"""Shared fixtures for unit tests.

On Python 3.10, `patch('couchpotato.api.addApiView', create=True)` fails because
`couchpotato.api` resolves to the `api = {}` dict (imported into couchpotato.__init__)
rather than the api module. This conftest ensures addApiView is patchable by replacing
the problematic patch targets with direct module-level mocks.
"""
import os

import pytest

from couchpotato.core.logger import reset_log_suppression

# Git sets GIT_DIR (and its siblings below) in the environment of hook
# subprocesses launched from a `git worktree` checkout -- but not from the
# main checkout. `pre-push` runs `make verify`, which runs this suite, so a
# push made from a worktree hands every test process a GIT_DIR naming that
# worktree's real `.git`.
#
# Any test that shells out to `git init`/`commit`/`checkout -b` inside a
# throwaway `tmp_path` MUST strip these first: with GIT_DIR set, `git init`
# in a fresh directory does not create a repo there, it RE-INITIALISES the
# repo GIT_DIR already points at, and every later commit/checkout in the
# fixture lands there too. T31 follow-up: this is exactly how the real
# developer checkout got a fixture branch, two fixture commits, and
# `core.bare` flipped to true.
#
# Deliberately a plain function, not a fixture and not autouse: importing it
# is each caller's explicit choice, so it carries none of the blast radius
# the autouse fixtures above do across this file's ~150+ dependents. See
# `tests/unit/test_fixtures_do_not_leak_gitdir.py`.
GIT_LOCATION_ENV_VARS = (
    'GIT_DIR',
    'GIT_WORK_TREE',
    'GIT_INDEX_FILE',
    'GIT_OBJECT_DIRECTORY',
    'GIT_COMMON_DIR',
    'GIT_ALTERNATE_OBJECT_DIRECTORIES',
)


def assert_git_dir_is(directory, env=None):
    """Assert git, run in `directory`, resolves its git dir INSIDE `directory`.

    Defence in depth for the GIT_DIR leak: verifies the EFFECT rather than
    trusting that the input was sanitised. Extracted from the two `repo`
    fixtures so it can be tested on its own -- inline, deleting it failed
    nothing, because the per-call sanitisation already kept every test green.
    Two layers where only one is proven look exactly like two working layers
    from a green run.

    Compares against the DIRECTORY, never against `directory/.git`, because in
    the case this exists to catch that path was never created -- git
    re-initialised the repo GIT_DIR named instead. Resolving through a child
    that does not exist is how this assertion reports the wrong thing on the
    one path that needs it.

    Proven by three mutations, not one, because they answer different
    questions:

        neuter this assertion    ->  1 failed              is it guarded?
        make it reject anything  ->  2 failed, 53 errors   is it on the code path?
        neuter the sanitisation  ->  1 failed              is the OTHER layer guarded?

    The middle one is the check most easily skipped. A guard can be guarded
    and still be dead code that is never reached; only forcing it to reject
    everything shows it actually runs -- here, for every test that takes the
    `repo` fixture.
    """
    import subprocess as _sp
    absolute_git_dir = _sp.run(
        ['git', 'rev-parse', '--absolute-git-dir'], cwd=str(directory),
        check=True, capture_output=True, text=True,
        env=sanitized_git_env() if env is None else env,
    ).stdout.strip()
    resolved = os.path.realpath(absolute_git_dir)
    root = os.path.realpath(str(directory))
    assert resolved == root or resolved.startswith(root + os.sep), (
        'git operations here are not targeting the throwaway directory '
        '(git dir resolved to %s, outside %s) -- refusing to continue rather '
        'than risk running further git commands against a real repository'
        % (absolute_git_dir, root)
    )


def sanitized_git_env():
    """A copy of the current environment with git's location variables
    removed -- pass as `env=` to any subprocess `git` call (or any script
    that itself shells out to `git`, e.g. `needs_e2e.sh`) that must operate
    on an explicit `cwd` rather than wherever the ambient GIT_DIR points."""
    env = os.environ.copy()
    for var in GIT_LOCATION_ENV_VARS:
        env.pop(var, None)
    return env


@pytest.fixture(autouse=True)
def _isolate_log_suppression():
    """AC-OPS-45's window is process-wide state, so reset it between tests.

    Without this, the FIRST test to provoke a bounded auth ERROR emits it and
    every later test in the same process sees the suppression notice instead of
    the message it is asserting on. That surfaced immediately -- five
    parametrised cases in `test_auth_required_lockout_guard.py` and one in
    `test_session_secret_store.py` went red on the second parameter onward,
    with a failure that reads like "the code stopped logging" rather than "the
    previous test used up the window". Order-dependent tests are the shape this
    repo has already been bitten by (`Env` contamination across the suite), so
    the reset is automatic rather than something each test must remember.

    This resets TEST state only. It does not change what the application does:
    the bound is still proven inside a single test in
    `tests/unit/test_auth_log_flooding.py`, which does 1,000 requests without
    resetting anything.
    """
    reset_log_suppression()
    yield
    reset_log_suppression()


@pytest.fixture(autouse=True)
def _isolate_session_secret_state():
    """AC-QA-19's "have we ever held a secret?" flag is process-wide too.

    It is the only thing that can tell a first-ever bootstrap from a
    regeneration, because a deleted property row leaves the database in exactly
    the state a fresh install is in. Being process-wide, the first test to
    bootstrap a secret would otherwise turn every later test's INFO into a
    WARNING -- which is spec gap 15 happening a second time, so it gets the
    same automatic reset rather than a note asking people to remember.
    """
    from couchpotato import reset_session_secret_state

    reset_session_secret_state()
    yield
    reset_session_secret_state()
