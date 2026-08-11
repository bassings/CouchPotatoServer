"""Ending a session actually ends it. AC-SEC-36, AC-SEC-37, AC-SEC-38.

The defect this file pins is not that logout was missing -- it existed. It is
that `response.delete_cookie(...)` asks the BROWSER to forget a value, and the
browser is the one party that was never the threat. Anyone who already had the
cookie kept it, and there was no server-side state to revoke.

A stateless signed cookie holds no per-session record, so under the settled
"no new table" constraint the only revocation available is rotating the shared
signing secret (D1). That ends every session on every device, which is the
correct behaviour for one operator and is what the control's copy must say.

Rotation being that powerful is exactly why AC-SEC-37 exists. `logout` was a
public unauthenticated GET, so under D1 a cross-site `<img src="/logout/">` on
any page the operator visited would have terminated every session on every
device, repeatedly, with nothing to see in the UI but a login page. It is now
an authenticated POST: `SameSite=Lax` keeps a cross-site POST from carrying the
cookie at all, and `require_auth` means the handler never runs without one.

Everything here is driven through the real routes against a real
`SQLiteAdapter` and the real property store. A test that asserted only on the
`Set-Cookie` deletion header would pass against the defect.
"""
import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from couchpotato import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    SESSION_SECRET_PROPERTY,
    ensure_session_secret,
    get_current_user,
    mint_session_token,
    rotate_session_secret,
    verify_session_token,
)
from couchpotato.api import api, api_docs, api_docs_missing, api_locks, api_nonblock
from couchpotato.core import event as event_module
from couchpotato.core.db.sqlite_adapter import SQLiteAdapter
from couchpotato.core.event import fireEvent
from couchpotato.core.helpers.variable import hash_password, md5
from couchpotato.core.settings import Settings
from couchpotato.environment import Env

sys.path.insert(0, str(Path(__file__).resolve().parent))

from env_helper import env_restored  # noqa: E402

API_KEY = 'notarealapikey' + '0' * 18
REPO_ROOT = Path(__file__).resolve().parents[2]

PASSWORD = 'hunter2'
#: bcrypt is deliberately slow, so it is paid once for the whole module rather
#: than once per login. Stored in the form `login_post` actually compares
#: against: bcrypt OVER the md5 of the plaintext, which is what the login path
#: computes (see `Core.md5Password`).
STORED_PASSWORD = hash_password(md5(PASSWORD))


class FakeSettings(Settings):
    """The REAL `getProperty` / `setProperty` over an in-memory config."""

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


