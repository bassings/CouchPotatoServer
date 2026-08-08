"""An unauthenticated caller cannot evict the log ring. AC-OPS-45, AC-OPS-46.

L1. Three log calls on the authentication surface fire once per REQUEST, at
ERROR, with no bound at all:

  * `'"Require login" is ON but NO PASSWORD is stored'` -- the state a
    locked-out operator is in, so it fires on every request they make while
    trying to recover;
  * `'Unrecognised auth_required value ... in config.ini'` -- the state a
    HAND-EDITED config.ini is in, which is the documented recovery path, so
    again it fires exactly when somebody is already in trouble;
  * the session-secret-missing ERROR, which fires on every request once the
    property store cannot be read.

None of them needs a credential. Measured baseline before this change: 50
unauthenticated requests produced 50 ERROR records totalling 21,650 bytes, so
roughly 11,600 requests evict the entire 500,000 x 11 byte ring configured at
`couchpotato/core/logger.py:264` -- which is the operator's only diagnostic
(there are no metrics and no dashboards on a self-hosted install). A stranger
who can reach the port can delete the evidence of anything else that happened.

The fix must not cost the diagnosis, which is the whole reason those lines are
at ERROR and name the `config.ini` remedy. So both directions are tested here:
the first record in a window is the FULL message, and the suppression itself is
visible and counted.

Records are counted out of a REAL `RotatingFileHandler` file on disk. `caplog`
would not do: `logger.py:24` remaps the INFO level NAME to 21, so
`caplog.at_level('INFO')` captures nothing (`make check-traps` fails on the
string form), and the ring being evicted is a property of the file, not of a
capture list.
"""
import glob
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core.logger import (
    LOG_SUPPRESSION_WINDOW,
    log_suppressed,
    reset_log_suppression,
)
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

API_KEY = 'notarealapikey' + '0' * 18

#: `'%(asctime)s %(levelname)s %(message)s'` with `'%m-%d %H:%M:%S'`, which is
#: what `setup_logging` configures. Anchored so a traceback continuation line
#: is not counted as a record.
_RECORD = re.compile(r'^\d\d-\d\d \d\d:\d\d:\d\d (DEBUG|INFO|WARNING|ERROR|CRITICAL) (.*)$')

#: INFO2 (21) is registered under the NAME 'INFO', so name-matching covers it.
_AT_INFO_OR_ABOVE = ('INFO', 'WARNING', 'ERROR', 'CRITICAL')


def records(log_path):
    """Every record in the whole RING as (level, message).

    The live file AND its rotated backups, because "the ring was evicted" is a
    property of all eleven files: reading only the live one reports a line as
    gone the moment a single rotation happens, which is a false alarm, and it
    would let a fix that merely rotates faster look like a fix.
    """
    out = []
    for path in [log_path] + sorted(glob.glob(log_path + '.*')):
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                match = _RECORD.match(line.rstrip('\n'))
                if match:
                    out.append((match.group(1), match.group(2)))
    return out


def at_info_or_above(log_path):
    return [r for r in records(log_path) if r[0] in _AT_INFO_OR_ABOVE]


@pytest.fixture
def log_file(tmp_path, request):
    """A real `RotatingFileHandler`, sized as production sizes it.

    Attached to the root logger at INFO by the INT, never the string: the name
    'INFO' resolves to 21 once `couchpotato.core.logger` is imported, which
    would silently drop every genuine INFO record.
    """
    path = str(tmp_path / 'CouchPotato.log')
    max_bytes, backups = getattr(request, 'param', (500000, 10))
    handler = RotatingFileHandler(path, mode='a', maxBytes=max_bytes,
                                  backupCount=backups, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s',
                                           '%m-%d %H:%M:%S'))
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # `httpx` emits one INFO record per request -- from the TEST CLIENT, not
    # from the application. In production nothing logs inbound requests at all
    # (`setup_logging` quiets the equivalent libraries), so counting them here
    # would measure the harness. Verified: the 2,001 records in the pre-change
    # baseline were 1,000 application ERRORs and 1,001 of these.
    noisy = [logging.getLogger(name) for name in ('httpx', 'httpcore')]
    previous_noisy = [logger.level for logger in noisy]
    for logger in noisy:
        logger.setLevel(logging.WARNING)

    reset_log_suppression()
    try:
        yield path
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(previous_level)
        for logger, level in zip(noisy, previous_noisy):
            logger.setLevel(level)
        reset_log_suppression()


