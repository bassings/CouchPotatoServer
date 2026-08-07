"""No session secret, cookie, signature or api_key reaches the log. AC-SEC-41.

Read off DISK, from a real `RotatingFileHandler` with the real `PrivacyFilter`
attached, after driving the real routes. `caplog` would not do: it bypasses the
handler the filter is attached to, so a record that leaks in production looks
clean in a caplog assertion. (`PrivacyFilter` is attached per HANDLER on
purpose -- a Logger's own filters only run for records that originate on that
logger, and `CPLog` always logs through a named child.)

The root logger is set to DEBUG here, not INFO. A secret written at DEBUG is
still a secret written to a file, and the operator turns DEBUG on precisely
when something is wrong, which is when they are most likely to be pasting the
log into an issue.

`PrivacyFilter`'s name lists (`logger.py:28-60`) had no entry that would catch a
session secret. `secret` is added to the bare-assignment list, which the prefix
match extends to `session_secret=`, `client_secret=` and the like. Its
load-bearingness is proven directly below rather than inferred: with the entry
removed, `test_a_secret_written_in_a_log_line_is_redacted` fails.
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
from couchpotato.core.logger import PrivacyFilter
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: 32 characters, the real key's LENGTH, because a short one produces a false
#: PASS: a few characters are likely to appear inside unrelated text, so the
#: "is it in the file" search finds them either way and the assertion never
#: discriminates. Not hex, deliberately: a realistic-looking hex key here is
#: indistinguishable from a real one to `gitleaks`, and the remedy for a
#: flagged secret is rotation, so a test fixture must never look like one.
#: Same spelling as the other suites in this directory.
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


@pytest.fixture
def env(tmp_path):
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

    Env.set('db', db)
    Env.set('settings', settings)
    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(REPO_ROOT))
    Env.set('data_dir', str(tmp_path))
    # PrivacyFilter returns early and redacts NOTHING when `dev` is on, so a
    # test that left it True would pass against a filter that does not work.
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
    # The same filter `setup_logging` attaches, constructed the same way. A
    # test that attached no filter would be measuring nothing.
    handler.addFilter(PrivacyFilter())
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

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
        # `PrivacyFilter` caches the api_key on the CLASS, so leaving this
        # module's key there would redact it out of every later test's log.
        PrivacyFilter._api_key = None
        PrivacyFilter._is_develop = None


def log_text(env):
    env.handler.flush()
    if not os.path.exists(env.log_path):
        return ''
    with open(env.log_path, encoding='utf-8') as handle:
        return handle.read()


def drive_every_flow(env):
    """Login, an authenticated page load, a failed login, logout.

    Returns every cookie value the server issued, so the assertions can look
    for the exact bytes rather than for a shape.
    """
    issued = []
    session = TestClient(env.app, follow_redirects=False)

    response = session.post('/login/', data={'username': '', 'password': PASSWORD})
    assert response.status_code == 302, response.text
    token = session.cookies.get(SESSION_COOKIE_NAME)
    assert token, 'no cookie was issued, so this test would assert nothing'
    issued.append(token)

    assert session.get('/').status_code == 200

    failed = TestClient(env.app, follow_redirects=False)
    assert failed.post('/login/', data={'username': '', 'password': 'wrong'}).status_code == 200

    assert session.post('/logout/').status_code in (302, 303)

    return issued


class TestNothingSecretReachesTheLogFile:
    """AC-SEC-41."""

    def test_the_signing_secret_is_absent(self, env):
        drive_every_flow(env)

        assert env.secret not in log_text(env), (
            'the session signing secret is in the log. Anyone who is sent the '
            'log can forge a session for as long as it takes the operator to '
            'sign out.'
        )

    def test_the_secret_that_replaced_it_is_absent_too(self, env):
        """Logout rotates, so there are two secrets in the life of this test."""
        drive_every_flow(env)

        rotated = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert rotated != env.secret, 'nothing rotated, so this asserts nothing'
        assert rotated not in log_text(env)

    def test_every_issued_cookie_value_is_absent(self, env):
        issued = drive_every_flow(env)
        text = log_text(env)

        assert issued, 'no cookies were issued'
        for token in issued:
            assert token not in text, 'an issued session cookie is in the log'

    def test_every_signature_is_absent(self, env):
        """The signature half alone is enough to matter.

        The payload is only an expiry timestamp, so a leaked signature paired
        with its payload IS the cookie.
        """
        issued = drive_every_flow(env)
        text = log_text(env)

        for token in issued:
            _payload, _sep, signature = token.partition('.')
            assert signature, token
            assert signature not in text

    def test_the_api_key_is_absent(self, env):
        drive_every_flow(env)

        assert API_KEY not in log_text(env), (
            'the api_key is in the log; it is the credential every /api/ '
            'route authenticates with'
        )

    def test_the_password_is_absent(self, env):
        """Not in AC-SEC-41's list, and checked anyway.

        The plaintext arrives on the login form and the hash is in settings;
        either in a log is worse than the cookie, because people reuse
        passwords.
        """
        drive_every_flow(env)
        text = log_text(env)

        assert PASSWORD not in text
        assert STORED_PASSWORD not in text

    def test_the_log_is_not_simply_empty(self, env):
        """The check that stops all of the above being vacuous.

        Every assertion here is "X is not in the file". If nothing were ever
        written, or the handler were misattached, they would all pass forever
        against a filter that does nothing.
        """
        drive_every_flow(env)
        logging.getLogger('canary').error('CANARY-this-line-must-be-written')

        text = log_text(env)
        assert 'CANARY-this-line-must-be-written' in text, (
            'nothing reaches the log file at all, so every absence assertion '
            'in this module is vacuous'
        )


class TestThePrivacyFilterEntryIsLoadBearing:
    """The new `secret` name, proven rather than assumed.

    Nothing in the tree logs the session secret today, so the assertions above
    would pass with no filter at all. This drives a record that DOES contain
    it, in the shape a future debug line would take, through the same handler.
    """

    def test_a_secret_written_in_a_log_line_is_redacted(self, env):
        logging.getLogger('leaky').error('loaded session_secret=%s from the store',
                                         env.secret)

        text = log_text(env)
        assert env.secret not in text, (
            'a log line containing `session_secret=<value>` reached the file '
            'unredacted; PrivacyFilter has no name that matches it'
        )
        assert 'session_secret=xxx' in text, text

    def test_a_bare_secret_assignment_is_redacted(self, env):
        logging.getLogger('leaky').error('secret=%s', env.secret)

        text = log_text(env)
        assert env.secret not in text
        assert 'secret=xxx' in text, text

    def test_the_rest_of_the_message_survives_the_redaction(self, env):
        """A filter that eats the line removes the reason it was logged.

        That is how redaction gets switched off, which is worse than a leak
        nobody noticed.
        """
        logging.getLogger('leaky').error('secret=%s and the response was 404',
                                         env.secret)

        text = log_text(env)
        assert '404' in text
        assert env.secret not in text