def _build_env(tmp_path, settings_overrides=None, bootstrap_secret=True):
    """A real adapter, a real `Core` plugin on the real event bus, a real app.

    `Core()` is instantiated for real rather than through `Core.__new__`, so
    the `setting.save.core.password` wiring under test is the shipped wiring
    and not something this file arranged. Two globals it touches are saved and
    restored: the signal handlers (skipped by pretending to be the desktop
    build) and the process-wide default socket timeout.

    `settings_overrides` and `bootstrap_secret` exist for the auth-OFF install
    of D12, which must be built the same way as the protected one in every
    respect except the two that define it: no password, `auth_required = 0`,
    and no secret ever created. Building that install by hand in a second
    fixture would let the two drift, and the interesting assertion is precisely
    that the same POST behaves differently.
    """
    old_api = dict(api)
    old_locks = dict(api_locks)
    old_nonblock = dict(api_nonblock)
    old_docs = dict(api_docs)
    old_missing = list(api_docs_missing)
    old_events = {name: list(handlers) for name, handlers in event_module.events.items()}
    old_timeout = socket.getdefaulttimeout()

    db = SQLiteAdapter()
    db.create(str(tmp_path / 'db'))

    values = {
        'username': '',
        'password': STORED_PASSWORD,
        'api_key': API_KEY,
        'auth_required': 1,
        'rate_limit_max': 0,
        'cors_origins': '',
        'ssl_cert': '',
        'ssl_key': '',
    }
    values.update(settings_overrides or {})
    settings = FakeSettings(values)

    # `env_restored()` like the five sibling modules this PR added
    # (`test_hostile_session_cookies`, `test_session_rejection_logging`,
    # `test_session_secret_recovery`, `test_session_upgrade_path`,
    # `test_auth_required_migration`). Without it this fixture restored the
    # api registry, the event bus, the socket timeout and `desktop`, but left
    # `Env._db` pointing at an adapter it had just CLOSED, plus `_settings`,
    # `web_base`, `api_base`, `data_dir`, `app_dir` and `dev` at this test's
    # values -- which is the positional leakage already recorded as debt on
    # this plan.
    with env_restored():
        Env.set('db', db)
        Env.set('settings', settings)
        Env.set('web_base', '/')
        Env.set('api_base', '/api/%s/' % API_KEY)
        Env.set('static_path', '/static/')
        Env.set('app_dir', str(REPO_ROOT))
        Env.set('data_dir', str(tmp_path))
        Env.set('dev', False)
        # Skips `Core.signalHandler`, which would replace this process's SIGINT and
        # SIGTERM handlers for the rest of the pytest run.
        Env.set('desktop', True)

        from couchpotato.core._base._core import Core
        Core()

        secret = ensure_session_secret(db) if bootstrap_secret else None

        from couchpotato import create_app
        app = create_app(API_KEY, '/')

        yield type('EnvHandle', (), {
            'db': db, 'settings': settings, 'secret': secret, 'app': app,
            'tmp_path': tmp_path,
        })

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


@pytest.fixture
def env(tmp_path):
    """The protected install: `auth_required = 1`, a password, a secret."""
    yield from _build_env(tmp_path)


@pytest.fixture
def open_env(tmp_path):
    """The install that never enabled authentication (D12).

    No password and an explicit `auth_required = 0`, which is what
    `runner.py`'s startup migration writes back on a default install -- so this
    is the MOST COMMON configuration this project ships, not an edge case. No
    secret is bootstrapped, because `runner.py` only bootstraps one when
    `auth_is_required()`.
    """
    yield from _build_env(
        tmp_path,
        settings_overrides={'password': '', 'auth_required': 0},
        bootstrap_secret=False,
    )


def client(env):
    return TestClient(env.app, follow_redirects=False)


def log_in(env) -> tuple:
    """A real POST /login/, returning (client, cookie value)."""
    session = client(env)
    response = session.post('/login/', data={'username': '', 'password': PASSWORD})

    assert response.status_code == 302, response.text
    token = session.cookies.get(SESSION_COOKIE_NAME)
    assert token, 'login issued no session cookie: %r' % response.headers.get('set-cookie')
    return session, token


def replay(env, token):
    """A FRESH client holding `token` -- the thief, not the browser that left."""
    session = client(env)
    session.cookies.set(SESSION_COOKIE_NAME, token)
    return session


def is_signed_in(session) -> bool:
    response = session.get('/')
    if response.status_code == 200:
        return True
    assert response.status_code == 302, response.status_code
    assert 'login' in response.headers.get('location', '')
    return False