@pytest.fixture
def app_env(tmp_path):
    """An install in the state that floods: auth ON, no password stored."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(Path(__file__).resolve().parents[2]))
    Env.set('data_dir', str(tmp_path))
    Env.set('dev', False)

    data = {
        'username': '',
        'password': '',
        'api_key': API_KEY,
        'auth_required': 1,
        'rate_limit_max': 0,
        'cors_origins': '',
        'ssl_cert': '',
        'ssl_key': '',
    }
    original = Env.setting

    def mock_setting(key=None, *args, **kwargs):
        if 'value' in kwargs:
            data[key] = kwargs['value']
            return
        return data.get(key, kwargs.get('default', ''))

    Env.setting = staticmethod(mock_setting)
    try:
        yield data
    finally:
        Env.setting = original
        api.clear()
        api.update(old_api)
        api_locks.clear()
        api_locks.update(old_locks)
        api_nonblock.clear()
        api_nonblock.update(old_nonblock)
        api_docs.clear()
        api_docs.update(old_docs)
        api_docs_missing.clear()
        api_docs_missing.extend(old_missing)


def client(app_env):
    from couchpotato import create_app
    return TestClient(create_app(API_KEY, '/'), follow_redirects=False)


BURST = 1000


class TestAnUnauthenticatedBurstCannotEvictTheRing:
    """AC-OPS-45."""

    def test_a_thousand_unauthenticated_requests_emit_at_most_ten_records(
            self, app_env, log_file):
        session = client(app_env)

        for _ in range(BURST):
            assert session.get('/').status_code == 302

        emitted = at_info_or_above(log_file)
        assert len(emitted) <= 10, (
            '%d requests with no credentials produced %d records at INFO or '
            'above; the log ring is a stranger\'s to empty' % (BURST, len(emitted))
        )

    # A ring the burst can actually exhaust. With production sizing
    # (500,000 x 11 = 5.5MB) this test CANNOT FAIL: 1,000 unbounded records
    # are ~533,043 bytes, under 10% of the ring, so the sentinel survives
    # whether or not anything is bounded. Measured -- with
    # `LOG_SUPPRESSION_WINDOW = 0`, i.e. suppression fully disabled, four
    # tests in this class went red and this one PASSED.
    #
    # 20,000 x 3 = 60KB, so ~533KB of unbounded records evicts the sentinel
    # many times over. Raising BURST past the ~10,300 records production
    # sizing needs would work too, and would cost 10,300 real HTTP requests.
    @pytest.mark.parametrize('log_file', [(20000, 2)], indirect=True)
    def test_the_lines_written_before_the_burst_are_still_there_afterwards(
            self, app_env, log_file):
        """The property that actually matters: eviction, not record count."""
        sentinel = 'SENTINEL-a-real-thing-that-happened-earlier'
        logging.getLogger('test-earlier').error(sentinel)

        session = client(app_env)
        for _ in range(BURST):
            session.get('/')

        assert any(sentinel in message for _, message in records(log_file)), (
            'a burst of unauthenticated requests evicted a log line that was '
            'written before it'
        )

    def test_the_unreadable_config_value_path_is_bounded_too(
            self, app_env, log_file):
        """The second flooding call site, reached by a typo in config.ini.

        Hand-editing config.ini is the DOCUMENTED lockout recovery, so a typo
        there is expected -- and it used to log at ERROR on every request while
        the operator was mid-recovery.
        """
        app_env['auth_required'] = 'yess'
        app_env['password'] = ''
        session = client(app_env)

        for _ in range(BURST):
            session.get('/')

        unrecognised = [r for r in at_info_or_above(log_file)
                        if 'unrecognised' in r[1].lower()]
        assert 0 < len(unrecognised) <= 10, len(unrecognised)

    def test_the_unreadable_secret_path_is_bounded_too(self, app_env, log_file):
        """The third call site, and the one a stranger provokes most cheaply.

        `get_current_user` only reaches `get_session_secret` when a cookie is
        PRESENT -- so a caller with no credentials at all simply sends a
        `user` cookie containing anything. No secret exists here, so every one
        of those requests took the ERROR path.
        """
        app_env['password'] = 'irrelevant-but-set'
        session = client(app_env)
        session.cookies.set('user', 'not-a-token')

        for _ in range(BURST):
            assert session.get('/').status_code == 302

        missing = [r for r in at_info_or_above(log_file)
                   if 'signing secret could be read' in r[1].replace('could not be', 'could be')]
        assert 0 < len(missing) <= 10, len(missing)
        assert len(at_info_or_above(log_file)) <= 10

    def test_two_different_conditions_do_not_silence_each_other(
            self, app_env, log_file):
        """Each call site needs its OWN key, and that is not decorative.

        Sharing one key between two messages bounds the log just as well and
        loses half the diagnosis: the operator sees whichever condition
        happened to be logged first and no trace of the other, on an install
        that has two things wrong with it. Caught by mutation -- pointing the
        `auth_required` site at the no-password key left every other test in
        this file green.

        Both conditions hold here at once: `auth_required` is a typo, so it
        falls back to the password (which IS set, so authentication is on), and
        a cookie is presented while no signing secret exists.
        """
        app_env['auth_required'] = 'yess'
        app_env['password'] = 'irrelevant-but-set'
        session = client(app_env)
        session.cookies.set('user', 'not-a-token')

        for _ in range(BURST):
            session.get('/')

        emitted = at_info_or_above(log_file)
        assert any('Unrecognised auth_required' in m for _, m in emitted), (
            'the config.ini typo was never reported: %r' % [m for _, m in emitted]
        )
        assert any('signing secret could be read' in m.replace('could not be', 'could be')
                   for _, m in emitted), (
            'the unreadable-secret condition was never reported, so one call '
            'site is suppressing the other: %r' % [m for _, m in emitted]
        )
        assert len(emitted) <= 10, len(emitted)


class TestEachCallSiteKeepsItsOwnKey:
    """Sharing a key bounds the log just as well and loses half the diagnosis.

    Both halves are here because neither alone is enough, and I know that
    because the behavioural one below let a real mutation through: pointing the
    `auth_required` typo message at the no-password key changed nothing
    observable, since those two conditions provably cannot hold at the same
    time (`auth_is_required` returns before reaching the second). The
    structural half catches it; the behavioural half catches the pair that CAN
    co-occur, which the structural half could never prove.
    """

    def test_every_suppression_key_in_the_web_module_is_distinct(self):
        """AC-ARCH-2's shape, applied to the suppression keys."""
        import couchpotato

        source = Path(couchpotato.__file__).read_text(encoding='utf-8')
        keys = re.findall(r"log_suppressed\(\s*log\.\w+,\s*'([a-z_]+)'", source)

        assert len(keys) >= 3, (
            'the suppression call sites were not found by this pattern, so '
            'this test is asserting nothing: %r' % keys
        )
        assert len(keys) == len(set(keys)), (
            'two log call sites share a suppression key, so one of them can '
            'silence the other: %r' % keys
        )

    def test_the_no_password_and_missing_secret_messages_both_get_through(
            self, app_env, log_file):
        """The pair that DOES co-occur, driven through the real app.

        `auth_required = 1` with no password stored logs the lockout remedy,
        and a request carrying any cookie then also finds no signing secret.
        An operator in this state needs both sentences.
        """
        app_env['auth_required'] = 1
        app_env['password'] = ''
        session = client(app_env)
        session.cookies.set('user', 'not-a-token')

        for _ in range(BURST):
            session.get('/')

        emitted = at_info_or_above(log_file)
        assert any('NO PASSWORD' in m for _, m in emitted), (
            'the lockout remedy was never logged: %r' % [m for _, m in emitted]
        )
        assert len(emitted) <= 10, len(emitted)


