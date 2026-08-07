"""Every class of session rejection is distinguishable from the log alone.

AC-OPS-44. Four things can be wrong with a session cookie and the operator's
response to each is different: no cookie at all is a first visit, a malformed
one is something other than this server writing it, a bad signature is a
rotation (or a forgery), an expired one is a person who left the tab open. A
single "auth failed" line collapses all four into "something is wrong", which
is the diagnosis the operator already had.

Read off DISK from a real `RotatingFileHandler` with the real `PrivacyFilter`
attached, at a root level of `logging.INFO` -- the INT, never the string.
`logger.py:24` calls `logging.addLevelName(21, 'INFO')`, which overwrites
`_nameToLevel['INFO']` from 20 to 21, so `caplog.at_level('INFO')` sets the
threshold ABOVE every genuine INFO record and captures nothing. That produces a
false RED reading "the code never logged" (spec gap 1).

AC-OPS-45 is the other half and it binds harder than it looks: these call sites
are reachable by an UNAUTHENTICATED caller once per request, so an unbounded
ERROR (or INFO) per rejected cookie is L1 back again with a different message.
Every one of them goes through `log_suppressed`, asserted structurally here and
measured over 1,000 requests in `test_auth_log_flooding.py`.
"""
import logging
import os
import re
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato import (
    SESSION_COOKIE_NAME,
    SESSION_REJECTIONS,
    ensure_session_secret,
    mint_session_token,
    session_rejection_reason,
)
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core import event as event_module
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.core.logger import PrivacyFilter
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_helper import env_restored  # noqa: E402

#: 32 characters, the real key's LENGTH: a short fixture key appears inside
#: unrelated text and turns every "is it in the file" assertion into a pass.
#: Not hex, so `gitleaks` cannot mistake it for a real one.
API_KEY = 'notarealapikey' + '0' * 18
PASSWORD = 'hunter2'
STORED_PASSWORD = hash_password(md5(PASSWORD))
REPO_ROOT = Path(__file__).resolve().parents[2]
OTHER_SECRET = 'b' * 64


class FakeSettings(Settings):
    def __init__(self, data):
        from couchpotato.core.logger import CPLog
        self.data = data
        self.log = CPLog('test-settings')
        self.file = None
        self.p = None
        self.directories_delimiter = '::'

    def get(self, attr, default=None, section='core', type=None):
        return self.data.get(attr, default)

    def set(self, section, option, value):
        self.data[option] = value

    def addSection(self, section):
        pass

    def save(self):
        pass


