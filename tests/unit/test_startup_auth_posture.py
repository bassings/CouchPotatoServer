"""Startup says, once, what authentication it is actually enforcing.

AC-OPS-47, and review finding M8. Only the auth-OFF direction logged, and that
WARNING predates this branch. With authentication ON the sole statement of
posture was `ensure_session_secret`'s first-creation INFO -- which AC-OPS-41
deliberately silences from the second boot onward, so a restarted instance said
nothing at all.

At 3am the first two questions are "is this instance actually requiring a
login" and "why is the browser not keeping the cookie". Both were answerable
only by inferring from an ABSENT warning plus a `config.ini` grep.

`secure` matters in the same line because it is derived, not configured: half a
TLS pair silently yields a non-Secure cookie, and the reverse yields an
undeliverable one whose only symptom is a login loop. Without a startup value
there is nothing to compare the observed loop against.

`logging.INFO` as an INT, never the string: `couchpotato/core/logger.py` calls
`logging.addLevelName(21, 'INFO')`, so `caplog.at_level('INFO')` resolves to 21
and drops every real INFO record.
"""
import logging

import pytest

from couchpotato.environment import Env


@pytest.fixture
def env(tmp_path):
    Env.set('app_dir', str(tmp_path))
    Env.set('data_dir', str(tmp_path))
    Env.set('web_base', '/')
    yield
    Env.set('web_base', '/')


def _posture_records(caplog):
    return [r for r in caplog.records if r.levelno >= logging.INFO]


class TestStartupStatesThePosture:

    def test_an_authenticated_instance_says_so_exactly_once(self, env, caplog, monkeypatch):
        import couchpotato
        import couchpotato.runner as runner

        monkeypatch.setattr(couchpotato, 'auth_is_required', lambda: True)
        monkeypatch.setattr(couchpotato, 'session_cookie_attributes',
                            lambda: {'httponly': True, 'samesite': 'lax',
                                     'path': '/', 'secure': False})

        with caplog.at_level(logging.INFO):
            runner.log_authentication_posture()

        records = _posture_records(caplog)
        assert len(records) == 1, (
            'expected exactly one posture record, got %d: %s'
            % (len(records), [r.getMessage() for r in records]))

        message = records[0].getMessage().lower()
        assert 'authentication' in message or 'login' in message, message
        assert 'secure' in message, (
            'the posture line does not state the resolved Secure value, which '
            'is the one thing a login loop needs comparing against: %s' % message)

    def test_it_names_the_resolved_secure_value_truthfully(self, env, caplog, monkeypatch):
        """Both directions, because a line that always says the same thing is
        not a measurement."""
        import couchpotato
        import couchpotato.runner as runner

        monkeypatch.setattr(couchpotato, 'auth_is_required', lambda: True)

        seen = {}
        for secure in (True, False):
            monkeypatch.setattr(couchpotato, 'session_cookie_attributes',
                                lambda secure=secure: {'secure': secure})
            caplog.clear()
            with caplog.at_level(logging.INFO):
                runner.log_authentication_posture()
            seen[secure] = _posture_records(caplog)[0].getMessage()

        assert seen[True] != seen[False], (
            'the posture line reads identically whether Secure is on or off, '
            'so it states nothing: %r' % seen[True])

    def test_an_open_instance_still_warns(self, env, caplog, monkeypatch):
        """The pre-existing behaviour, unchanged. An unauthenticated instance
        is a decision and the log is where the operator checks it."""
        import couchpotato
        import couchpotato.runner as runner

        monkeypatch.setattr(couchpotato, 'auth_is_required', lambda: False)

        with caplog.at_level(logging.INFO):
            runner.log_authentication_posture()

        records = _posture_records(caplog)
        assert len(records) == 1, [r.getMessage() for r in records]
        assert records[0].levelno >= logging.WARNING, (
            'an open instance must warn, not merely inform')
        assert 'disabled' in records[0].getMessage().lower()


class TestItSurvivesTheRealStartupEnvironment:
    """The tests above all monkeypatch `session_cookie_attributes`, and that is
    exactly what hid a crash.

    The first version of this feature called `log_authentication_posture()`
    ABOVE the line that sets `web_base`. `session_cookie_attributes()` reads
    `Env.get('web_base')`, so the real server died on boot::

        AttributeError: type object 'Env' has no attribute '_web_base'
          runner.py  log_authentication_posture()
          __init__.py  'path': Env.get('web_base') or '/',

    Every unit test passed, because each one replaced the function that
    breaks. Only the E2E -- which starts a real server -- caught it. So one
    test here drives the REAL thing.
    """

    def test_the_real_attributes_function_is_callable_when_it_is_called(self, env, caplog, monkeypatch):
        import couchpotato
        import couchpotato.runner as runner

        monkeypatch.setattr(couchpotato, 'auth_is_required', lambda: True)

        # No patch on session_cookie_attributes: this must work for real.
        with caplog.at_level(logging.INFO):
            runner.log_authentication_posture()

        assert _posture_records(caplog), 'the real call produced no record'

    def test_the_call_site_is_below_the_web_base_assignment(self):
        """Pins the ORDERING, which no executed test can see.

        `runner()` is not callable in a unit test, so the only way to keep the
        two lines in the right order is to read the source -- the same
        technique `test_auth_required_gate.py` uses for the migration block,
        and for the same reason.
        """
        import inspect

        source = inspect.getsource(runner_module()).splitlines()

        def line_of(needle):
            hits = [i for i, line in enumerate(source)
                    if needle in line and not line.strip().startswith('#')]
            assert len(hits) == 1, 'expected one %r, found %d' % (needle, len(hits))
            return hits[0]

        assert line_of("Env.set('web_base', web_base)") < line_of('    log_authentication_posture()'), (
            'log_authentication_posture() runs before web_base is set. It reads '
            'session_cookie_attributes(), which reads Env.get("web_base"), so '
            'the server will die on boot with AttributeError -- and no unit '
            'test will notice, because they patch that function.'
        )


def runner_module():
    import couchpotato.runner as runner
    return runner
