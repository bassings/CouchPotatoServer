"""Shared fixtures for unit tests.

On Python 3.10, `patch('couchpotato.api.addApiView', create=True)` fails because
`couchpotato.api` resolves to the `api = {}` dict (imported into couchpotato.__init__)
rather than the api module. This conftest ensures addApiView is patchable by replacing
the problematic patch targets with direct module-level mocks.
"""
import os

import pytest

from couchpotato.core.logger import reset_log_suppression

# Git sets GIT_DIR (and its siblings) in the environment of hook subprocesses
# launched from a `git worktree` checkout -- but not from the main checkout.
# `pre-push` runs `make verify`, which runs this suite, so a push made from a
# worktree hands every test process a GIT_DIR naming that worktree's real
# `.git`.
#
# Any test that shells out to `git init`/`commit`/`checkout -b` inside a
# throwaway `tmp_path` MUST strip these first: with GIT_DIR set, `git init`
# in a fresh directory does not create a repo there, it RE-INITIALISES the
# repo GIT_DIR already points at, and every later commit/checkout in the
# fixture lands there too. T31 follow-up: this is exactly how the real
# developer checkout got a fixture branch, two fixture commits, and
# `core.bare` flipped to true.
#
# T57 follow-up: the original fix here was a DENYLIST of six "location"
# variables -- GIT_DIR and its siblings -- built on the axis "what redirects
# the repository". That is the wrong axis, and it missed two real escapes:
#
#   1. GIT_CONFIG_PARAMETERS. `git -c foo=bar <cmd>` EXPORTS this into the
#      environment of every subprocess it spawns, so `git -c ... push` run
#      from a worktree hands the suite arbitrary config, which then rides
#      into every later git call the suite makes -- same trigger as the
#      GIT_DIR leak above, one name the six-item list never had.
#
#   2. GIT_TEMPLATE_DIR is not a location variable at all -- it names a
#      directory whose `hooks/` are COPIED into every repo `git init`
#      creates from that template, and then RUN. No denylist built on "what
#      redirects the repository" would ever have contained it, because
#      redirection was never the axis that made it dangerous. Measured, not
#      reasoned: a template dir with an executable `hooks/pre-commit`, then
#      `GIT_TEMPLATE_DIR=../tmpl git init -q .` followed by a seed commit,
#      copied the hook into the new repo AND EXECUTED it during that commit.
#      Every throwaway repo this suite creates would have run it.
#
# The property that actually matters is not "what redirects the repository",
# and not quite "what git exports" either -- GIT_TEMPLATE_DIR is dangerous
# and git does not export it, the operator (or an attacker) sets it. The
# property is what git READS from the environment, which is a superset of
# both. A denylist on that axis can never be finished: it is wrong again the
# day git adds a new variable, and nothing announces that a new one shipped.
# A namespace rule excludes the new one automatically, the day it ships,
# with no update required here.
#
# So `sanitized_git_env()` now strips the WHOLE `GIT_*` namespace and allows
# back only the commit-identity variables named in
# GIT_IDENTITY_ENV_PREFIXES below. Those change what a commit RECORDS
# (author/committer name, email, date), never where an operation LANDS or
# what git EXECUTES, which is the distinction that makes them safe to let
# through.
#
# Deliberately a plain function, not a fixture and not autouse: importing it
# is each caller's explicit choice, so it carries none of the blast radius
# the autouse fixtures above do across this file's ~150+ dependents. See
# `tests/unit/test_fixtures_do_not_leak_gitdir.py` (the GIT_DIR leak and the
# call-site audit) and `tests/unit/test_git_env_namespace_scrub.py` (this
# namespace rule).
GIT_IDENTITY_ENV_PREFIXES = (
    'GIT_AUTHOR_',
    'GIT_COMMITTER_',
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
    """A copy of the current environment with git's entire `GIT_*` namespace
    removed, except the commit-identity variables in
    GIT_IDENTITY_ENV_PREFIXES -- pass as `env=` to any subprocess `git` call
    (or any script that itself shells out to `git`, e.g. `needs_e2e.sh`) that
    must operate on an explicit `cwd` rather than wherever the ambient
    environment redirects or configures it to.

    A namespace strip, not a denylist of known-dangerous names: see the
    comment above GIT_IDENTITY_ENV_PREFIXES for why the axis matters and what
    a fixed list of names misses -- concretely, GIT_CONFIG_PARAMETERS and
    GIT_TEMPLATE_DIR, neither of which a "what redirects the repository"
    denylist would ever have named."""
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('GIT_') and not key.startswith(GIT_IDENTITY_ENV_PREFIXES):
            env.pop(key, None)
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