def change_password(value):
    """Mirror `Settings.saveView`'s real event sequence for `core.password`
    (settings.py), rather than `env.settings.saveView(...)` -- `FakeSettings`
    has no real `self.p` (ConfigParser), which `saveView`'s own
    `isOptionWritable` needs, so calling it directly raises `AttributeError`.

    Firing only the value hook, as every test here used to, is no longer
    enough. T14 moved rotation to `setting.save.core.password.committed`,
    fired by `saveView` only once `self.save()` has returned without raising
    -- deliberately NOT `.after`, which `fireEvent` auto-fires as an
    intrinsic side effect of firing the value-hook event itself, before any
    save happens at all (`couchpotato/core/event.py`). So the two calls below
    are not interchangeable with one: the first alone reproduces exactly the
    "rotates before the commit" defect T14 fixes.

    **This is a COPY of `saveView`'s event sequence, not `saveView` itself**
    (review L3, 2026-08-11). If `Settings.saveView` ever stopped firing
    `.committed` -- a typo, a refactor, a merge conflict -- every test built
    on this helper would keep passing while real password changes silently
    stopped revoking sessions, because this function would still fire it
    regardless. The only place that verifies `saveView` ITSELF still fires
    `.committed` is `test_password_rotation_after_commit.py`, which drives the
    real method end to end (`TestASuccessfulSaveActuallyRotates`,
    `TestARealSaveFiresTheRotationExactlyOnce`). Do not trim those as
    "redundant with this file": they are the only guard standing between a
    drifted `saveView` and a false-green AC-SEC-38 suite here. (`FakeSettings`
    in this module has no real `self.p` ConfigParser, which `saveView`'s
    `isOptionWritable` needs, so pointing these tests at the real method
    directly is not a small change -- see the class docstring above
    `TestChangingThePasswordEndsEverySession` for the trade this file makes
    instead.)
    """
    stored = fireEvent('setting.save.core.password', value, single=True)
    fireEvent('setting.save.core.password.committed', single=True)
    return stored


class TestLogoutRevokesRatherThanForgets:
    """AC-SEC-36 / D1."""

    def test_a_cookie_captured_before_logout_is_refused_after_it(self, env):
        owner, token = log_in(env)
        thief = replay(env, token)

        assert is_signed_in(thief), (
            'the captured cookie was not valid to begin with, so the assertion '
            'below would pass without revoking anything'
        )

        assert owner.post('/logout/').status_code in (302, 303)

        assert not is_signed_in(thief), (
            'the cookie captured before logout still works. Logout asked the '
            'browser to forget a value the thief already had; it revoked '
            'nothing.'
        )

    def test_logging_out_ends_the_session_on_the_other_device_too(self, env):
        """D1 is deliberately not "this browser only", and must be visibly so.

        If this ever passes only for the browser that clicked, the sign-out
        copy tranche C renders becomes a lie about the security property the
        operator is relying on.
        """
        phone, _ = log_in(env)
        laptop, _ = log_in(env)

        phone.post('/logout/')

        assert not is_signed_in(laptop)

    def test_the_secret_actually_changed_rather_than_the_cookie_being_cleared(self, env):
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        owner, _ = log_in(env)

        owner.post('/logout/')

        after = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        assert after != before
        assert len(bytes.fromhex(after)) == 32

    def test_only_one_secret_row_survives_a_hundred_logout_cycles(self, env):
        """AC-SEC-46: rotation must update the row, never accumulate rows.

        A second row with the same identifier makes the lookup return whichever
        SQLite hands back first, after which sessions verify or not at random.

        The cookie is minted against the current secret rather than obtained by
        a real password POST: bcrypt costs 166 ms a login here, so a hundred of
        those would put 17 seconds into the unit suite to exercise a code path
        that is not the one under test. Everything downstream of the cookie --
        the route, `require_auth`, the rotation and the property store -- is
        real.
        """
        for _ in range(100):
            current = env.settings.getProperty(SESSION_SECRET_PROPERTY)
            session = replay(env, mint_session_token(current, SESSION_LIFETIME))
            assert session.post('/logout/').status_code in (302, 303)

        rows = [row for row in env.db._query_index('property', key=SESSION_SECRET_PROPERTY)
                if row.get('identifier') == SESSION_SECRET_PROPERTY]
        assert len(rows) == 1, 'logout accumulated %d secret rows' % len(rows)

    def test_a_rotation_that_fails_does_not_report_a_successful_sign_out(self, env, monkeypatch):
        """The failure mode that must not be smoothed over.

        If the store is unwritable, the honest outcomes are "error" or
        "still signed in". The tempting one -- log it, clear the cookie,
        redirect to the login page -- is the worst available: the operator sees
        exactly what a successful sign-out looks like while the token in
        somebody else's hands stays valid. That is a door locked in appearance
        only, which is the defect class this whole PR exists to close.
        """
        owner, token = log_in(env)

        def explode(*args, **kwargs):
            raise RuntimeError('property store is down')

        monkeypatch.setattr('couchpotato.rotate_session_secret', explode)

        response = owner.post('/logout/')

        assert response.status_code == 500, (
            'a failed revocation answered %d, which the operator reads as '
            '"signed out"' % response.status_code
        )
        assert 'set-cookie' not in response.headers, (
            'the cookie was cleared even though nothing was revoked, so the '
            'browser looks signed out while the token still works'
        )
        assert is_signed_in(replay(env, token))

    def test_ending_sessions_costs_no_integration(self, env):
        """AC-PROD-3: the whole point of not reusing the api_key as the cookie.

        Rotating the api_key breaks the userscript, every script and every
        downloader at once, which is why nobody ever did it and a leaked cookie
        was valid forever.
        """
        owner, _ = log_in(env)
        key_before = env.settings.get('api_key')

        owner.post('/logout/')

        assert env.settings.get('api_key') == key_before
        api_response = client(env).get('/api/%s/app.available' % API_KEY)
        assert api_response.status_code == 200, api_response.text


