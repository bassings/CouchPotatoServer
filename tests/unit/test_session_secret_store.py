"""The signing secret: where it lives, who may write it, and what happens
when it is not there.

Driven against a REAL `SQLiteAdapter`, not a dict double. The defects this
file exists to catch all live in the seam between the adapter and
`Settings.getProperty`: a stub that tolerated raw bytes would hide the fact
that `setProperty` mangles them, and a stub with no `_rev` would hide the
compare-and-swap that turns a lost race into a duplicate row.

Two read paths reach that adapter, and a broken-store test has to name the
one it means (T13/D17): `get_current_user`'s verification reads through the
REAL `Settings.getProperty`, so breaking THAT is the correct fault for the
verification-path tests below. `ensure_session_secret`'s bootstrap
(`_session_secret_row`) reads the adapter directly and never touches
`getProperty` -- breaking `getProperty` alone leaves that read working and
proves nothing about it, which is exactly how
`test_login_issues_no_cookie_when_the_secret_cannot_be_read` passed once
while a raising store issued a cookie. Those tests break
`SQLiteAdapter._query_index` instead, the layer both paths resolve to for the
`property` index.

Companion to `test_session_token.py`, which covers the pure sign/verify seam.
"""
import ast
import inspect
import logging
import os
import textwrap
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from couchpotato import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    SESSION_SECRET_PROPERTY,
    ensure_session_secret,
    generate_session_secret,
    get_current_user,
    get_session_secret,
    mint_session_token,
    verify_session_token,
)
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core.db.sqlite_adapter import ConflictError, SQLiteAdapter
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

#: 32 characters, the length a real `api_key` has, so a substring check
#: against the cookie cannot false-negative on a short one -- but visibly
#: fake and low-entropy, because a realistic random value here is a
#: gitleaks finding in the repository forever.
API_KEY = 'notarealapikey' + '0' * 18
REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeSettings(Settings):
    """The REAL `getProperty` / `setProperty`, over an in-memory config.

    Subclassed rather than stubbed so the property round-trip under test is
    the production one, including `toUnicode`. `Settings.__init__` registers
    API views and events, which a unit test must not do, so it is replaced.
    """

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


def make_db(path) -> SQLiteAdapter:
    db = SQLiteAdapter()
    db.create(str(path))
    return db


@pytest.fixture
def env(tmp_path):
    """Env wired to a real database and real Settings property methods."""
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)

    db = make_db(tmp_path / 'db')
    data = {
        'username': 'admin',
        'password': 'stored-hash',
        'api_key': API_KEY,
        'auth_required': 1,
    }
    settings = FakeSettings(data)

    Env.set('db', db)
    Env.set('settings', settings)
    Env.set('web_base', '/')
    Env.set('api_base', '/api/%s/' % API_KEY)
    Env.set('static_path', '/static/')
    Env.set('app_dir', str(REPO_ROOT))
    Env.set('data_dir', str(tmp_path))
    Env.set('dev', False)

    yield type('EnvHandle', (), {
        'db': db, 'data': data, 'settings': settings, 'tmp_path': tmp_path,
    })

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


def secret_rows(db):
    """Every stored property row for the secret, counted via `_query_index`.

    `get()` returns the FIRST match and hides duplicates, which is precisely
    the failure being counted: `Settings.setProperty` turning a lost
    compare-and-swap into a second row is invisible to `get()`.
    """
    return [row for row in db._query_index('property', key=SESSION_SECRET_PROPERTY)
            if row.get('identifier') == SESSION_SECRET_PROPERTY]


def client(follow_redirects=False):
    from couchpotato import create_app
    return TestClient(create_app(API_KEY, '/'), follow_redirects=follow_redirects)


