"""The secret vanishes under a running process, and the operator gets back in.

AC-QA-19 and D14. Open since tranche A as a straight contradiction: AC-QA-19
wants "a fresh login recovers a working session without a restart", D2 forbade
the request path from ever creating a secret, and both cannot hold -- with no
secret and no bootstrap, a correct password buys nothing until somebody
restarts the container. On a box whose owner may have no shell, that is the
lockout this spec exists to prevent, arriving through a different door.

D14 settles it: `login_post` MAY create a missing secret, and only after the
submitted password has been verified. The two properties that made D2 worth
having are kept, and both are asserted here rather than argued:

  * the write still goes through the ONE compare-and-swap writer (AC-ARCH-3,
    AC-DATA-3), which is what makes concurrent creates safe;
  * nothing unauthenticated, and nothing pre-credential, can write. A wrong
    password writes nothing, and with `auth_required` off nothing writes at
    all, because the password check cannot succeed on an install with no
    password (AC-QA-21).

The WARNING is the other half. A creation on a boot that already had a secret
is not the same event as a first-ever bootstrap: one is an install starting up,
the other is data that disappeared from under a running process, and the second
deserves to be findable in the log.
"""
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato import (
    SESSION_COOKIE_NAME,
    SESSION_SECRET_PROPERTY,
    ensure_session_secret,
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

API_KEY = 'notarealapikey' + '0' * 18
PASSWORD = 'hunter2'
STORED_PASSWORD = hash_password(md5(PASSWORD))
REPO_ROOT = Path(__file__).resolve().parents[2]


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


def secret_rows(db):
    return [row for row in db.query('property', SESSION_SECRET_PROPERTY)
            if row.get('identifier') == SESSION_SECRET_PROPERTY]


def delete_the_secret(db):
    """Take the property row out from under the running process."""
    rows = secret_rows(db)
    assert rows, 'there was no secret to delete, so the test proves nothing'
    for row in rows:
        db.delete(row)
    assert not secret_rows(db)


@pytest.fixture
def env(tmp_path, request):
    """A running app. `auth` marker turns authentication off for AC-QA-21."""
    auth_on = not request.node.get_closest_marker('auth_off')

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
        'username': '',
        'password': STORED_PASSWORD if auth_on else '',
        'api_key': API_KEY,
        'auth_required': 1 if auth_on else 0,
        'rate_limit_max': 0, 'cors_origins': '', 'ssl_cert': '', 'ssl_key': '',
    })

    with env_restored():
        Env.set('db', db)
        Env.set('settings', settings)
        Env.set('web_base', '/')
        Env.set('api_base', '/api/%s/' % API_KEY)
        Env.set('static_path', '/static/')
        Env.set('app_dir', str(REPO_ROOT))
        Env.set('data_dir', str(tmp_path))
        Env.set('dev', False)
        Env.set('desktop', True)

        from couchpotato.core._base._core import Core
        Core()

        # The startup bootstrap, exactly as `runner.py` runs it: only when
        # authentication is on, so an install that never enabled it never grows the
        # row.
        secret = ensure_session_secret(db) if auth_on else None

        log_path = str(tmp_path / 'CouchPotato.log')
        handler = RotatingFileHandler(log_path, mode='a', maxBytes=500000,
                                      backupCount=10, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s',
                                               '%m-%d %H:%M:%S'))
        handler.addFilter(PrivacyFilter())
        root = logging.getLogger()
        previous_level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(handler)
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


def sign_in(session) -> int:
    return session.post('/login/', data={'username': '', 'password': PASSWORD}).status_code