class TestRevocationIsNotReachableWithoutASession:
    """AC-SEC-37."""

    def test_an_unauthenticated_logout_leaves_another_clients_session_valid(self, env):
        victim, _ = log_in(env)
        stranger = client(env)

        response = stranger.post('/logout/')

        assert response.status_code == 302
        assert 'login' in response.headers.get('location', '')
        assert is_signed_in(victim), (
            'an unauthenticated POST to /logout/ terminated somebody else\'s '
            'session. Under D1 that is every session on every device, and it '
            'can be repeated indefinitely.'
        )

    def test_a_cross_site_image_get_cannot_revoke_anything(self, env):
        """`<img src="/logout/">` is the concrete attack D1 would have opened.

        A GET is what an image, a prefetch, a link preview and a mail client
        all issue, and none of them can be talked out of it. The route no
        longer answers one.
        """
        victim, _ = log_in(env)

        response = client(env).get('/logout/')

        assert response.status_code == 405, (
            'GET /logout/ is answered, so any cross-site image tag revokes '
            'every session on every device'
        )
        assert is_signed_in(victim)

    def test_an_authenticated_cross_site_image_get_cannot_revoke_either(self, env):
        """The same GET, this time carrying the operator's own cookie.

        `SameSite=Lax` DOES send the cookie on a top-level navigation, so
        "the browser will not send it" is not the whole defence and must not
        be the only one.
        """
        victim, _ = log_in(env)

        assert victim.get('/logout/').status_code == 405
        assert is_signed_in(victim)

    def test_a_client_with_a_broken_cookie_can_still_reach_the_login_page(self, env):
        """The route back in, which is what makes this safe to enforce.

        Requiring a session to log OUT is only acceptable while a client
        holding an unusable session can still get to the form. This is the
        assertion standing between AC-SEC-37 and a lockout.
        """
        stuck = client(env)
        stuck.cookies.set(SESSION_COOKIE_NAME, 'not-a-token')

        response = stuck.get('/login/')

        assert response.status_code == 200
        assert 'password' in response.text.lower()

    def test_a_client_with_an_expired_cookie_can_still_reach_the_login_page(self, env):
        import time as _time

        stuck = client(env)
        stuck.cookies.set(
            SESSION_COOKIE_NAME,
            mint_session_token(env.secret, SESSION_LIFETIME, now=_time.time() - SESSION_LIFETIME - 1),
        )

        response = stuck.get('/login/')

        assert response.status_code == 200
        assert 'password' in response.text.lower()

    def test_a_client_whose_secret_was_rotated_away_can_still_reach_the_login_page(self, env):
        owner, token = log_in(env)
        rotate_session_secret(env.db)

        response = owner.get('/login/')

        assert response.status_code == 200
        assert 'password' in response.text.lower()

    def test_the_logout_route_carries_the_auth_dependency(self, env):
        """Structural, so a future refactor cannot quietly drop `Depends`.

        The behavioural tests above would still pass if `require_auth` were
        replaced by an in-handler check that a later edit removed.
        """
        from fastapi.routing import APIRoute

        logout_routes = [
            route for route in env.app.routes
            if isinstance(route, APIRoute) and route.path in ('/logout', '/logout/')
        ]
        assert logout_routes, 'no /logout route is served at all'

        for route in logout_routes:
            names = {getattr(d.call, '__name__', '') for d in route.dependant.dependencies}
            assert 'require_auth' in names, route.path
            assert route.methods == {'POST'}, (
                '%s answers %r; a revocation that any GET can trigger is a '
                'cross-site request forgery' % (route.path, route.methods)
            )


