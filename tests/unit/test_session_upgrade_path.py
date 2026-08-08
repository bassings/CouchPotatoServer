"""What happens to a RUNNING install the first time it starts this version.

AC-SEC-44 and D5. The spec's first question about any design here is "what
happens to the owner of a running install when it is wrong", because PR 2
shipped a one-click unrecoverable lockout and an earlier attempt at this same
auth surface failed OPEN for a week.

So the upgrade is driven, not reasoned about: an existing database is opened
with `SQLiteAdapter.open()` -- never `create()`, which would run `schema.sql`
and quietly paper over exactly the failure this criterion exists to catch --
with `auth_required = 1` and a password already stored, holding the api_key
cookie the previous version issued.

Four things have to hold at once, and only the last is comfortable:

  * no DDL. `open()` runs none of `schema.sql`, so anything added there reaches
    FRESH installs only and the first login on every existing one raises
    `no such table`. That is the settled constraint the whole design follows
    from, and it is asserted here by watching what SQLite is actually asked to
    execute rather than by reading the diff.
  * the old cookie stops working IMMEDIATELY, with a 302 to the login page and
    never a 500. There is no compatibility window (D5): the old cookie IS the
    api_key, so honouring it for one more day is honouring the defect for one
    more day.
  * the way back in is the password the operator already has. No `config.ini`
    edit, no restart, no reading the source -- and no restart BETWEEN the
    refusal and the recovery, which is the part a test that rebuilds the app
    would quietly skip.
  * exactly one log line says existing sessions were invalidated and names the
    way back. Not zero, because the operator is about to be signed out of a
    machine they did not touch; not several, because the one that matters gets
    lost among them.
"""
import logging
import socket
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato import SESSION_COOKIE_NAME, ensure_session_secret
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core import event as event_module
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_helper import env_restored  # noqa: E402

API_KEY = 'notarealapikey' + '0' * 18
PASSWORD = 'hunter2'
STORED_PASSWORD = hash_password(md5(PASSWORD))
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Statements that change the shape of the database. A migration that needs one
#: of these cannot ship under the no-DDL constraint, because `open()` will
#: never have run it on an existing install.
DDL_PREFIXES = ('CREATE TABLE', 'ALTER TABLE', 'DROP TABLE', 'DROP INDEX',
                'CREATE VIRTUAL TABLE')


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
        self.saves = getattr(self, 'saves', 0) + 1


class RecordingConnection:
    """A `sqlite3.Connection` that remembers every statement it is given.

    `__setattr__` forwards, and that is not decoration: `SQLiteAdapter.open()`
    does `self._conn.row_factory = sqlite3.Row` straight after connecting. A
    wrapper that swallowed the assignment left the real connection handing back
    tuples, so every read in this file died on `row['data']` -- a failure that
    reads exactly like "the upgrade corrupted the database".
    """

    _OWN = ('_connection', '_statements')

    def __init__(self, connection, statements):
        object.__setattr__(self, '_connection', connection)
        object.__setattr__(self, '_statements', statements)

    def execute(self, sql, *args, **kwargs):
        self._statements.append(sql)
        return self._connection.execute(sql, *args, **kwargs)

    def executemany(self, sql, *args, **kwargs):
        self._statements.append(sql)
        return self._connection.executemany(sql, *args, **kwargs)

    def executescript(self, sql, *args, **kwargs):
        self._statements.append(sql)
        return self._connection.executescript(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __setattr__(self, name, value):
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self._connection, name, value)


def build_the_old_install(path) -> str:
    """A database as the PREVIOUS version left it: no session secret in it.

    Created and then closed, so what the upgrade sees is a file on disk rather
    than a live handle the test has been holding open.
    """
    db = SQLiteAdapter()
    db.create(str(path))
    # Something to lose. An upgrade that emptied the library would otherwise
    # pass every assertion below.
    db.insert({'_t': 'media', 'type': 'movie', 'identifiers': {'imdb': 'tt0111161'},
               'title': 'The Shawshank Redemption'})
    db.insert({'_t': 'property', 'identifier': 'last_checked', 'value': '1700000000'})
    db.close()
    return str(path)