@pytest.fixture
def env(tmp_path):
    """A real app over a real adapter, with authentication actually enforced."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    old_events = {name: list(handlers) for name, handlers in event_module.events.items()}
    old_timeout = socket.getdefaulttimeout()

    db = SQLiteAdapter()
    db.create(str(tmp_path / 'db'))

    settings = FakeSettings({
        'username': '', 'password': STORED_PASSWORD, 'api_key': API_KEY,
        'auth_required': 1, 'rate_limit_max': 0, 'cors_origins': '',
        'ssl_cert': '', 'ssl_key': '',
    })

    with env_restored():
        Env.set('db', db)
        Env.set('settings', settings)
        Env.set('web_base', '/')
        Env.set('api_base', '/api/%s/' % API_KEY)
        Env.set('static_path', '/static/')
        Env.set('app_dir', str(REPO_ROOT))
        Env.set('data_dir', str(tmp_path))
        # `PrivacyFilter` returns early and redacts NOTHING when `dev` is on, so a
        # test that left it True would be measuring a filter that does not run.
        Env.set('dev', False)
        Env.set('desktop', True)

        from couchpotato.core._base._core import Core
        Core()

        secret = ensure_session_secret(db)

        log_path = str(tmp_path / 'CouchPotato.log')
        handler = RotatingFileHandler(log_path, mode='a', maxBytes=500000,
                                      backupCount=10, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s',
                                               '%m-%d %H:%M:%S'))
        handler.addFilter(PrivacyFilter())
        root = logging.getLogger()
        previous_level = root.level
        # The INT. `logging.INFO` is 20; the string 'INFO' resolves to 21 here.
        root.setLevel(logging.INFO)
        root.addHandler(handler)

        # `httpx` emits one INFO record per request -- from the TEST CLIENT, not
        # from the application, and production has no such logger. Counting them
        # would measure the harness: before this line, 200 refused requests
        # produced exactly 200 records and every one of them was httpx's.
        noisy = [logging.getLogger(name) for name in ('httpx', 'httpcore')]
        previous_noisy = [logger.level for logger in noisy]
        for logger in noisy:
            logger.setLevel(logging.WARNING)

        from couchpotato import create_app
        app = create_app(API_KEY, '/')

        try:
            yield type('EnvHandle', (), {
                'db': db, 'settings': settings, 'secret': secret, 'app': app,
                'log_path': log_path, 'handler': handler,
            })
        finally:
            root.removeHandler(handler)
            handler.close()
            root.setLevel(previous_level)
            for logger, level in zip(noisy, previous_noisy):
                logger.setLevel(level)
            Env.set('desktop', False)
            socket.setdefaulttimeout(old_timeout)
            db.close()
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
            event_module.events.clear()
            event_module.events.update(old_events)
            PrivacyFilter._api_key = None
            PrivacyFilter._is_develop = None


def log_text(env) -> str:
    env.handler.flush()
    if not os.path.exists(env.log_path):
        return ''
    with open(env.log_path, encoding='utf-8') as handle:
        return handle.read()


def cookie_for(env, reason: str):
    """A `user` cookie value that provokes exactly `reason`, or None."""
    if reason == 'no_cookie':
        return None
    if reason == 'malformed':
        # No separator at all, so it is not even shaped like a token.
        return 'this-is-not-a-session-token'
    if reason == 'bad_signature':
        # Correctly shaped, correctly unexpired, signed with another secret.
        return mint_session_token(OTHER_SECRET, 3600)
    if reason == 'expired':
        # Signed by THIS server, so only the clock refuses it.
        return mint_session_token(env.secret, -10)
    raise AssertionError('unknown rejection reason %r' % reason)


def provoke(env, reason: str):
    session = TestClient(env.app, follow_redirects=False)
    cookie = cookie_for(env, reason)
    if cookie is not None:
        session.cookies.set(SESSION_COOKIE_NAME, cookie)

    response = session.get('/')
    assert response.status_code == 302, (
        'the request was not refused at all, so this test would assert '
        'nothing about a rejection: %s' % response.status_code
    )
    assert '/login/' in response.headers.get('location', '')
    return cookie


REASONS = sorted(SESSION_REJECTIONS)


class TestEachRejectionClassIsNamedDistinctly:
    """AC-OPS-44: four reasons, four tokens, one grep each."""

    def test_the_four_classes_are_all_covered(self):
        """Anti-vacuity: the parametrised tests below only cover what is here."""
        assert set(SESSION_REJECTIONS) == {
            'no_cookie', 'malformed', 'bad_signature', 'expired'}

    @pytest.mark.parametrize('reason', REASONS)
    def test_the_reason_reaches_the_log_at_info_or_above(self, env, reason):
        provoke(env, reason)

        token = SESSION_REJECTIONS[reason][0]
        assert token in log_text(env), (
            'nothing in the log names %r, so an operator cannot tell this '
            'rejection from the other three.\nlog was:\n%s'
            % (token, log_text(env))
        )

    @pytest.mark.parametrize('reason', REASONS)
    def test_no_other_reason_token_appears(self, env, reason):
        """Distinguishable, not merely present.

        A single message carrying all four tokens would pass the test above
        for every parameter while telling the operator nothing.
        """
        provoke(env, reason)

        text = log_text(env)
        others = sorted(
            other_token for other, (other_token, _) in SESSION_REJECTIONS.items()
            if other != reason and other_token in text
        )
        assert not others, (
            'refusing a %s cookie also logged %s, so the reasons do not '
            'discriminate.\nlog was:\n%s' % (reason, others, text)
        )

    def test_the_tokens_are_distinct_and_greppable(self):
        tokens = [token for token, _ in SESSION_REJECTIONS.values()]
        assert len(tokens) == len(set(tokens)), tokens
        for token in tokens:
            assert re.fullmatch(r'session-rejected:[a-z-]+', token), token

    def test_every_message_names_its_own_token(self):
        """The token has to be IN the message, not merely mapped to it."""
        for reason, (token, message) in SESSION_REJECTIONS.items():
            assert token in message, reason


class TestNothingSecretIsInThoseRecords:
    """AC-OPS-44's second clause, and AC-SEC-41 again for the new call sites."""

    @pytest.mark.parametrize('reason', REASONS)
    def test_the_cookie_value_is_not_in_the_log(self, env, reason):
        cookie = provoke(env, reason)
        if cookie is None:
            pytest.skip('the no-cookie case has no cookie value to leak')

        assert cookie not in log_text(env)

    @pytest.mark.parametrize('reason', REASONS)
    def test_the_signing_secret_is_not_in_the_log(self, env, reason):
        provoke(env, reason)

        assert env.secret not in log_text(env)