def _every_document(db):
    """A comparable snapshot of the whole store.

    Compared as sorted JSON rather than by hashing the SQLite file: the file
    changes for reasons that are not writes (page cache, journal), so a hash
    would be flaky in the direction that costs the most -- a failure nobody
    trusts gets re-run until it is green.
    """
    import json as _json
    return sorted(_json.dumps(doc, sort_keys=True, default=str) for doc in db.all('id'))


class TestLogoutWritesNothingWhenAuthenticationIsOff:
    """D12: the unauthenticated database write this PR introduced.

    With `auth_required` off, `get_current_user` returns True for everyone, so
    `require_auth` passes everyone, so ANY caller -- with no credentials at all
    -- reached the rotation path and caused a write. Measured against the real
    app before the fix::

        auth_is_required(): False
        rows before        : 0
        POST /logout/      : 303
        rows after         : 1      _t=property identifier=session_secret

    It grants no access, because such an install serves everything to everyone
    anyway, and it is bounded to one row. It is still an unauthenticated write
    to the operator's database, and it contradicts AC-QA-21 ("the property
    store is never written") and AC-SEC-46 ("the change persists exactly one new
    document") -- both of which promise that an install which never enabled
    authentication never grows a secret row.

    The fix is one condition, and it lives at the logout CALL SITE rather than
    inside `rotate_session_secret`: the rotation function is also D6's
    (`setting.save.core.password`), whose ordering already sets
    `auth_required = 1` before rotating. A guard inside the rotation would make
    D6 depend on that ordering silently, and a later edit to the order would
    turn the password-change revocation off with nothing failing.
    """

    def test_an_unauthenticated_logout_writes_no_document_at_all(self, open_env):
        before = _every_document(open_env.db)

        response = client(open_env).post('/logout/')

        assert response.status_code in (302, 303), response.status_code
        assert _every_document(open_env.db) == before, (
            'POST /logout/ from a caller who presented no credentials wrote to '
            'the database of an install that never enabled authentication'
        )

    def test_it_never_creates_a_session_secret(self, open_env):
        """Named separately from the snapshot above so the failure says which.

        The snapshot catches any write; this says what the write WAS, which is
        the sentence the operator would otherwise have to reconstruct from a
        JSON diff.
        """
        client(open_env).post('/logout/')

        rows = [row for row in open_env.db._query_index('property', key=SESSION_SECRET_PROPERTY)
                if row.get('identifier') == SESSION_SECRET_PROPERTY]
        assert rows == [], (
            'an install with no password grew a session_secret row: %r' % rows
        )

    def test_fifty_of_them_still_write_nothing(self, open_env):
        """A guard against "writes once, then finds the row and no-ops".

        That shape would pass the two tests above only by accident of ordering,
        and it is still an unauthenticated write.
        """
        before = _every_document(open_env.db)

        stranger = client(open_env)
        for _ in range(50):
            assert stranger.post('/logout/').status_code in (302, 303)

        assert _every_document(open_env.db) == before

    def test_it_does_not_tell_the_operator_that_sessions_were_ended(self, open_env):
        """Copy has to match what happened, which is nothing.

        `?reason=signed_out` renders "You have been signed out on every device",
        and on an install with authentication off that is false in both halves:
        nobody was signed in and nothing was revoked.
        """
        response = client(open_env).post('/logout/')

        assert 'reason=signed_out' not in response.headers.get('location', ''), (
            'an install with authentication off claims to have signed every '
            'device out, having revoked nothing'
        )

    def test_the_protected_install_still_revokes(self, env):
        """The paired positive, so the fix cannot be "logout does nothing".

        The narrow guard and its inverse in one place: same route, same POST,
        opposite outcome, decided only by whether authentication is on.
        """
        owner, token = log_in(env)
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)

        assert owner.post('/logout/').status_code in (302, 303)

        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) != before
        assert not is_signed_in(replay(env, token))