def implementation_of(function) -> str:
    """Code only: docstrings and comments removed. See test_session_token.py."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    statements = tree.body[0].body
    if (statements and isinstance(statements[0], ast.Expr)
            and isinstance(statements[0].value, ast.Constant)
            and isinstance(statements[0].value.value, str)):
        statements = statements[1:]
    return '\n'.join(ast.unparse(node) for node in statements)


class TestTheSecretRoundTripsThroughThePropertyStore:
    """AC-DATA-1."""

    def test_the_stored_secret_reads_back_byte_identically(self, env):
        created = ensure_session_secret(env.db)

        assert Env.prop(SESSION_SECRET_PROPERTY) == created

    def test_the_stored_secret_still_carries_32_bytes_after_the_round_trip(self, env):
        ensure_session_secret(env.db)

        read_back = Env.prop(SESSION_SECRET_PROPERTY)

        assert len(bytes.fromhex(read_back)) == 32, (
            'the secret lost entropy in the store. Asserted in BYTES, never in '
            'characters: a corrupted value has a character length that varies '
            'with the random bytes (measured 29 one run, 31 another), so a '
            'character-count assertion is flaky as well as wrong.'
        )

    def test_raw_bytes_would_not_have_survived_which_is_why_it_is_hex(self, env):
        """The measurement behind the encoding, pinned so it cannot be undone.

        `setProperty` stores `toUnicode(value)`, which decodes with
        REPLACEMENT. This is not a fixed-length truncation: how much survives
        depends on which random bytes happen to form valid UTF-8.
        """
        raw = os.urandom(32)
        env.settings.setProperty('a-raw-bytes-canary', raw)

        assert env.settings.getProperty('a-raw-bytes-canary') != raw, (
            'raw bytes now survive the property store. If that is genuinely '
            'true the hex encoding is no longer load-bearing -- but verify it '
            'against `toUnicode` before relaxing anything, because a secret '
            'stored raw is silently different on every install and '
            'unrecoverable after the fact.'
        )

    def test_the_secret_is_a_property_row_not_a_new_document_type(self, env):
        """AC-SIMP-13/AC-ARCH-13: no new `_t`, so rollback is image-only."""
        ensure_session_secret(env.db)

        rows = secret_rows(env.db)
        assert len(rows) == 1
        stored = env.db.get('id', rows[0]['_id'])
        assert stored['_t'] == 'property'


class TestOnlyOneSecretRowEverExists:
    """AC-DATA-2 and AC-DATA-3."""

    def test_four_concurrent_bootstraps_leave_exactly_one_row(self, env):
        """The race D2 removes, driven directly rather than assumed away.

        Measured on `Settings.setProperty`: four concurrent creates produced
        TWO rows and lost two writes. Two rows means the lookup returns
        whichever SQLite hands back first, so half the issued cookies stop
        verifying at some arbitrary later point.
        """
        results = []
        barrier = threading.Barrier(4)

        def bootstrap():
            barrier.wait()
            results.append(ensure_session_secret(env.db))

        threads = [threading.Thread(target=bootstrap) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(secret_rows(env.db)) == 1, (
            'four concurrent first-time bootstraps produced %d property rows'
            % len(secret_rows(env.db))
        )
        assert len(set(results)) == 1, (
            'the four bootstraps disagreed about the secret: %r' % (set(results),)
        )

    def test_every_cookie_issued_by_those_concurrent_bootstraps_verifies(self, env):
        results = []
        barrier = threading.Barrier(4)

        def bootstrap_and_mint():
            barrier.wait()
            secret = ensure_session_secret(env.db)
            results.append(mint_session_token(secret, SESSION_LIFETIME))

        threads = [threading.Thread(target=bootstrap_and_mint) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        stored = Env.prop(SESSION_SECRET_PROPERTY)
        assert len(results) == 4
        for token in results:
            assert verify_session_token(token, stored) is True, (
                'a cookie issued during the concurrent bootstrap does not '
                'verify against the secret that survived'
            )

    def test_four_concurrent_logins_all_issue_cookies_that_verify(self, env):
        """The same race at the level the operator experiences it."""
        from couchpotato.core.helpers.variable import md5
        env.data['password'] = md5('hunter2')
        ensure_session_secret(env.db)

        cookies = []
        barrier = threading.Barrier(4)

        def login():
            barrier.wait()
            response = client().post('/login/', data={
                'username': 'admin', 'password': 'hunter2',
            })
            cookies.append(response.cookies.get(SESSION_COOKIE_NAME))

        threads = [threading.Thread(target=login) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(secret_rows(env.db)) == 1
        secret = Env.prop(SESSION_SECRET_PROPERTY)
        assert len(cookies) == 4
        for token in cookies:
            assert token, 'a concurrent login issued no session cookie'
            assert verify_session_token(token, secret) is True

    def test_a_write_that_loses_the_compare_and_swap_retries_rather_than_inserting(self, env):
        """AC-DATA-3, the `setProperty` defect reproduced against our writer.

        `Settings.setProperty` wraps get-then-update in a bare
        `except Exception:` that falls through to `insert`. A `ConflictError`
        -- the adapter's signal that our `_rev` is stale -- therefore becomes a
        SECOND property row plus a discarded write, after which `get()` returns
        the older value. Ours must re-read and retry.
        """
        from couchpotato import _write_session_secret

        ensure_session_secret(env.db)
        assert len(secret_rows(env.db)) == 1

        real_update = env.db.update
        calls = {'n': 0}

        def flaky_update(doc):
            calls['n'] += 1
            if calls['n'] == 1:
                # A REAL competing write, not just a raised exception. Raising
                # on call count alone leaves the row untouched, so the retry
                # succeeds whether it re-read or reused a stale copy -- and
                # this test passed with `existing = _session_secret_row(db)`
                # hoisted OUT of the retry loop, which is precisely the defect
                # it claims to catch. Measured: 9 passed with the read hoisted.
                #
                # Bumping the row's `_rev` here means a hoisted read retries
                # against a stale revision and keeps conflicting.
                from couchpotato import _session_secret_row
                competitor = _session_secret_row(env.db)
                competitor['value'] = 'written-by-someone-else'
                real_update(competitor)
                raise ConflictError(doc.get('_id'))
            return real_update(doc)

        env.db.update = flaky_update
        try:
            _write_session_secret('c' * 64, db=env.db)
        finally:
            env.db.update = real_update

        assert calls['n'] == 2, 'the losing write did not retry (%d attempts)' % calls['n']
        assert len(secret_rows(env.db)) == 1, (
            'the lost compare-and-swap inserted a duplicate property row '
            'instead of retrying -- exactly the setProperty defect'
        )
        assert Env.prop(SESSION_SECRET_PROPERTY) == 'c' * 64, (
            'the retried write was lost; the store returned the older value'
        )


class TestTheSecretIsCreatedOnceAtStartup:
    """D2, AC-OPS-41, AC-ARCH-3."""

    def test_the_first_bootstrap_creates_one_row_and_says_so_once(self, env, caplog):
        with caplog.at_level(logging.INFO):
            ensure_session_secret(env.db)

        assert len(secret_rows(env.db)) == 1
        created = [record for record in caplog.records
                   if record.levelno >= 20 and 'session signing secret' in record.getMessage()]
        assert len(created) == 1, (
            'expected exactly one INFO naming the event, got %d: %r'
            % (len(created), [record.getMessage() for record in created])
        )
        assert 'invalidated' in created[0].getMessage().lower(), (
            'the record must say existing browser logins stop working, '
            'because that is the part the operator is about to be asked about'
        )

    def test_a_second_boot_creates_nothing_and_logs_nothing(self, env, caplog):
        first = ensure_session_secret(env.db)

        with caplog.at_level(logging.INFO):
            second = ensure_session_secret(env.db)

        assert second == first, 'the second boot rotated the secret and signed everyone out'
        assert len(secret_rows(env.db)) == 1
        assert not [record for record in caplog.records
                    if 'session signing secret' in record.getMessage()], (
            'a second boot against the same data directory announced a '
            'creation that did not happen'
        )

    def test_the_bootstrap_runs_in_the_runner_before_the_server_starts(self):
        """A source-order guard, kept for the reason AC-ARCH-10 keeps its own.

        An executed unit test can prove `ensure_session_secret` works. It
        cannot prove the runner calls it BEFORE `_start_uvicorn_or_exit`, and
        "before the first request" is the whole of D2: a bootstrap that ran
        lazily on a request path would put an unauthenticated caller's request
        in front of a database write.

        Written by LINE and with comments excluded, and each pattern asserted
        to match EXACTLY ONCE -- not with `str.find` over the raw file. That
        was the shape this guard's sibling in `test_auth_required_gate.py`
        shipped in, and it broke twice: once when a refactor moved the matching
        literal to the top of the file so the ordering assertion became
        permanently true, and once when the same edit put the other pattern
        inside a docstring so the match found prose. Review of #229 caught this
        one still written the old way, in the same PR that fixed the sibling.
        """
        lines = (REPO_ROOT / 'couchpotato' / 'runner.py').read_text(
            encoding='utf-8').splitlines()

        def line_of(needle):
            # Excludes comments AND `def` lines: the CALL is what has to sit
            # before the server starts, and `_start_uvicorn_or_exit(application`
            # matches its own definition too. Tightening this guard is what
            # surfaced that -- `str.find` had been matching the call purely
            # because it happens to come first, so moving the definition above
            # it would have re-targeted the assertion silently.
            hits = [i for i, line in enumerate(lines)
                    if needle in line
                    and not line.strip().startswith('#')
                    and not line.strip().startswith('def ')]
            assert len(hits) == 1, (
                'expected exactly one %r in runner.py, found %d at lines %s. '
                'A pattern that matches more than once silently measures '
                'whichever came first.' % (needle, len(hits), [h + 1 for h in hits])
            )
            return hits[0]

        bootstrap = line_of('ensure_session_secret(')
        serve = line_of('_start_uvicorn_or_exit(application')
        assert bootstrap < serve, (
            'the secret bootstrap now runs AFTER the server starts serving, so '
            'the first requests race the write it was moved out of the request '
            'path to avoid'
        )

    def test_the_bootstrap_is_skipped_when_authentication_is_off(self):
        """AC-QA-21's other half, which no request-path spy can reach.

        A counting spy on the request path passes here whatever the runner
        does, because the request path never writes at all. The only place the
        "auth off never grows a secret row" promise can actually be broken is
        the runner, and the runner is not callable from a unit test without
        starting a server -- so this reads the structure instead: the
        bootstrap call must sit inside an `if auth_is_required():`.
        """
        tree = ast.parse((REPO_ROOT / 'couchpotato' / 'runner.py').read_text(encoding='utf-8'))

        guarded = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not (isinstance(test, ast.Call) and getattr(test.func, 'id', None) == 'auth_is_required'):
                continue
            body = '\n'.join(ast.unparse(statement) for statement in node.body)
            if 'ensure_session_secret(' in body:
                guarded.append(body)

        assert len(guarded) == 1, (
            'the session secret bootstrap is not inside an '
            '`if auth_is_required():` in runner.py, so an install that never '
            'turned authentication on grows a secret row it will never use -- '
            'and gains a database write on a path it did not have one before'
        )

    def test_exactly_one_function_writes_the_secret(self, env):
        """AC-ARCH-3, by grep over the shipped source."""
        sources = {
            path: path.read_text(encoding='utf-8')
            for path in (REPO_ROOT / 'couchpotato').rglob('*.py')
        }
        writers = {path: text for path, text in sources.items()
                   if '_write_session_secret(' in text}

        assert set(writers) == {REPO_ROOT / 'couchpotato' / '__init__.py'}, (
            'the session secret is written from more than one file: %r'
            % sorted(str(path) for path in writers)
        )
        # Named, not counted. A bare count says nothing about WHERE the calls
        # are, and the point of AC-ARCH-3 is that the three triggers -- startup
        # bootstrap, logout and password change -- all funnel through this one
        # writer rather than any of them writing the property row itself.
        tree = ast.parse(sources[REPO_ROOT / 'couchpotato' / '__init__.py'])
        callers = sorted(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and any(getattr(call.func, 'id', None) == '_write_session_secret'
                    for call in ast.walk(node) if isinstance(call, ast.Call))
        )

        assert callers == ['ensure_session_secret', 'rotate_session_secret'], callers

    def test_no_other_module_writes_the_secret_property_row(self):
        """The writer being alone is only half of it.

        Anything that inserted or updated a `property` document with the secret
        identifier directly would bypass the retry-on-conflict in
        `_write_session_secret`, and a lost compare-and-swap there becomes a
        SECOND row -- after which the lookup returns whichever SQLite hands
        back first and sessions verify or not at random.

        Scoped per FUNCTION, not per file. `couchpotato/core/database.py` names
        the identifier -- that is how `database.document.update` REFUSES to
        touch the row (AC-SEC-40) -- and separately calls `db.update` for
        ordinary documents. A file-level grep calls that an offender forever,
        which would end with the check being deleted or allowlisted into
        uselessness. What actually matters is a function that knows the
        identifier AND writes.
        """
        writes = {'insert', 'update', 'delete', 'setProperty'}
        offenders = []

        for path in sorted((REPO_ROOT / 'couchpotato').rglob('*.py')):
            if path == REPO_ROOT / 'couchpotato' / '__init__.py':
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                names = {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}
                if 'SESSION_SECRET_PROPERTY' not in names:
                    continue
                called = {getattr(call.func, 'attr', None)
                          for call in ast.walk(node) if isinstance(call, ast.Call)}
                if called & writes:
                    offenders.append('%s:%s' % (path.relative_to(REPO_ROOT), node.name))

        assert offenders == [], offenders


class TestVerificationNeverWrites:
    """AC-ARCH-6: the read path cannot create, rotate or repair a secret."""

    def test_verification_with_a_broken_store_does_not_call_the_writer(self, env, monkeypatch):
        secret = ensure_session_secret(env.db)
        token = mint_session_token(secret, SESSION_LIFETIME)
        before = env.db.get('id', secret_rows(env.db)[0]['_id'])

        writes = []
        monkeypatch.setattr('couchpotato._write_session_secret',
                            lambda *args, **kwargs: writes.append(args))
        # `Settings.getProperty` is the RIGHT fault here, not the discredited
        # one: `get_current_user` reads via `Env.prop` -> `getProperty`, so
        # this breaks the actual path being exercised. It is only the wrong
        # fault for `ensure_session_secret`'s bootstrap read
        # (`_session_secret_row`, straight against the adapter), which is why
        # the login-creation tests in `TestFailClosedWhenTheSecretIsUnavailable`
        # break `SQLiteAdapter._query_index` instead (T13/D17).
        monkeypatch.setattr(Settings, 'getProperty',
                            lambda self, identifier: (_ for _ in ()).throw(RuntimeError('store down')))

        assert get_current_user(_request(token)) is None
        assert writes == [], 'verification wrote to the property store'

        monkeypatch.undo()
        assert env.db.get('id', before['_id']) == before, (
            'the stored secret changed while verification was failing'
        )

    def test_the_verification_path_does_not_mention_the_writer_at_all(self):
        for function in (get_current_user, get_session_secret, verify_session_token):
            body = implementation_of(function)
            assert '_write_session_secret' not in body, function.__name__
            assert 'ensure_session_secret' not in body, function.__name__
            assert 'setProperty' not in body, function.__name__


def _request(cookie=None):
    from types import SimpleNamespace
    return SimpleNamespace(cookies=({SESSION_COOKIE_NAME: cookie} if cookie else {}))


class TestTheCookieIsNotTheApiKey:
    """AC-SEC-30, AC-SIMP-9."""

    def test_a_successful_login_does_not_hand_back_the_api_key(self, env):
        from couchpotato.core.helpers.variable import md5
        env.data['password'] = md5('hunter2')
        ensure_session_secret(env.db)

        response = client().post('/login/', data={'username': 'admin', 'password': 'hunter2'})

        token = response.cookies.get(SESSION_COOKIE_NAME)
        assert token, 'a correct login issued no session cookie'
        assert API_KEY not in token, (
            'the session cookie still contains the api_key, so reading it is '
            'still full API access: add, rename, movie.delete?delete_from=all'
        )

    def test_a_cookie_whose_value_is_the_api_key_is_refused(self, env):
        ensure_session_secret(env.db)

        assert get_current_user(_request(API_KEY)) is None, (
            'the api_key was accepted as a session cookie. Every browser that '
            'logged in before this change holds exactly that value, and D5 '
            'says they are refused from the first request after upgrade.'
        )

    def test_get_current_user_never_compares_the_cookie_to_the_api_key(self):
        """AC-SIMP-9: the branch is DELETED, not kept as a fallback.

        A fallback would mean the api_key still authenticates the browser,
        which is the entire defect this PR exists to remove.
        """
        body = implementation_of(get_current_user)

        assert 'api_key' not in body, (
            'get_current_user still reads the api_key:\n%s' % body
        )

    def test_the_api_key_valued_cookie_is_refused_through_the_real_app(self, env):
        ensure_session_secret(env.db)
        test_client = client()
        test_client.cookies.set(SESSION_COOKIE_NAME, API_KEY)

        response = test_client.get('/')

        assert response.status_code in (302, 307)
        assert 'login' in response.headers.get('location', '')


class TestTheCookieCannotLockThePlainHttpOperatorOut:
    """The failure this whole spec exists to prevent.

    PR 2 shipped a one-click unrecoverable lockout, and an earlier attempt at
    this same surface failed OPEN for a week. `secure` is the shape that does
    it here: on a plain-HTTP deployment (which the production one is,
    http://homemedia.maeewing.com:5050) the browser silently drops a Secure
    cookie, the redirect to `/` bounces straight back to `/login/`, and the
    operator is locked out by an upgrade with nothing in the log.
    """

    @pytest.fixture
    def logged_in(self, env):
        from couchpotato.core.helpers.variable import md5
        env.data['password'] = md5('hunter2')
        ensure_session_secret(env.db)
        return client()

    def test_the_cookie_is_not_marked_secure_on_a_plain_http_login(self, logged_in):
        response = logged_in.post('/login/', data={'username': 'admin', 'password': 'hunter2'})

        header = response.headers.get('set-cookie', '')
        assert header, 'no Set-Cookie at all'
        assert 'secure' not in header.lower(), (
            'the session cookie is marked Secure. Served over http the browser '
            'drops it, so the operator logs in successfully and lands back on '
            'the login page forever. Header was: %r' % header
        )

    def test_the_cookie_is_httponly(self, logged_in):
        response = logged_in.post('/login/', data={'username': 'admin', 'password': 'hunter2'})

        assert 'httponly' in response.headers.get('set-cookie', '').lower()

    def test_a_plain_http_login_reaches_the_app_root_rather_than_looping(self, env):
        """Bounded hops, so an infinite `/` -> `/login/` bounce fails here."""
        from couchpotato.core.helpers.variable import md5
        env.data['password'] = md5('hunter2')
        ensure_session_secret(env.db)

        test_client = client()
        login = test_client.post('/login/', data={'username': 'admin', 'password': 'hunter2'})
        assert login.status_code == 302

        hops = 0
        response = test_client.get(login.headers['location'])
        while response.status_code in (302, 307) and hops < 3:
            hops += 1
            response = test_client.get(response.headers['location'])

        assert response.status_code == 200, (
            'a correct login did not reach a served page in %d hops; the last '
            'response was %s to %r -- this is the lockout shape'
            % (hops, response.status_code, response.headers.get('location'))
        )
        assert hops == 0, 'the login redirect took %d extra hops' % hops

    def test_remember_me_persists_the_cookie_and_the_default_does_not(self, logged_in):
        """Unchanged from before this PR, deliberately.

        Without "remember me" the cookie dies with the browser process, which
        is the more conservative of the two and is what operators already have.
        The signed expiry is what bounds it SERVER-side either way.
        """
        remembered = logged_in.post('/login/', data={
            'username': 'admin', 'password': 'hunter2', 'remember_me': '1'})
        assert 'max-age=%d' % (30 * 24 * 3600) in remembered.headers['set-cookie'].lower()

        plain = logged_in.post('/login/', data={'username': 'admin', 'password': 'hunter2'})
        assert 'max-age' not in plain.headers['set-cookie'].lower()


class TestFailClosedWhenTheSecretIsUnavailable:
    """AC-SEC-33."""

    @pytest.fixture
    def broken_store(self, env, monkeypatch):
        """Breaks the read at the ADAPTER, the level every consumer shares.

        `Settings.getProperty` calls `db.get('property', ...)`, and
        `ensure_session_secret`'s `_session_secret_row` calls `db.query('property',
        ...)` directly -- both end up in `SQLiteAdapter._query_index` for a
        named index. Patching `_query_index` therefore breaks both real read
        paths from one fault, the way a genuinely unreadable store would.

        This is deliberately NOT a patch of `Settings.getProperty` itself:
        that method's own `except Exception:` swallows whatever `_query_index`
        raises and returns None, so patching `getProperty` to raise bypasses
        that handler and never gets exercised by a real fault -- which is
        exactly the defect T13 removed `session_secret_store_is_readable()`
        for. A version of this fixture that patched `getProperty` let
        `test_login_issues_no_cookie_when_the_secret_cannot_be_read` below pass
        while a login against a raising store actually issued a cookie: proven
        by running it after T13's other changes landed, before this fixture
        was fixed.
        """
        monkeypatch.setattr(
            SQLiteAdapter, '_query_index',
            lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError('store down')))
        return env

    def test_login_issues_no_cookie_when_the_secret_cannot_be_read(self, broken_store):
        from couchpotato.core.helpers.variable import md5
        broken_store.data['password'] = md5('hunter2')

        response = client().post('/login/', data={'username': 'admin', 'password': 'hunter2'})

        assert SESSION_COOKIE_NAME not in response.cookies, (
            'a session cookie was issued while the signing secret was '
            'unreadable, so it was signed with something that is not a secret'
        )
        assert 'set-cookie' not in response.headers

    def test_login_against_a_raising_store_creates_no_secret(self, env, monkeypatch):
        """The other half of AC-SEC-33 for the CREATE-on-unreadable-store case:
        no cookie is necessary but not sufficient. There is no pre-existing
        secret here (asserted below) -- a store that raises on read must not
        be treated as merely absent and bootstrapped into, because the next
        successful login could then find EITHER row non-deterministically,
        and because a login that "succeeded" against a store it could not
        actually read is not a login anyone should trust. So this is pinned
        independently rather than inferred from the cookie assertion above.

        The OVERWRITE case -- a secret already exists and a raising store
        must not have it replaced under it, which would invalidate every
        OTHER live session on the strength of a transient fault -- is covered
        separately by
        `test_session_secret_recovery.py::TestAnUnreadableStoreIsNotAnAbsentSecret::test_a_login_against_a_raising_store_writes_nothing`,
        whose fixture requires a pre-existing row for exactly that reason.

        Checks `secret_rows` before patching `_query_index` and again after
        undoing the patch, deliberately: `secret_rows` itself reads through
        `_query_index`, so evaluating it while the patch is still active would
        raise instead of asserting.
        """
        from couchpotato.core.helpers.variable import md5
        env.data['password'] = md5('hunter2')

        assert secret_rows(env.db) == [], (
            'a secret already existed before the login attempt, so this test '
            'cannot tell a write from a pre-existing row'
        )

        monkeypatch.setattr(
            SQLiteAdapter, '_query_index',
            lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError('store down')))

        client().post('/login/', data={'username': 'admin', 'password': 'hunter2'})

        monkeypatch.undo()
        assert secret_rows(env.db) == [], (
            'a login against a store that cannot be READ wrote a secret to it '
            '-- signing every device out on the strength of a transient fault'
        )

    def test_a_previously_valid_cookie_is_refused_when_the_secret_cannot_be_read(self, env, monkeypatch):
        secret = ensure_session_secret(env.db)
        token = mint_session_token(secret, SESSION_LIFETIME)
        assert get_current_user(_request(token)) is True

        # `Settings.getProperty` is the real path this assertion drives:
        # `get_current_user` -> `get_session_secret` -> `Env.prop` ->
        # `getProperty`. Not the discredited pattern (T13/D17) -- that applies
        # to `ensure_session_secret`'s bootstrap read, which never calls
        # `getProperty` at all.
        monkeypatch.setattr(Settings, 'getProperty',
                            lambda self, identifier: (_ for _ in ()).throw(RuntimeError('store down')))

        assert get_current_user(_request(token)) is None

    def test_one_error_names_the_config_ini_recovery_path(self, broken_store, caplog):
        with caplog.at_level(logging.ERROR):
            get_session_secret()

        errors = [record for record in caplog.records if record.levelno >= 40]
        assert len(errors) == 1, (
            'expected exactly one ERROR, got %r'
            % [record.getMessage() for record in errors]
        )
        message = errors[0].getMessage()
        assert 'config.ini' in message, (
            'the log line the locked-out operator will be reading does not '
            'name the recovery path: %r' % message
        )
        assert 'auth_required = 0' in message

    def test_the_error_does_not_leak_the_secret_or_the_api_key(self, env, caplog):
        secret = ensure_session_secret(env.db)
        with caplog.at_level(logging.DEBUG):
            get_session_secret()
            get_current_user(_request(mint_session_token(secret, SESSION_LIFETIME)))

        logged = '\n'.join(record.getMessage() for record in caplog.records)
        assert secret not in logged
        assert API_KEY not in logged

    def test_an_absent_secret_fails_closed_rather_than_verifying_with_nothing(self, env):
        """No secret has ever been created: nothing may authenticate."""
        assert secret_rows(env.db) == []

        assert get_session_secret() is None
        assert get_current_user(_request('anything')) is None
        assert get_current_user(_request('%d.x' % (2 ** 31))) is None


class TestSessionsSurviveARestart:
    """AC-QA-16."""

    def test_a_session_survives_rebuilding_the_app_against_the_same_database(self, env):
        secret = ensure_session_secret(env.db)
        token = mint_session_token(secret, SESSION_LIFETIME)

        rebuilt = client()
        rebuilt.cookies.set(SESSION_COOKIE_NAME, token)

        assert rebuilt.get('/login/').status_code in (302, 307), (
            'the session was not accepted after the app was rebuilt, so the '
            'secret is being regenerated per process rather than read back -- '
            'every restart would sign the operator out'
        )

    def test_rebuilding_against_a_different_database_refuses_the_token(self, env, tmp_path):
        secret = ensure_session_secret(env.db)
        token = mint_session_token(secret, SESSION_LIFETIME)

        other = make_db(tmp_path / 'other-db')
        try:
            Env.set('db', other)
            ensure_session_secret(other)

            assert get_current_user(_request(token)) is None, (
                'a token minted under one database verified against another. '
                'The secret is not actually coming from the store.'
            )
        finally:
            Env.set('db', env.db)
            other.close()


class TestAuthOffRunsNoSessionMachinery:
    """AC-QA-21: an install that never enabled auth never grows a secret row."""

    @pytest.fixture
    def auth_off(self, env):
        env.data['auth_required'] = 0
        env.data['password'] = ''
        return env

    def test_a_garbage_cookie_is_harmless_when_auth_is_off(self, auth_off):
        test_client = client(follow_redirects=True)
        test_client.cookies.set(SESSION_COOKIE_NAME, 'garbage.garbage')

        assert test_client.get('/login/').status_code == 200
        assert get_current_user(_request('garbage.garbage')) is True

    def test_the_property_store_is_never_written_when_auth_is_off(self, auth_off, monkeypatch):
        """Two spies, deliberately.

        AC-QA-21 names a counting spy on `setProperty`, and that one is kept.
        On its own it would be VACUOUS against this implementation: the secret
        is written by `_write_session_secret`, not by `setProperty`, because
        `setProperty`'s bare `except Exception:` is what AC-DATA-3 forbids. So
        the load-bearing spy is the one on the actual writer, and the
        `setProperty` spy guards against the write moving back there.
        """
        set_property_calls = []
        writer_calls = []
        monkeypatch.setattr(Settings, 'setProperty',
                            lambda self, identifier, value='': set_property_calls.append(identifier))
        monkeypatch.setattr('couchpotato._write_session_secret',
                            lambda *args, **kwargs: writer_calls.append(args))

        test_client = client(follow_redirects=True)
        test_client.cookies.set(SESSION_COOKIE_NAME, 'garbage.garbage')
        test_client.get('/login/')
        get_current_user(_request('garbage.garbage'))
        get_current_user(_request())

        assert set_property_calls == [], set_property_calls
        assert writer_calls == [], writer_calls
        assert secret_rows(auth_off.db) == [], (
            'an install with authentication off grew a session secret row'
        )


class TestTheLiteralsLiveInExactlyOnePlace:
    """AC-ARCH-2."""

    @pytest.fixture
    def sources(self):
        return {path: path.read_text(encoding='utf-8')
                for path in (REPO_ROOT / 'couchpotato').rglob('*.py')}

    def test_the_hmac_computation_appears_in_one_file(self, sources):
        files = sorted(str(path.relative_to(REPO_ROOT)) for path, text in sources.items()
                       if 'hmac.new(' in text)

        assert files == ['couchpotato/__init__.py'], files

    def test_the_cookie_name_literal_appears_in_one_file(self, sources):
        files = sorted(str(path.relative_to(REPO_ROOT)) for path, text in sources.items()
                       if "SESSION_COOKIE_NAME = '" in text)

        assert files == ['couchpotato/__init__.py'], files

        # And nowhere does a bare literal name the cookie again. A rename that
        # half-lands issues a cookie under one name and reads another, which
        # signs everybody out with no error anywhere.
        bare = sorted(
            str(path.relative_to(REPO_ROOT)) for path, text in sources.items()
            if any(pattern in text for pattern in (
                "cookies.get('user')", "set_cookie('user'", "delete_cookie('user'"))
        )
        assert bare == [], (
            'a bare "user" cookie-name literal reappeared outside the '
            'constant: %r' % bare
        )

    def test_the_secret_property_key_literal_appears_in_one_file(self, sources):
        files = sorted(str(path.relative_to(REPO_ROOT)) for path, text in sources.items()
                       if "SESSION_SECRET_PROPERTY = '" in text)

        assert files == ['couchpotato/__init__.py'], files


class TestNoNewRuntimeDependency:
    """AC-SIMP-1."""

    def test_requirements_txt_is_unmodified_by_this_change(self):
        requirements = (REPO_ROOT / 'requirements.txt').read_text(encoding='utf-8').lower()

        assert 'itsdangerous' not in requirements, (
            'Starlette SessionMiddleware needs itsdangerous, and it binds its '
            'secret at app-construction time, which defeats rotate-on-logout'
        )

    def test_the_session_code_uses_the_standard_library_only(self):
        source = (REPO_ROOT / 'couchpotato' / '__init__.py').read_text(encoding='utf-8')

        assert 'SessionMiddleware' not in source
        assert 'itsdangerous' not in source
        for module in ('import hmac', 'import hashlib', 'import secrets', 'import base64'):
            assert module in source, module