class TestTheSecretIsDeletedUnderARunningProcess:
    """AC-QA-19, driven end to end against one app object.

    No `create_app` between the deletion and the recovery: "without a restart"
    is the whole criterion, and rebuilding the app would quietly satisfy it.
    """

    def test_an_existing_cookie_stops_working(self, env):
        session = TestClient(env.app, follow_redirects=False)
        assert sign_in(session) == 302
        assert session.get('/').status_code == 200

        delete_the_secret(env.db)

        response = session.get('/')
        assert response.status_code == 302, response.status_code
        assert '/login/' in response.headers.get('location', '')

    def test_no_exception_escapes(self, env):
        session = TestClient(env.app, follow_redirects=False)
        assert sign_in(session) == 302
        delete_the_secret(env.db)

        body = session.get('/').text
        for marker in ('Traceback', 'Internal Server Error'):
            assert marker not in body

    def test_an_error_names_the_condition_and_the_recovery(self, env):
        session = TestClient(env.app, follow_redirects=False)
        assert sign_in(session) == 302
        delete_the_secret(env.db)
        session.get('/')

        text = log_text(env)
        # Matches the FACT, not the old wording. The message used to claim
        # "NO login can succeed", which was false on the very path D14 makes
        # work -- a first login bootstraps a secret and succeeds. Asserting on
        # the phrasing rather than the substance is what made this test object
        # to the correction.
        assert 'signing secret could be read' in text.replace('could not be', 'could be'), text
        assert 'config.ini' in text, 'the recovery path is no longer named'
        assert 'config.ini' in text

    def test_a_fresh_login_recovers_a_working_session_with_no_restart(self, env):
        session = TestClient(env.app, follow_redirects=False)
        assert sign_in(session) == 302
        delete_the_secret(env.db)
        assert session.get('/').status_code == 302

        # Same app object, same process. The operator types their existing
        # password into the page they were just redirected to.
        recovered = TestClient(env.app, follow_redirects=False)
        assert sign_in(recovered) == 302
        assert recovered.cookies.get(SESSION_COOKIE_NAME), (
            'the login issued no cookie, so the operator is still locked out '
            'until somebody restarts the container'
        )
        assert recovered.get('/').status_code == 200

    def test_the_recovery_writes_exactly_one_row(self, env):
        delete_the_secret(env.db)
        sign_in(TestClient(env.app, follow_redirects=False))

        assert len(secret_rows(env.db)) == 1

    def test_the_cookie_from_before_the_deletion_stays_dead(self, env):
        """The recovery mints a NEW secret, so it must not resurrect anything.

        If it did, deleting the row would be a way to keep an old cookie alive
        rather than a way to kill one.
        """
        old = TestClient(env.app, follow_redirects=False)
        assert sign_in(old) == 302
        stolen = old.cookies.get(SESSION_COOKIE_NAME)

        delete_the_secret(env.db)
        sign_in(TestClient(env.app, follow_redirects=False))

        replay = TestClient(env.app, follow_redirects=False)
        replay.cookies.set(SESSION_COOKIE_NAME, stolen)
        assert replay.get('/').status_code == 302


class TestTheRegenerationIsAnnounced:
    """AC-QA-19's second sentence."""

    def test_a_regeneration_warns_and_names_the_trigger(self, env):
        delete_the_secret(env.db)
        sign_in(TestClient(env.app, follow_redirects=False))

        warnings = [line for line in log_text(env).splitlines() if ' WARNING ' in line]
        assert warnings, (
            'the signing secret disappeared from the database and was silently '
            'replaced. That invalidates every other session on every device '
            'and there is nothing in the log to explain it.\nlog was:\n%s'
            % log_text(env)
        )
        joined = '\n'.join(warnings).lower()
        assert 'session' in joined and 'secret' in joined, warnings
        # The TRIGGER, not just the fact. "A new secret was created" is what
        # the INFO on a first boot already says.
        assert 'no longer in the database' in joined, warnings

    def test_a_first_ever_bootstrap_does_not_warn(self, tmp_path):
        """Both directions. A WARNING on every fresh install is a WARNING
        nobody reads by the second install."""
        import logging as logging_module

        from couchpotato import reset_session_secret_state

        reset_session_secret_state()
        db = SQLiteAdapter()
        db.create(str(tmp_path / 'fresh'))
        records = []

        class Collect(logging_module.Handler):
            def emit(self, record):
                records.append(record)

        handler = Collect()
        root = logging_module.getLogger()
        previous = root.level
        root.setLevel(logging_module.INFO)
        root.addHandler(handler)
        try:
            ensure_session_secret(db)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
            db.close()

        warnings = [r for r in records if r.levelno >= logging_module.WARNING]
        assert not warnings, [r.getMessage() for r in warnings]
        created = [r for r in records if 'session signing secret' in r.getMessage()]
        assert len(created) == 1, [r.getMessage() for r in created]


class TestNothingUnauthenticatedCanTriggerTheWrite:
    """D14's whole justification, asserted rather than asserted-in-prose."""

    def test_a_wrong_password_writes_nothing(self, env):
        delete_the_secret(env.db)

        session = TestClient(env.app, follow_redirects=False)
        response = session.post('/login/', data={'username': '', 'password': 'wrong'})

        assert response.status_code == 200, 'the login should have been refused'
        assert secret_rows(env.db) == [], (
            'a rejected login created a signing secret, so the write is '
            'reachable before any credential has been verified'
        )

    def test_an_unauthenticated_page_request_writes_nothing(self, env):
        delete_the_secret(env.db)

        session = TestClient(env.app, follow_redirects=False)
        for _ in range(5):
            assert session.get('/').status_code == 302

        assert secret_rows(env.db) == []

    @pytest.mark.auth_off
    def test_with_authentication_off_a_login_writes_nothing(self, env):
        """AC-QA-21, unchanged by D14 and asserted against it directly.

        There is no password to check on such an install, so the credential
        check cannot succeed, so the bootstrap cannot be reached. An install
        that never enabled authentication never grows the row.
        """
        session = TestClient(env.app, follow_redirects=False)
        session.post('/login/', data={'username': '', 'password': 'anything'})
        session.get('/')

        assert secret_rows(env.db) == []

    def test_the_login_bootstrap_uses_the_single_writer(self, env):
        """AC-ARCH-3: one compare-and-swap writer, not a second one here."""
        import couchpotato

        delete_the_secret(env.db)
        calls = []
        original = couchpotato._write_session_secret

        def spy(secret, db=None, attempts=3):
            calls.append(secret)
            return original(secret, db=db, attempts=attempts)

        couchpotato._write_session_secret = spy
        try:
            assert sign_in(TestClient(env.app, follow_redirects=False)) == 302
        finally:
            couchpotato._write_session_secret = original

        assert len(calls) == 1, (
            'the login bootstrap wrote the secret %d times through the '
            'single-writer function; anything other than one means it is '
            'writing the property row some other way' % len(calls)
        )