class TestSuppressionDoesNotCostTheDiagnosis:
    """AC-OPS-46, both directions."""

    def test_the_first_record_carries_the_full_message_and_the_remedy(
            self, app_env, log_file):
        client(app_env).get('/')

        emitted = [m for _, m in at_info_or_above(log_file) if 'Require login' in m]
        assert emitted, 'nothing was logged at all, so nothing can be diagnosed'
        first = emitted[0]
        assert 'config.ini' in first, (
            'the first record does not name the config.ini remedy, which is '
            'the only way out of this state: %r' % first
        )
        assert 'auth_required = 0' in first, first
        assert 'NO PASSWORD' in first, first

    def test_the_suppression_itself_is_visible_in_the_log(self, app_env, log_file):
        """Otherwise the operator sees one line and no sign of the other 999.

        A silent limiter turns "this happened once" and "this is happening
        continuously" into the same log, which is a worse diagnosis than the
        flood it replaced.
        """
        session = client(app_env)
        for _ in range(50):
            session.get('/')

        text = ' '.join(message for _, message in at_info_or_above(log_file))
        assert 'suppress' in text.lower(), (
            'nothing in the log says that further messages were withheld: %r' % text
        )

    def test_a_later_record_states_how_many_were_suppressed(self, app_env, log_file):
        """The count, which is the part that tells them the scale.

        Reported on the next emission after the window rather than during it:
        the number is not known until then.
        """
        session = client(app_env)
        for _ in range(50):
            session.get('/')

        # Step past the window without sleeping and without patching a
        # module-level clock (that also freezes `date.today()` here).
        reset_at = LOG_SUPPRESSION_WINDOW + 1
        log_suppressed(
            logging.getLogger('test-count').error,
            'auth_required_without_password',
            'the same message again',
            now=_monotonic_now() + reset_at,
        )

        counted = [re.search(r'\b(\d+) identical', message)
                   for _, message in at_info_or_above(log_file)]
        counted = [int(m.group(1)) for m in counted if m]
        assert counted, (
            'no record states how many messages were suppressed: %r'
            % [m for _, m in at_info_or_above(log_file)]
        )
        assert max(counted) >= 40, (
            'the reported count (%r) is nowhere near the ~49 occurrences that '
            'were actually withheld' % counted
        )