class TestChangingThePasswordEndsEverySession:
    """AC-SEC-38 / D6.

    Driven through `change_password()`, a hand-rolled copy of `saveView`'s
    event sequence -- `FakeSettings` here has no real `self.p` (ConfigParser),
    which `saveView`'s own `isOptionWritable` needs, so calling the real
    method directly raises `AttributeError` (measured). See `change_password`'s
    docstring for the resulting trade: this file proves the session-revocation
    BEHAVIOUR against the copied sequence; `test_password_rotation_after_commit.py`
    is what proves `saveView` itself still produces that sequence.
    """

    def test_a_cookie_issued_before_a_password_change_is_refused_after_it(self, env):
        owner, token = log_in(env)
        thief = replay(env, token)
        assert is_signed_in(thief)

        # Driven through the real `Settings.saveView` (T14: rotation lives on
        # `setting.save.core.password.committed`, fired only after the save
        # commits -- firing the value hook alone, as this test used to,
        # no longer triggers it).
        change_password('a-new-password')

        assert not is_signed_in(thief), (
            'changing the password left every existing session valid. Someone '
            'who has your cookie keeps it, which is the situation a password '
            'change is usually a response to.'
        )

    def test_the_password_fields_description_states_that_consequence(self, env):
        """AC-SEC-38's copy half, asserted next to the behaviour it describes.

        Kept in the SAME test as a driven password change so the two cannot
        drift: a description edited without the rotation, or a rotation
        removed without the description, fails here.
        """
        from couchpotato.core._base._core import config

        options = [option
                   for section in config
                   for group in section['groups']
                   for option in group['options']]
        password = [option for option in options if option['name'] == 'password'][0]
        description = password['description'].lower()

        owner, token = log_in(env)
        change_password('a-new-password')
        assert not verify_session_token(token, env.settings.getProperty(SESSION_SECRET_PROPERTY))

        assert 'sign' in description or 'log' in description, description
        assert 'device' in description or 'everywhere' in description, (
            'the password field does not tell the operator that changing it '
            'signs them out on every device, which is what it now does: %r'
            % password['description']
        )

    def test_clearing_the_password_does_not_grow_a_secret_row_on_a_fresh_install(self, env, tmp_path):
        """The one case that must NOT rotate.

        Clearing the password turns `auth_required` off, so every request is
        already served without a session and there is nothing to revoke. Making
        it write anyway would put a secret row on installs that never enabled
        authentication, which AC-QA-21 and AC-SEC-46 both forbid.
        """
        empty = SQLiteAdapter()
        empty.create(str(tmp_path / 'empty-db'))
        Env.set('db', empty)
        try:
            change_password('')

            rows = [row for row in empty._query_index('property', key=SESSION_SECRET_PROPERTY)
                    if row.get('identifier') == SESSION_SECRET_PROPERTY]
            assert rows == []
        finally:
            empty.close()
            Env.set('db', env.db)

    def test_a_rotation_failure_does_not_raise_out_of_the_save_sequence(self, env):
        """The save-SEQUENCE-level guarantee, not the hook's own guard.

        Renamed from `test_a_failure_to_rotate_does_not_stop_the_password_being_hashed`
        (review M2, 2026-08-11): that name promised a test of the `try/except`
        inside `rotateSessionSecretAfterSave`, but `change_password` reaches
        that hook only through `fireEvent`, whose OWN dispatch loop already
        catches every handler exception (`couchpotato/core/event.py`). So this
        passes -- and always would -- regardless of whether the hook's own
        `try/except` exists; it is observing `fireEvent`'s catch-all, not the
        hook's. What it still legitimately pins: a rotation failure does not
        surface as an error on the request that changed the password, and the
        value hook's own return (the stored hash) is unaffected by what
        happens to rotation afterwards.

        The hook's OWN `try/except` -- reached by calling it directly, the way
        `fireEvent` does not have to be involved -- is tested in
        `test_password_rotation_after_commit.py::TestARotationFailureDoesNotEscapeTheHook`.
        """
        with patch('couchpotato.rotate_session_secret', side_effect=RuntimeError('store down')):
            stored = change_password('a-new-password')  # must not raise

        assert stored.startswith(('$2a$', '$2b$', '$2y$')), stored


