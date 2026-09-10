#!/usr/bin/env python3
"""The one place a standalone script scrubs `GIT_*` before shelling out to git.

`cwd=` does NOT win over `GIT_DIR`. Measured on this repo: `git ls-files`
lists 795 files normally and 1 with a foreign `GIT_DIR` set, and a caller
that trusts that list then reports "passed" having examined a different
repository. Not a crash and not a skip, either of which would be visible.

Shared by `scripts/check_test_traps.py` and `scripts/mutation_changed.py` so
the scrub has exactly one definition. Two copies of a security-relevant
helper is how one of them drifts and nobody notices -- which is exactly what
happened before this module existed: `check_test_traps.py` scrubbed its own
`git ls-files` call (#347) while `mutation_changed.py`'s four git call sites
stayed unscrubbed (#348), because the fix for the first did not reach the
second.

`tests/unit/conftest.py` carries an independent `sanitized_git_env()` for the
test suite's own git fixtures (`tests/conftest.py`'s `GIT_IDENTITY_ENV_PREFIXES`).
That copy is deliberate, not an oversight: a script cannot import the test
suite's conftest, and `tests/unit/test_check_test_traps.py`'s
`test_the_scripts_scrub_matches_the_suites_rule` pins the two allow-lists
together so they cannot drift apart silently.
"""

from __future__ import annotations

import os

#: Commit-identity variables, the only `GIT_*` names safe to pass through:
#: they change what a commit RECORDS, never where an operation LANDS or what
#: git EXECUTES. Same rule and same reasoning as `tests/conftest.py`, and
#: `test_the_scripts_scrub_matches_the_suites_rule` fails if the two drift.
GIT_IDENTITY_PREFIXES = ('GIT_AUTHOR_', 'GIT_COMMITTER_')


def git_env():
    """The environment with git's whole `GIT_*` namespace stripped.

    `cwd=` does NOT win over `GIT_DIR`. Measured on this repo: `git ls-files`
    lists 795 files normally and 1 with a foreign `GIT_DIR` set, and a caller
    that trusts that list then reports "passed". Not a crash and not a skip,
    either of which would be visible: a confident green about a different
    repository, from a script whose whole job is stopping false greens.

    Live rather than theoretical. `make check-traps` and `make
    mutation-changed` both run in the pre-push gate, git exports `GIT_DIR`
    into hook subprocesses launched from a linked worktree, and a lot of
    work here happens in worktrees. The same leak corrupted this repository
    twice on 2026-08-18, which is why `tests/conftest.py` pops the namespace
    process-wide before collection. That protects this code when pytest
    imports it and NOT when a script runs standalone, which is the gap this
    module closes.

    A namespace strip rather than a denylist of known-dangerous names,
    because a list of what redirects the repository would never have named
    GIT_CONFIG_PARAMETERS or GIT_TEMPLATE_DIR.
    """
    env = os.environ.copy()
    for key in list(env):
        if key.startswith('GIT_') and not key.startswith(GIT_IDENTITY_PREFIXES):
            env.pop(key, None)
    return env