class TestAnUnreadableStoreIsNotAnAbsentSecret:
    """The boundary between D14 and AC-SEC-33, and it is a real one.

    `get_session_secret` answers None to both "this install has never had a
    secret" and "the property store just raised", and the two need opposite
    responses. Creating on a raising store would write a fresh secret over a row
    nobody could read -- signing every live session out because of a transient
    fault -- while AC-SEC-33 says a raising store issues no cookie at all.

    The first version of the D14 change conflated them and turned
    `test_session_secret_store.py::test_login_issues_no_cookie_when_the_secret_
    cannot_be_read` red, which is the only reason this class exists.

    Both tests below break the read at `SQLiteAdapter._query_index`, not at
    `Settings.getProperty`. `getProperty` swallows whatever `_query_index`
    raises in its own `except Exception:` and returns None, so patching
    `getProperty` to raise bypasses that handler -- a fault a real store never
    produces -- and never reaches `ensure_session_secret`'s read
    (`_session_secret_row`, straight against the adapter), which is the one
    that has to fail for either assertion below to mean anything. T13 deleted
    `session_secret_store_is_readable()` for exactly this reason: it read via
    `getProperty` too, and answered "readable" for a store whose real reads
    raised.
    """

    def test_a_login_against_a_raising_store_issues_no_cookie(self, env, monkeypatch):
        with monkeypatch.context() as m:
            m.setattr(
                SQLiteAdapter, '_query_index',
                lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError('store down')))

            session = TestClient(env.app, follow_redirects=False)
            response = session.post('/login/', data={'username': '', 'password': PASSWORD})

        assert 'set-cookie' not in {k.lower() for k in response.headers}

    def test_a_login_against_a_raising_store_writes_nothing(self, env, monkeypatch):
        """The dangerous half: a blind write over a row we cannot see.

        `secret_rows` reads through `_query_index` itself, so it is called
        before the patch is applied and again after the `with` block has
        undone it -- evaluating it while the patch is live would raise
        instead of comparing.
        """
        before = secret_rows(env.db)
        assert before, 'no secret to overwrite, so this proves nothing'

        with monkeypatch.context() as m:
            m.setattr(
                SQLiteAdapter, '_query_index',
                lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError('store down')))

            TestClient(env.app, follow_redirects=False).post(
                '/login/', data={'username': '', 'password': PASSWORD})

        assert secret_rows(env.db) == before, (
            'a login rewrote the signing secret while the property store was '
            'raising, so a transient fault signs every device out'
        )


class TestAFailedRecoveryDoesNotPretendToSucceed:

    def test_a_login_that_cannot_create_a_secret_issues_no_cookie(self, env, monkeypatch):
        """Fail closed. Signing with '' or a constant would hand a valid
        session to anyone who can read this source."""
        import couchpotato

        delete_the_secret(env.db)
        monkeypatch.setattr(couchpotato, 'ensure_session_secret',
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no')))

        session = TestClient(env.app, follow_redirects=False)
        response = session.post('/login/', data={'username': '', 'password': PASSWORD})

        # 503 and a rendered page, NOT the 302 this used to assert. The
        # redirect was the defect: it sent a user who had typed the right
        # password to the app root with no cookie, which bounced them back to
        # a blank login form explaining nothing -- the same unexplained loop
        # the rejected-credentials branch was changed to remove. Raised as a
        # P2 in review of #229.
        assert response.status_code == 503, response.status_code
        assert 'name="password"' in response.text, (
            'the user has no form to read or retry from')

        # The part that always mattered, unchanged: fail CLOSED. Signing with
        # '' or a constant would hand a valid session to anyone who can read
        # this source.
        assert SESSION_COOKIE_NAME not in response.cookies
        assert 'set-cookie' not in {k.lower() for k in response.headers}
        assert 'could not' in log_text(env).lower()