class TestRotationTakesEffectImmediately:
    """AC-ARCH-5: no stale cache, no restart."""

    def test_the_very_next_verification_uses_the_new_secret(self, env):
        old_token = mint_session_token(env.secret, SESSION_LIFETIME)
        assert get_current_user(_request(old_token)) is True

        new_secret = rotate_session_secret(env.db)

        assert get_current_user(_request(old_token)) is None, (
            'a cookie minted before the rotation still verifies in the same '
            'process, so something is caching the old secret'
        )
        assert get_current_user(_request(mint_session_token(new_secret, SESSION_LIFETIME))) is True

    def test_a_session_started_after_the_rotation_survives_the_next_request(self, env):
        """Paired positive: rotation must not leave the install unable to log in."""
        rotate_session_secret(env.db)

        session, _ = log_in(env)

        assert is_signed_in(session)
        assert is_signed_in(session), 'the second request after logging in failed'

    def test_ten_consecutive_requests_after_a_rotation_all_succeed(self, env):
        """Guards against a rotation that half-lands and flaps."""
        session, _ = log_in(env)
        rotate_session_secret(env.db)
        after, _ = log_in(env)

        assert all(is_signed_in(after) for _ in range(10))
        assert not is_signed_in(session)


class TestExactlyOneFunctionWritesTheSecret:
    """AC-ARCH-3, driven rather than grepped.

    The grep half lives in `test_session_secret_store.py`; this is the spy that
    proves all three triggers go through it.
    """

    def test_bootstrap_logout_and_password_change_all_go_through_the_writer(self, env, tmp_path, monkeypatch):
        import couchpotato

        real_writer = couchpotato._write_session_secret
        calls = []

        def spy(secret, db=None, attempts=3):
            calls.append(secret)
            return real_writer(secret, db=db, attempts=attempts)

        monkeypatch.setattr(couchpotato, '_write_session_secret', spy)

        fresh = SQLiteAdapter()
        fresh.create(str(tmp_path / 'fresh-db'))
        try:
            ensure_session_secret(fresh)
            assert len(calls) == 1, 'startup bootstrap did not use the writer'

            owner, _ = log_in(env)
            owner.post('/logout/')
            assert len(calls) == 2, 'logout did not use the writer'

            change_password('a-new-password')
            assert len(calls) == 3, 'the password change did not use the writer'
        finally:
            fresh.close()

        assert len(set(calls)) == 3, 'two triggers wrote the same secret'


def _request(cookie=None):
    from types import SimpleNamespace
    return SimpleNamespace(cookies=({SESSION_COOKIE_NAME: cookie} if cookie else {}))


