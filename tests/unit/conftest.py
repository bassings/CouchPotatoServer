"""Shared fixtures for unit tests.

On Python 3.10, `patch('couchpotato.api.addApiView', create=True)` fails because
`couchpotato.api` resolves to the `api = {}` dict (imported into couchpotato.__init__)
rather than the api module. This conftest ensures addApiView is patchable by replacing
the problematic patch targets with direct module-level mocks.
"""
import pytest

from couchpotato.core.logger import reset_log_suppression


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