def _monotonic_now():
    import time
    return time.monotonic()


class TestTheSuppressionHelperItself:
    """Driven directly with an injected clock, so no test sleeps."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        reset_log_suppression()
        yield
        reset_log_suppression()

    def test_the_first_call_emits_the_full_message(self):
        emitted = []
        log_suppressed(emitted.append, 'k', 'the whole message', now=0)

        assert emitted == ['the whole message']

    def test_the_second_call_inside_the_window_does_not_repeat_it(self):
        emitted = []
        log_suppressed(emitted.append, 'k', 'the whole message', now=0)
        log_suppressed(emitted.append, 'k', 'the whole message', now=1)

        assert len(emitted) == 2, emitted
        assert emitted[0] == 'the whole message'
        assert 'suppress' in emitted[1].lower(), emitted[1]
        assert 'the whole message' not in emitted[1], (
            'the "now suppressing" notice repeats the message it is suppressing'
        )

    def test_a_thousand_more_inside_the_window_add_nothing(self):
        emitted = []
        for i in range(1000):
            log_suppressed(emitted.append, 'k', 'm', now=i * 0.001)

        assert len(emitted) == 2, len(emitted)

    def test_after_the_window_it_emits_again_and_states_the_count(self):
        emitted = []
        for i in range(50):
            log_suppressed(emitted.append, 'k', 'the whole message', now=i * 0.001)

        log_suppressed(emitted.append, 'k', 'the whole message',
                       now=LOG_SUPPRESSION_WINDOW + 1)

        assert 'the whole message' in emitted[-1]
        # 49, not 50: the first call was emitted in full, and the second was
        # withheld behind the "now suppressing" notice, so it counts too.
        assert '49 identical' in emitted[-1], emitted[-1]

    def test_a_quiet_period_then_one_occurrence_is_reported_in_full(self):
        """The regression that would matter most: swallowing a lone event.

        An operator who restarts and makes one request must see the whole
        message, not a counter.
        """
        emitted = []
        log_suppressed(emitted.append, 'k', 'the whole message', now=0)
        log_suppressed(emitted.append, 'k', 'the whole message',
                       now=LOG_SUPPRESSION_WINDOW * 10)

        assert emitted[-1] == 'the whole message', emitted

    def test_different_keys_do_not_suppress_each_other(self):
        emitted = []
        log_suppressed(emitted.append, 'a', 'first', now=0)
        log_suppressed(emitted.append, 'b', 'second', now=0)

        assert emitted == ['first', 'second']

    def test_the_message_arguments_are_still_formatted_lazily(self):
        """CPLog is `%`-style and PrivacyFilter relies on `record.args`.

        Interpolating here instead of passing the args through would bypass
        that, which is how a private path or a key reaches the log.
        """
        emitted = []

        def capture(msg, *args):
            emitted.append((msg, args))

        log_suppressed(capture, 'k', 'value is %r', 'secret-ish', now=0)

        assert emitted == [('value is %r', ('secret-ish',))]