class TestASiblingAppCannotSignTheOperatorOut:
    """P2 review finding: `SameSite=Lax` does not scope to an ORIGIN.

    It scopes to a SITE, which ignores port and covers subdomains of the same
    registrable domain. This project's own deployment is the example: Jackett
    runs on :9117 and CouchPotato on :5050 of the same host, so a compromised
    or malicious sibling is same-site and the browser DOES attach the session
    cookie to its cross-origin POST.

    `require_auth` therefore succeeds and the secret rotates, signing the
    operator out of every device. Not credential theft -- but repeatable, and
    it stops them getting back in for as long as the sibling keeps firing.

    The defence is an Origin check, not a token: AC-SIMP-11 forbids CSRF token
    machinery, and header validation is not that.

    Deliberately refuses only when Origin or Referer is PRESENT and does not
    match. A client that sends neither is allowed through, because refusing
    would risk locking out an operator behind a proxy that strips them -- and
    a browser always sends `Origin` on a cross-origin POST, which is the case
    this exists to stop.
    """

    def test_a_cross_origin_post_does_not_rotate(self, env):
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(env)

        response = client.post('/logout/', headers={'origin': 'http://localhost:9117'})

        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == before, (
            'a POST from a same-site sibling app rotated the signing secret, '
            'so any app sharing this host can sign the operator out at will'
        )
        assert response.status_code in (400, 403), response.status_code

    def test_a_same_origin_post_still_signs_out(self, env):
        """The counterweight, and the one that matters: sign-out must work."""
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(env)

        response = client.post('/logout/', headers={'origin': 'http://testserver'})

        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) != before, (
            'the operator can no longer sign out from the app itself'
        )
        assert response.status_code in (302, 303), response.status_code

    def test_a_post_with_no_origin_header_still_signs_out(self, env):
        """No header, no verdict. Refusing here would lock out an operator
        behind a proxy that strips it, and a browser always sends Origin on
        the cross-origin POST this guards against."""
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(env)

        client.post('/logout/')

        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) != before



class TestTheOriginCheckDoesNotBreakSignOutBehindAProxy:
    """The false-POSITIVE direction of the cross-origin refusal.

    nginx's default `proxy_pass` sets `Host` to the UPSTREAM address unless
    the config overrides it, so on an install at `https://media.example.com`
    proxied to `127.0.0.1:5050` the app sees:

        Origin: https://media.example.com   ->  media.example.com
        Host:   127.0.0.1:5050

    Comparing those verbatim refuses every legitimate sign-out, forever. And
    because D1 makes secret rotation the ONLY revocation this design has --
    there is no session table -- that operator has no working sign-out at all.

    The asymmetry decides it. A false refusal costs the operator their only
    revocation mechanism, permanently and silently. A false accept costs a
    repeatable annoyance from an app that already shares their host. The
    spec's own rule is that nothing here may produce a lockout.

    So `X-Forwarded-Host` counts as this app's identity too. A malicious
    sibling cannot forge it: the attack shape is a plain cross-site form POST,
    which cannot set custom headers, and a `fetch` that did would trigger a
    CORS preflight it cannot satisfy.
    """

    def test_a_proxied_sign_out_is_not_refused(self, env):
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(env)

        response = client.post('/logout/', headers={
            'origin': 'https://media.example.com',
            'x-forwarded-host': 'media.example.com',
        })

        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) != before, (
            'a legitimate sign-out from behind a reverse proxy was refused, so '
            'this operator has no working revocation at all'
        )
        assert response.status_code in (302, 303), response.status_code

    def test_a_sibling_app_is_still_refused_behind_a_proxy(self, env):
        """The counterweight: forwarding headers must not become a bypass."""
        before = env.settings.getProperty(SESSION_SECRET_PROPERTY)
        client, _ = log_in(env)

        response = client.post('/logout/', headers={
            'origin': 'http://localhost:9117',
            'x-forwarded-host': 'media.example.com',
        })

        assert env.settings.getProperty(SESSION_SECRET_PROPERTY) == before, (
            'a sibling app on another port signed the operator out despite the '
            'forwarded host naming a different origin'
        )
        assert response.status_code == 403

    def test_a_refusal_is_logged_with_both_values(self, env, caplog):
        """A 403 nobody can diagnose is how this becomes a silent lockout."""
        import logging

        client, _ = log_in(env)

        with caplog.at_level(logging.WARNING):
            client.post('/logout/', headers={'origin': 'http://localhost:9117'})

        text = ' '.join(r.getMessage() for r in caplog.records).lower()
        assert 'localhost:9117' in text, (
            'the refusal logged nothing naming the mismatch, so an operator '
            'whose proxy breaks this has nothing to go on: %s' % text[-400:])