@pytest.fixture
def upgraded(tmp_path):
    """An existing install, opened -- not created -- by this version."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    old_events = {name: list(handlers) for name, handlers in event_module.events.items()}
    old_timeout = socket.getdefaulttimeout()

    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    build_the_old_install(data_dir / 'database_v2')

    statements = []
    real_connect = sqlite3.connect

    def recording_connect(*args, **kwargs):
        return RecordingConnection(real_connect(*args, **kwargs), statements)

    sqlite3.connect = recording_connect
    try:
        db = SQLiteAdapter()
        # THE POINT OF THIS FILE. `create()` runs `schema.sql`; `open()` does
        # not, and `open()` is what every existing install gets.
        db.open(str(data_dir / 'database_v2'))
    finally:
        sqlite3.connect = real_connect

    settings = FakeSettings({
        'username': '', 'password': STORED_PASSWORD, 'api_key': API_KEY,
        # The install was already password-protected and already had the gate
        # explicitly on, which is the state the migration leaves behind.
        'auth_required': 1,
        'rate_limit_max': 0, 'cors_origins': '', 'ssl_cert': '', 'ssl_key': '',
    })

    with env_restored():
        Env.set('db', db)
        Env.set('settings', settings)
        Env.set('web_base', '/')
        Env.set('api_base', '/api/%s/' % API_KEY)
        Env.set('static_path', '/static/')
        Env.set('app_dir', str(REPO_ROOT))
        Env.set('data_dir', str(data_dir))
        Env.set('dev', False)
        Env.set('desktop', True)

        from couchpotato.core._base._core import Core
        Core()

        try:
            yield type('Upgrade', (), {
                'db': db, 'settings': settings, 'statements': statements,
                'data_dir': data_dir,
            })
        finally:
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


def boot(upgraded):
    """What `runner.py` does at startup, in the same order, then the app."""
    ensure_session_secret(upgraded.db)
    from couchpotato import create_app
    return create_app(API_KEY, '/')


def ddl_in(statements):
    return [s for s in statements
            if s.strip().upper().startswith(DDL_PREFIXES)]


class TestTheUpgradeRunsNoDDL:

    def test_opening_the_existing_database_creates_no_table(self, upgraded):
        assert ddl_in(upgraded.statements) == [], ddl_in(upgraded.statements)

    def test_the_session_bootstrap_and_a_full_login_run_none_either(self, upgraded):
        upgraded.statements.clear()

        app = boot(upgraded)
        session = TestClient(app, follow_redirects=False)
        session.post('/login/', data={'username': '', 'password': PASSWORD})
        session.get('/')
        session.post('/logout/')

        assert ddl_in(upgraded.statements) == [], ddl_in(upgraded.statements)

    def test_the_only_create_statements_on_open_are_the_pre_existing_indexes(
            self, upgraded):
        """`DDL_PREFIXES` deliberately omits CREATE INDEX, so say why here.

        `open()` runs `_ensure_unique_media_identifier_index` and
        `_ensure_release_download_index`, which predate this change and which
        AC-ARCH-13 names as untouched by it. Anything ELSE creating something
        on open is this change reaching into the schema, which is the thing
        that cannot ship: `open()` never runs `schema.sql`, so a new table
        would exist on fresh installs only and the first login on every
        existing one would raise `no such table`.
        """
        creates = [s.strip() for s in upgraded.statements
                   if s.strip().upper().startswith('CREATE')]

        assert all('INDEX' in s.upper() for s in creates), creates
        assert all('IF NOT EXISTS' in s.upper() for s in creates), creates

    def test_the_session_flow_creates_nothing_at_all(self, upgraded):
        """Not even an index. The secret is a `property` row in a table that
        has existed since before this PR."""
        upgraded.statements.clear()

        app = boot(upgraded)
        session = TestClient(app, follow_redirects=False)
        session.post('/login/', data={'username': '', 'password': PASSWORD})
        session.get('/')

        creates = [s for s in upgraded.statements
                   if s.strip().upper().startswith('CREATE')]
        assert creates == [], creates

    def test_the_recorder_actually_sees_statements(self, upgraded):
        """Anti-vacuity: "no DDL" is what an empty list says too, and an
        earlier version of this fixture recorded nothing at all because the
        adapter had already connected."""
        assert len(upgraded.statements) >= 2, upgraded.statements

    def test_the_pre_existing_library_is_still_there(self, upgraded):
        """An upgrade that lost the library would satisfy every DDL assertion
        above perfectly."""
        boot(upgraded)

        titles = [row.get('title') for row in upgraded.db.all('media')]
        assert 'The Shawshank Redemption' in titles, titles


class TestThePreviousVersionsCookieStopsWorking:
    """D5: no compatibility window, because the old cookie IS the api_key."""

    def test_it_is_refused_with_a_redirect_and_not_a_500(self, upgraded):
        app = boot(upgraded)

        session = TestClient(app, follow_redirects=False)
        session.cookies.set(SESSION_COOKIE_NAME, API_KEY)
        response = session.get('/')

        assert response.status_code == 302, response.status_code
        assert '/login/' in response.headers.get('location', '')

    def test_it_is_refused_on_the_very_first_request(self, upgraded):
        """No grace period, not even one request."""
        app = boot(upgraded)

        session = TestClient(app, follow_redirects=False)
        session.cookies.set(SESSION_COOKIE_NAME, API_KEY)

        assert session.get('/').status_code == 302

    def test_the_refusal_names_the_session_ending_rather_than_a_first_visit(self, upgraded):
        """The person had a working login a minute ago. The login page has to
        say so, or the only explanation available is "it is broken"."""
        app = boot(upgraded)

        session = TestClient(app, follow_redirects=False)
        session.cookies.set(SESSION_COOKIE_NAME, API_KEY)

        assert 'reason=session_ended' in session.get('/').headers['location']

    def test_the_api_key_still_works_as_an_api_key(self, upgraded):
        """AC-PROD-3. The cookie stops being a credential; the KEY does not,
        so no script, downloader or userscript breaks."""
        app = boot(upgraded)

        response = TestClient(app).get('/api/%s/app.available/' % API_KEY)

        assert response.status_code == 200, response.text


class TestTheWayBackInIsThePasswordTheyAlreadyHave:

    def test_a_login_immediately_yields_a_working_session(self, upgraded):
        app = boot(upgraded)

        session = TestClient(app, follow_redirects=False)
        session.cookies.set(SESSION_COOKIE_NAME, API_KEY)
        assert session.get('/').status_code == 302

        # Same app object, same process, no restart, no config edit.
        response = session.post('/login/', data={'username': '', 'password': PASSWORD})
        assert response.status_code == 302
        assert session.get('/').status_code == 200

    def test_no_settings_were_written_to_get_back_in(self, upgraded):
        """"No `config.ini` edit" as an assertion rather than a claim."""
        app = boot(upgraded)
        upgraded.settings.saves = 0

        session = TestClient(app, follow_redirects=False)
        session.post('/login/', data={'username': '', 'password': PASSWORD})
        assert session.get('/').status_code == 200

        assert getattr(upgraded.settings, 'saves', 0) == 0, (
            'the recovery wrote to the settings file, so an install whose '
            'config is read-only cannot get back in'
        )

    def test_the_new_cookie_is_not_the_api_key(self, upgraded):
        app = boot(upgraded)

        session = TestClient(app, follow_redirects=False)
        session.post('/login/', data={'username': '', 'password': PASSWORD})

        issued = session.cookies.get(SESSION_COOKIE_NAME)
        assert issued
        assert API_KEY not in issued


class TestTheUpgradeSaysWhatItDidExactlyOnce:
    """AC-SEC-44's last clause."""

    def test_one_line_states_the_invalidation_and_the_way_back(self, upgraded, caplog):
        with caplog.at_level(logging.INFO):
            boot(upgraded)

        stated = [
            record.getMessage() for record in caplog.records
            if record.levelno >= logging.INFO
            and 'invalidated' in record.getMessage().lower()
        ]

        assert len(stated) == 1, stated
        message = stated[0].lower()
        assert 'sign in again' in message or 'log in again' in message, stated
        # The other half of the operator's question, and the reason the api_key
        # is deliberately NOT rotated: nothing else they run breaks.
        assert 'api_key' in message, stated

    def test_a_second_boot_says_nothing(self, upgraded, caplog):
        """AC-OPS-41. A message repeated on every restart is a message that
        stops meaning anything."""
        boot(upgraded)

        with caplog.at_level(logging.INFO):
            boot(upgraded)

        stated = [record.getMessage() for record in caplog.records
                  if 'invalidated' in record.getMessage().lower()]
        assert stated == [], stated