class TestTheRejectionLoggingIsBounded:
    """AC-OPS-45, applied to the call sites AC-OPS-44 adds.

    Without this the fix for L1 becomes decorative: one unbounded record per
    rejected cookie is the same log-ring eviction with a friendlier message,
    and it needs no credential to provoke.
    """

    @pytest.mark.parametrize('reason', REASONS)
    def test_two_hundred_rejections_emit_at_most_ten_records(self, env, reason):
        session = TestClient(env.app, follow_redirects=False)
        cookie = cookie_for(env, reason)
        if cookie is not None:
            session.cookies.set(SESSION_COOKIE_NAME, cookie)

        for _ in range(200):
            assert session.get('/').status_code == 302

        text = log_text(env)
        emitted = [line for line in text.splitlines()
                   if ' INFO ' in line or ' WARNING ' in line or ' ERROR ' in line]
        # Both directions. Without the lower bound this passes just as well
        # against a build that logs nothing at all, which is the state
        # AC-OPS-44 exists to end.
        assert SESSION_REJECTIONS[reason][0] in text, (
            'no record names this rejection, so the bound below is being '
            'measured against silence'
        )
        assert len(emitted) <= 10, (
            '200 refused requests produced %d records; the log ring is a '
            'stranger\'s to empty' % len(emitted)
        )

    def test_every_rejection_call_site_goes_through_log_suppressed(self):
        """Structural, because the behavioural test above cannot see a fifth
        call site somebody adds next to these four."""
        import ast
        import inspect
        import textwrap

        import couchpotato

        source = textwrap.dedent(inspect.getsource(couchpotato._log_session_rejection))
        calls = [node.func for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call)]
        names = {getattr(f, 'id', None) or getattr(f, 'attr', None) for f in calls}

        assert 'log_suppressed' in names, (
            'the rejection logger calls %s but not `log_suppressed`, so an '
            'unauthenticated caller can evict the log ring one refused cookie '
            'at a time -- which is L1, reopened.' % sorted(n for n in names if n)
        )

    def test_each_reason_gets_its_own_suppression_key(self):
        """Sharing one key bounds the log just as well and loses the diagnosis.

        Spec gap 18: two call sites sharing a key is invisible to a behavioural
        test whenever the two conditions cannot co-occur -- and no two of these
        four can, since one request has one cookie.
        """
        from couchpotato import session_suppression_key

        keys = [session_suppression_key(reason) for reason in SESSION_REJECTIONS]
        assert len(keys) == len(set(keys)), keys

        # ...and distinct from the keys already in the module, which would
        # otherwise be silenced by a burst of refused cookies.
        source = (REPO_ROOT / 'couchpotato' / '__init__.py').read_text(encoding='utf-8')
        literal = re.findall(r"log_suppressed\(\s*log\.\w+,\s*'([a-z_]+)'", source)
        assert literal, 'the literal-key call sites are gone; this asserts nothing'
        assert not set(keys) & set(literal), set(keys) & set(literal)


class TestTheClassifierAgreesWithTheVerifier:
    """The classifier must never accept what `verify_session_token` refuses.

    Two functions that both decide "is this session good" is exactly the shape
    that drifts, and the direction that matters is the permissive one.
    """

    def test_a_valid_token_classifies_as_no_rejection(self):
        secret = 'a' * 64
        assert session_rejection_reason(mint_session_token(secret, 3600), secret) is None

    @pytest.mark.parametrize('token,expected', [
        ('', 'no_cookie'),
        (None, 'no_cookie'),
        ('nothing-like-a-token', 'malformed'),
        ('.', 'malformed'),
        ('123.', 'malformed'),
        ('x' * 5000, 'malformed'),
    ])
    def test_the_structural_cases(self, token, expected):
        assert session_rejection_reason(token, 'a' * 64) == expected

    def test_a_token_signed_by_someone_else_is_a_bad_signature(self):
        token = mint_session_token(OTHER_SECRET, 3600)

        assert session_rejection_reason(token, 'a' * 64) == 'bad_signature'

    def test_a_token_we_signed_that_ran_out_is_expired(self):
        secret = 'a' * 64
        token = mint_session_token(secret, 3600, now=1_700_000_000)

        assert session_rejection_reason(token, secret, now=1_700_000_000) is None
        assert session_rejection_reason(
            token, secret, now=1_700_000_000 + 3601) == 'expired'

    def test_an_expired_token_whose_signature_is_also_wrong_is_a_bad_signature(self):
        """Signature first: the expiry is only trustworthy once the payload is
        known to be ours."""
        token = mint_session_token(OTHER_SECRET, -10)

        assert session_rejection_reason(token, 'a' * 64) == 'bad_signature'
