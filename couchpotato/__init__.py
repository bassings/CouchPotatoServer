"""CouchPotato web application module - FastAPI backed.

Provides web views, authentication, and the main application setup.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import traceback

from couchpotato.api import api_nonblock, callApiHandler
from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.variable import check_password, hash_password, is_legacy_md5_hash, md5, tryInt
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env

from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment as JinjaEnv, FileSystemLoader, select_autoescape
from markupsafe import Markup
from starlette.concurrency import run_in_threadpool

log = CPLog(__name__)

# Jinja2 template environment
_template_dir = os.path.join(os.path.dirname(__file__), 'templates')
class CPJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles bytes from CodernityDB documents."""
    def default(self, o):
        if isinstance(o, bytes):
            return o.decode('utf-8', errors='replace')
        return super().default(o)


def _cp_tojson(value):
    """Custom tojson filter that handles bytes values."""
    return Markup(json.dumps(value, cls=CPJSONEncoder))


_jinja_env = JinjaEnv(
    loader=FileSystemLoader(_template_dir),
    autoescape=select_autoescape(['html', 'xml']),
)
_jinja_env.filters['tojson'] = _cp_tojson
_jinja_env.policies['json.dumps_kwargs'] = {'cls': CPJSONEncoder}


def get_db():
    return Env.get('db')


# --- Authentication ---

def auth_is_required() -> bool:
    """Is the web interface gated on a session?

    An EXPLICIT setting, not an inference from two unrelated fields. The old
    gate was `if username and password:`, which meant a blank username silently
    disabled authentication -- and the settings copy put "Leave empty to
    disable authentication" on the USERNAME field, so the field that turned
    auth off was the one whose description promised exactly that. Driven
    directly, three of the four credential combinations returned "fully
    public", including password-set-with-blank-username.

    Absent (an upgrade from any config.ini written before this change) derives
    from whether a password is set, so an install that had bothered to set one
    stays protected rather than falling open on upgrade. `runner.py` writes the
    resolved value back once at startup, after which it is an explicit 0 or 1
    the operator can find with `grep` -- which matters, because grepping
    config.ini is the documented lock-out recovery path.

    Deliberately NOT a tri-state `None` default. `registerDefaults`
    materialises the literal `auth_required = None` into config.ini on first
    boot and `Env.setting`'s own default is `''`, so the natural
    `Env.setting('auth_required', type='bool')` reads falsy and auth stays off
    on every install, silently, with no failing test and no log line.
    """
    configured = Env.setting('auth_required', default=None)

    if configured is None or configured == '':
        return _auth_required_from_password()

    # ORDER MATTERS: resolve what the setting MEANS before consulting the
    # password.
    #
    # The first version of the lockout guard below checked the password first,
    # so it fired for any value that was not None/'' -- including an explicit
    # 0. That is the state every default install reaches: `runner.py`'s startup
    # migration deliberately writes back `auth_required = 0` for an install
    # with no password, so the value is greppable in config.ini. From the next
    # request onward it logged '"Require login" is on but no password is
    # stored' on EVERY page load, for the most common configuration this
    # project ships. Nothing broke -- the return value was already correct --
    # but the log asserted the opposite of the truth, on exactly the mechanism
    # `runner.py`'s own comment says operators rely on. Same defect class this
    # branch fixes three times elsewhere.
    wants_auth = _parse_auth_required(configured)

    if wants_auth is None:
        # config.ini is the documented lock-out recovery path, so it gets
        # hand-edited and typos here are expected. Reading an unrecognised
        # value as "off" would silently make the server public; reading it as
        # "on" would lock out an install with no password. Fall back to the
        # same derivation used when the key is absent, which does neither.
        log.error('Unrecognised auth_required value %r in config.ini; expected '
                  '0 or 1. Falling back to "required only if a password is '
                  'set". Fix the value to remove this warning.', configured)
        return _auth_required_from_password()

    if not wants_auth:
        return False

    # FAIL CLOSED. An earlier version of this function served the app WITHOUT
    # authentication here, reasoning that a requirement nothing can satisfy
    # should not be enforced. That was wrong, and measurably so.
    #
    # Driven against a real `create_app` with `auth_required=1` and no
    # password, the fail-open version gave an unauthenticated caller:
    #
    #     GET /wanted/                          -> 200
    #     the api_key, embedded in that page    -> present
    #     movie.delete?delete_from=all          -> reachable
    #
    # So the trade was "a lockout the operator can fix" against "a remote
    # stranger can read the api_key and delete the library". On a port-forwarded
    # install that is not a close call, and it inverts this project's own
    # precedence: irrecoverable data loss and security both outrank operability.
    #
    # The lockout is recoverable BY CONSTRUCTION. `Core.guardAuthRequired`
    # blocks the settings UI and the wizard from creating this state, so the
    # only remaining routes are a hand-edited config.ini or a restored backup --
    # both of which require filesystem access, which is exactly what the remedy
    # needs. The cost is a config edit; the cost of the alternative is the
    # library.
    #
    # ERROR, not WARNING, and it names the remedy: this is the log line the
    # locked-out operator will be reading.
    if not Env.setting('password'):
        log.error('"Require login" is ON but NO PASSWORD is stored, so no login '
                  'can succeed and every request will be refused. Serving is '
                  'CONTINUING with authentication enforced rather than falling '
                  'open -- an unauthenticated instance would expose the api_key '
                  'and allow the library to be deleted remotely. To recover: '
                  'set "auth_required = 0" in the [core] section of config.ini '
                  'and restart, then set a password from Settings.')

    return True


def _parse_auth_required(configured):
    """True, False, or None when the value is not recognisable.

    A STRING is the normal case on the startup path, not an edge case:
    `runner.py` calls `auth_is_required()` before `loader.run()` has registered
    the option's type, so `Settings.getType` falls back to 'unicode', which
    `_coerce_value` does not coerce -- the raw ConfigParser string arrives
    here. `bool('0')` is True, so this parsing is the only thing keeping an
    explicit `auth_required = 0` from turning auth ON.

    `None` for "cannot tell" rather than collapsing into False: the caller
    errs toward the password-derived answer, and a typo must not be silently
    read as "off".
    """
    if isinstance(configured, bool):
        return configured

    if isinstance(configured, str):
        value = configured.strip().lower()
        if value in ('1', 'true', 'yes', 'on'):
            return True
        if value in ('0', 'false', 'no', 'off'):
            return False
        return None

    return bool(configured)


def _auth_required_from_password() -> bool:
    """Derive the gate from whether a password exists.

    Used when `auth_required` is absent or unreadable. Keeps a
    password-protected install protected without ever producing the
    auth-on-with-no-password state that nothing can satisfy.
    """
    return bool(Env.setting('password'))


# --- Session cookie ---
#
# The browser used to be handed `Env.setting('api_key')` verbatim as its `user`
# cookie, so the session cookie WAS the credential `/api/{route:path}`
# authenticates with: reading it bought add, rename and
# `movie.delete?delete_from=all`. Logout could only ask the browser to forget a
# value the thief already had, and the only revocation was rotating the api_key,
# which breaks the userscript and every downloader at once -- so it never
# happened and a leaked cookie was valid forever.
#
# The cookie is now `<absolute expiry>.<HMAC-SHA256 of that expiry>` under a
# secret held in the existing property store. No new table and no DDL
# (`SQLiteAdapter.open()` runs none, so a `schema.sql` addition would reach
# fresh installs only and raise `no such table` on the first login of every
# existing one), and no `db.get('session', ...)` -- `_query_index`'s generic
# `else` branch discards the key and returns an arbitrary document, which this
# repo has shipped as a live defect twice.
#
# Everything below takes its clock and its secret as arguments so expiry is
# provable without `sleep` and without patching module-level `time.time` (which
# also freezes `date.today()` -- a recorded false positive on this repo).

SESSION_COOKIE_NAME = 'user'
SESSION_SECRET_PROPERTY = 'session_secret'

# Lifetimes, not settings: a wrong value here makes the cookie undeliverable or
# the session eternal, and neither belongs one typo away in config.ini. 24 hours
# clears WCAG 2.2.1's 20-hour exception, so no warn-and-extend is owed.
SESSION_LIFETIME = 24 * 3600
SESSION_LIFETIME_REMEMBERED = 30 * 24 * 3600

# Serialises the read-then-create in `ensure_session_secret`. The property store
# has no uniqueness constraint on `identifier`, so two threads that both find
# nothing both insert -- measured on `Settings.setProperty`: four concurrent
# creates produced two rows and lost two writes. The adapter is single-process
# over a single connection (see `SQLiteAdapter.update`), so a process-local lock
# is the whole story.
_SESSION_SECRET_WRITE_LOCK = threading.Lock()

_SESSION_SECRET_MISSING = (
    'The session signing secret could not be read, so NO login can succeed and '
    'every browser session is refused. The api_key and the /api/ routes are '
    'unaffected. To recover: set "auth_required = 0" in the [core] section of '
    'config.ini and restart, then check the database is readable.'
)


def generate_session_secret() -> str:
    """A fresh signing secret: 32 bytes of entropy, as hex text.

    Hex, not raw bytes, and that is correctness rather than tidiness.
    `Settings.setProperty` stores `toUnicode(value)`, which decodes with
    REPLACEMENT, so `os.urandom(32)` comes back mangled and how much survives
    depends on which random bytes happened to form valid UTF-8 (measured twice:
    29 characters once, 31 the next). A secret stored raw would differ silently
    on every install and be unrecoverable after the fact.

    Never derived from `api_key` (embedded in every rendered page), `uuid4`,
    `md5`, the clock or the password hash: a secret anyone can recompute makes
    session forgery permanent and survives every api_key rotation.
    """
    return secrets.token_hex(32)


def _sign_session_payload(payload: str, secret) -> str:
    """The ONLY HMAC computation for session cookies in the tree."""
    signature = hmac.new(
        str(secret).encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')


def mint_session_token(secret, lifetime: int, now=None) -> str:
    """A signed cookie value valid for `lifetime` seconds from `now`."""
    if not secret:
        # Never sign with '' or None. A constant fallback key would make every
        # install forgeable by anyone who can read this file.
        raise ValueError('refusing to sign a session token without a secret')

    current = time.time() if now is None else now
    payload = str(int(current) + int(lifetime))
    return '%s.%s' % (payload, _sign_session_payload(payload, secret))


def verify_session_token(token, secret, now=None) -> bool:
    """Is `token` a signature we issued, and is it still inside its lifetime?

    Signature first, expiry second: the expiry is only trustworthy once the
    payload is known to be ours.
    """
    if not secret or not token or not isinstance(token, str):
        return False

    payload, separator, signature = token.partition('.')
    if not separator or not signature:
        return False

    try:
        presented = signature.encode('ascii')
    except UnicodeEncodeError:
        # `hmac.compare_digest` refuses non-ASCII str; a cookie is whatever the
        # client sent, so this is a refusal rather than a 500.
        return False

    expected = _sign_session_payload(payload, secret).encode('ascii')
    if not hmac.compare_digest(presented, expected):
        # Constant-time: a plain `==` short-circuits on the first differing
        # byte and leaks the correct signature to anyone who can time us.
        return False

    try:
        expires_at = int(payload)
    except (TypeError, ValueError):
        return False

    current = time.time() if now is None else now
    return current < expires_at


def _session_secret_row(db):
    """The stored secret's property document, or None.

    Filtered on `identifier` again after the query. `_query_index` honours the
    key for the `property` index today, but its generic `else` branch discards
    the key and returns an arbitrary document, and this repo has shipped that
    exact defect twice (`release_download`, `media`). Accepting whatever came
    back would mean signing with another property's value.
    """
    for row in db.query('property', SESSION_SECRET_PROPERTY):
        if row.get('identifier') == SESSION_SECRET_PROPERTY:
            return row
    return None


def _write_session_secret(secret: str, db=None, attempts: int = 3) -> str:
    """The ONLY function in the tree that writes the session secret.

    `Settings.setProperty` cannot be used: it wraps get-then-update in a bare
    `except Exception:` that falls through to `insert`, so a lost
    compare-and-swap becomes a DUPLICATE property row and a silently discarded
    write (measured: after the conflict, `get()` returned the older value).
    Retrying against a re-read row is the fix, and it lives here because
    `couchpotato/core/settings.py` stays out of this diff.
    """
    from couchpotato.core.db.sqlite_adapter import ConflictError

    db = get_db() if db is None else db

    for _ in range(attempts):
        existing = _session_secret_row(db)

        if existing is None:
            db.insert({
                '_t': 'property',
                'identifier': SESSION_SECRET_PROPERTY,
                'value': secret,
            })
            return secret

        existing['identifier'] = SESSION_SECRET_PROPERTY
        existing['value'] = secret
        try:
            db.update(existing)
            return secret
        except ConflictError:
            # Lost the compare-and-swap. Re-read and retry. NEVER fall through
            # to insert: that is `setProperty`'s defect, and a second row makes
            # the lookup arbitrary for the life of the install.
            continue

    raise RuntimeError(
        'could not store the session signing secret after %d attempts' % attempts
    )


def ensure_session_secret(db=None) -> str:
    """Read the signing secret, creating it once if this install has none.

    Called from `runner.py` at startup, BEFORE the first request is served, so
    the request path only ever reads (D2). Verification never reaches here.
    """
    db = get_db() if db is None else db

    with _SESSION_SECRET_WRITE_LOCK:
        existing = _session_secret_row(db)
        if existing is not None and existing.get('value'):
            return existing['value']

        secret = generate_session_secret()
        _write_session_secret(secret, db=db)
        log.info('Created a session signing secret. Browser logins are now '
                 'signed sessions rather than the api_key, so any existing '
                 'login is invalidated and must sign in again. The api_key '
                 'itself is unchanged and every script keeps working.')
        return secret


def rotate_session_secret(db=None) -> str:
    """Replace the signing secret, which ends every session on every device.

    D1. A stateless signed cookie holds no per-session server state, so under
    the settled "no new table" constraint this is the ONLY revocation there is:
    logout previously called `response.delete_cookie(...)`, which asks the
    browser to forget a value the thief already had. The browser is the one
    party that was never the threat.

    Whole-secret rotation is deliberately not per-device. That is correct for
    one operator, and the sign-out control's copy has to say so rather than
    implying "this browser only".

    Under the same lock as `ensure_session_secret`, and for the same measured
    reason: the property store has no uniqueness constraint on `identifier`, so
    two writers that both find nothing both insert, and a second row makes the
    lookup return whichever SQLite hands back first for the life of the
    install.

    Does NOT touch the `api_key`. Rotating that was the old revocation, and it
    breaks the userscript, every script and every downloader at once -- which
    is why in practice it never happened and a leaked cookie was valid forever.
    """
    db = get_db() if db is None else db

    with _SESSION_SECRET_WRITE_LOCK:
        secret = generate_session_secret()
        _write_session_secret(secret, db=db)
        log.info('Rotated the session signing secret: every browser session, '
                 'on every device, has been signed out and must log in again. '
                 'The api_key is unchanged, so scripts, the userscript and '
                 'every downloader keep working.')
        return secret


def get_session_secret():
    """The signing secret, or None. Reads only -- it never creates one.

    A verification path that could create a secret would let an unauthenticated
    caller write to the database, and would quietly mint a NEW secret whenever
    the store hiccupped, invalidating every live session at random.
    """
    try:
        secret = Env.prop(SESSION_SECRET_PROPERTY)
    except Exception:
        secret = None

    if not secret:
        log.error(_SESSION_SECRET_MISSING)
        return None

    return secret


def _server_terminates_tls() -> bool:
    """Does THIS process speak TLS, as opposed to something in front of it?

    The same pair `runner.py` hands to uvicorn, and for the same reason: both
    or neither. Half a TLS configuration still serves plain HTTP.
    """
    return bool(Env.setting('ssl_cert') and Env.setting('ssl_key'))


def session_cookie_attributes() -> dict:
    """The ONE source of the session cookie's attributes, set and delete alike.

    A `Set-Cookie` deletion only matches if its `Path` and `Domain` match the
    cookie that was set. Two hand-written attribute lists agree right up until
    somebody edits one of them, and the failure is silent: the browser keeps
    the original cookie while the server believes it cleared it, which is
    precisely what "logging out" used to amount to here.

    `secure` comes from the SERVER'S OWN configuration (D4) and from nothing
    else -- not `X-Forwarded-Proto`, not `X-Forwarded-Ssl`, not `Host`, not the
    request URL's scheme. Those are attacker-settable on a plain-HTTP LAN box,
    and the failure direction is not a weaker cookie, it is an UNDELIVERABLE
    one: the browser drops a Secure cookie on http, the redirect to `/` bounces
    straight back to `/login/`, and the operator is locked out of their own
    server by a header a stranger sent. This project's production instance is
    plain HTTP, and the parent plan already records one near-miss of that
    shape.

    Read per request rather than frozen at `create_app` time, which leaves one
    narrow window: an operator who saves `ssl_cert` and `ssl_key` from the
    settings UI and does NOT restart is still being served plain HTTP, and the
    next login would set a cookie the browser drops. That is bounded and
    self-healing -- the Server settings group already says "Needs restart
    before changes take effect", and the restart both makes TLS real and makes
    the cookie deliverable. Freezing the value at boot would trade it for a
    worse failure: any call path that builds the app before settings are loaded
    would pin the wrong answer for the life of the process.

    `samesite='Lax'` written out, because the browser default is not specified
    and differs between them. Lax rather than Strict: Strict withholds the
    cookie on a top-level navigation from another origin, so a bookmark or a
    link from anywhere else would land the operator on the login page. Lax
    still keeps a cross-site POST -- the logout CSRF of AC-SEC-37 -- from
    carrying it.

    `path` is `web_base` rather than a hardcoded `/`: an install served at
    `/couchpotato/` behind a shared host would otherwise send its session
    cookie to every other application on that host. It still covers the new UI,
    the legacy `/old/` redirect and the API routes, which all live under
    `web_base` (DEF-004).
    """
    return {
        'path': Env.get('web_base') or '/',
        'httponly': True,
        'samesite': 'Lax',
        'secure': _server_terminates_tls(),
    }


def get_current_user(request: Request):
    """FastAPI dependency for cookie-based auth."""
    if not auth_is_required():
        return True

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    # No legacy branch. The cookie used to be compared against
    # `Env.setting('api_key')` and that comparison is GONE rather than kept as
    # a fallback: a fallback would mean the api_key still authenticates the
    # browser, which is the whole defect. An api_key-valued cookie carries no
    # signature, so it is refused here like any other forgery.
    secret = get_session_secret()
    if not secret:
        return None

    if verify_session_token(token, secret):
        return True

    return None


def require_auth(request: Request):
    """FastAPI dependency that requires authentication."""
    user = get_current_user(request)
    if not user:
        web_base = Env.get('web_base')
        location = '%slogin/' % web_base
        # ONLY when the caller actually presented a session. A first-time
        # visitor who has never logged in must not be told their session ended
        # (AC-A11Y-5's negative half); somebody whose working login just
        # stopped working -- expired, revoked, or invalidated by the upgrade
        # D5 describes -- is exactly who the message is for.
        if request.cookies.get(SESSION_COOKIE_NAME):
            location += '?reason=session_ended'
        raise HTTPException(status_code=302, headers={'Location': location})
    return user


# --- Login page copy ---
#
# One place, so the wording can be reviewed as writing rather than hunted for
# across three routes. The tone selects the panel tint and the ARIA role; the
# text is rendered verbatim and is the only thing the person reads.
#
# Nothing here names the mechanism -- no token, signature, cookie or status
# code. A status code tells the operator nothing they can act on, and the rest
# describes an implementation they did not ask about. Pinned by a test, because
# copy drifts.
LOGIN_MESSAGES = {
    'signed_out': (
        'notice',
        'You have been signed out on every device, not just this browser. '
        'Sign in again to continue.',
    ),
    'session_ended': (
        'notice',
        'Your session has ended, so you need to sign in again. If CouchPotato '
        'was just updated, the update ended every existing session; your '
        'existing password still works.',
    ),
    'rejected': (
        'error',
        'That username or password was not accepted. Check them and try again.',
    ),
    'empty_password': (
        'error',
        'Enter your password to sign in.',
    ),
    'sign_out_failed': (
        'error',
        'Sign-out did not work, so every session is still signed in on every '
        'device. The server could not write the change to its database. Check '
        'the server log, then try again.',
    ),
}

#: The only two reasons a URL may ask for. Everything else is produced by the
#: server as the direct result of a POST it just handled, so accepting it from
#: the query string would let any link claim the operator's last attempt was
#: rejected. Unknown values render no message at all rather than an error.
LOGIN_REASONS_FROM_URL = ('signed_out', 'session_ended')

#: A rejected username is reflected back so the operator does not retype it.
#: Bounded because it is untrusted input that ends up in a page and in the
#: browser's history.
MAX_REFLECTED_USERNAME = 100


def render_login_page(reason=None, username='', status_code: int = 200,
                      mode: str = 'signin'):
    """The ONE renderer of `login.html`, for every state it has.

    `login_get`, a rejected `login_post` and a failed sign-out all land here,
    so the status region, the focus target and the escaping are decided once.
    Three separate call sites would drift, and the one that drifted would be
    the one nobody looks at -- the failure path.
    """
    tone = text = None
    if reason:
        tone, text = LOGIN_MESSAGES[reason]

    if mode == 'signout_failed':
        # The person is still signed in, so there is nothing to type. Focus
        # goes to the message: it is the only thing on the page that changed,
        # and it is what they need to have read before pressing anything.
        focus_field = 'message'
    elif tone == 'error':
        focus_field = 'password'
    else:
        focus_field = 'username'

    tmpl = _jinja_env.get_template('login.html')
    return HTMLResponse(
        tmpl.render(
            web_base=Env.get('web_base') or '/',
            heading='Sign-out failed' if mode == 'signout_failed' else 'Sign in',
            mode=mode,
            message_tone=tone,
            message_text=text,
            # `alert` interrupts, `status` waits for a pause. A failed attempt
            # is the former; a confirmation the operator asked for is not.
            message_role='alert' if tone == 'error' else 'status',
            username_value=username,
            focus_field=focus_field,
        ),
        status_code=status_code,
    )


# --- Web Views ---
#
# NOTE: the `views`/`addView` registry and most of the legacy MooTools-era
# view functions (apiDocs(), databaseManage(), manifest(), robots(), index())
# were retired in UI-CLEANUP-01/UI-CLEANUP-02 — none of them were read by any
# live route (the registry itself was never consulted by the router;
# `/robots.txt`, `/docs`, `/database` and `/couchpotato.appcache` have no
# FastAPI route handler). `index()` was the one exception, called directly by
# `Userscript.iFrame`; that embed was confirmed already broken/unused and was
# deleted in UI-CLEANUP-02, along with `index()`, `index.html`, the
# ClientScript plugin, and the compiled bundles it rendered — see
# `specs/UI-MIGRATION.md`.

# --- FastAPI Route Handlers ---

def create_app(api_key: str, web_base: str, static_dir: str = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    # openapi_url=None as well as docs_url/redoc_url.
    #
    # Turning off the two doc UIs left the SCHEMA they render still served, and
    # unauthenticated: measured on an instance with auth_required=1 and a
    # password set, `GET /openapi.json` returned 200 and 26,655 bytes
    # enumerating all 77 paths while `/wanted/` 302'd to the login page. No
    # credential is disclosed (the api_key is not in the body -- checked with a
    # realistic key, since a short one produces a false positive), so this is
    # reconnaissance rather than access: a complete machine-readable map of the
    # API from a server the operator believes is behind a login.
    #
    # Disabled rather than gated behind require_auth: nothing in this app reads
    # the schema, so there is no functionality to preserve, and a route that
    # does not exist cannot be left unprotected by the next change.
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    # Rate limiting middleware
    from couchpotato.core.rate_limit import RateLimitMiddleware
    rate_limit_max = tryInt(Env.setting('rate_limit_max', default=300))
    rate_limit_window = tryInt(Env.setting('rate_limit_window', default=60))
    if rate_limit_max > 0:
        app.add_middleware(RateLimitMiddleware, max_requests=rate_limit_max, window_seconds=rate_limit_window)

    # CORS middleware — same-origin by default, configurable via settings
    cors_origins = Env.setting('cors_origins', default='')
    allowed_origins = [o.strip() for o in cors_origins.split(',') if o.strip()] if cors_origins else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files BEFORE catch-all routes so they take priority
    if static_dir and os.path.isdir(static_dir):
        from fastapi.staticfiles import StaticFiles
        app.mount(web_base + 'static', StaticFiles(directory=static_dir), name='static')

    # Mount new UI at root (default) and keep legacy /new/ path for compatibility
    from couchpotato.ui import create_router as create_ui_router
    ui_router = create_ui_router(require_auth)
    app.include_router(ui_router, prefix=web_base.rstrip('/'))
    # Also keep /new/ working for bookmarks
    app.include_router(ui_router, prefix=web_base.rstrip('/') + '/new')

    # Robots.txt at root
    @app.get(web_base + 'robots.txt')
    async def robots_txt():
        return Response(content='User-agent: * \nDisallow: /', media_type='text/plain')

    api_base = '%sapi/%s' % (web_base, api_key)

    # Header-based API auth route (X-Api-Key header, preferred over URL-based)
    @app.get(web_base + 'api/{route:path}')
    @app.post(web_base + 'api/{route:path}')
    async def api_header_auth_handler(route: str, request: Request):
        """API handler that checks X-Api-Key header first, then falls back to URL key."""
        header_key = request.headers.get('x-api-key')

        # Check if the route starts with the API key (URL-based auth)
        if header_key:
            if header_key != api_key:
                return JSONResponse(content={'success': False, 'error': 'Invalid API key'}, status_code=401)
            # Strip leading key from route if present (header takes priority)
            if route.startswith(api_key + '/'):
                route = route[len(api_key) + 1:]
            elif route == api_key:
                route = ''
        elif route.startswith(api_key + '/'):
            route = route[len(api_key) + 1:]
        elif route == api_key:
            route = ''
        else:
            return JSONResponse(content={'success': False, 'error': 'API key required'}, status_code=401)

        return await _dispatch_api(route, request)

    async def _dispatch_api(route: str, request: Request):
        route = route.strip('/')
        if not route:
            return RedirectResponse(url=web_base + 'docs/')

        # Serve cached files (posters, etc.) directly
        if route.startswith('file.cache/'):
            from starlette.responses import FileResponse
            import glob
            filename = route.split('/')[-1]

            # Sanitise filename to prevent directory traversal attacks
            filename = os.path.basename(filename)
            if not filename or '..' in filename:
                return JSONResponse(content={'success': False, 'error': 'Invalid filename'}, status_code=400)

            cache_dir = toUnicode(Env.get('cache_dir'))
            file_path = os.path.join(cache_dir, filename)

            # Verify resolved path stays within the cache directory
            real_path = os.path.realpath(file_path)
            real_cache = os.path.realpath(cache_dir)
            if not real_path.startswith(real_cache + os.sep) and real_path != real_cache:
                return JSONResponse(content={'success': False, 'error': 'Invalid filename'}, status_code=400)

            if os.path.isfile(real_path):  # codeql[py/path-injection]
                return FileResponse(real_path)  # codeql[py/path-injection]
            # Try with common extensions (URLs often omit the extension)
            # Escape glob special characters in path to prevent pattern injection
            glob_pattern = glob.escape(real_path) + '.*'
            matches = [os.path.realpath(m) for m in glob.glob(glob_pattern)
                       if os.path.realpath(m).startswith(real_cache + os.sep)]
            if matches:
                return FileResponse(matches[0])
            return JSONResponse(content={'success': False, 'error': 'File not found'}, status_code=404)

        # Check nonblock routes (long-poll support)
        nonblock_key = route.replace('nonblock/', '', 1) if route.startswith('nonblock/') else route
        if nonblock_key in api_nonblock:
            add_listener, remove_listener = api_nonblock[nonblock_key]
            kwargs = dict(request.query_params)
            last_id = kwargs.get('last_id')

            loop = asyncio.get_event_loop()
            future = loop.create_future()

            def on_result(result):
                try:
                    loop.call_soon_threadsafe(future.set_result, result)
                except Exception:
                    pass

            add_listener(on_result, last_id=last_id)
            try:
                result = await asyncio.wait_for(future, timeout=30)
                return JSONResponse(content=result)
            except asyncio.TimeoutError:
                remove_listener(on_result)
                return JSONResponse(content={'success': True, 'result': []})
            except asyncio.CancelledError:
                remove_listener(on_result)
                raise

        kwargs = dict(request.query_params)
        if request.method == 'POST':
            content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
            if content_type in ('application/x-www-form-urlencoded', 'multipart/form-data'):
                kwargs.update(dict(await request.form()))
            elif content_type == 'application/json':
                raw_body = await request.body()
                if not raw_body.strip():
                    body = None
                else:
                    try:
                        body = json.loads(raw_body)
                    except ValueError:
                        return JSONResponse(content={'success': False, 'error': 'Invalid JSON body'}, status_code=400)
                if isinstance(body, dict):
                    kwargs.update(body)
        # Dispatched in the threadpool (REG-002): callApiHandler is
        # synchronous and can block for a long time (e.g. the chart
        # scrapers hitting IMDB/Blu-ray.com over the network). Running it
        # inline on the event loop would freeze every other concurrent
        # request for the same duration.
        result = await run_in_threadpool(callApiHandler, route, **kwargs)

        if isinstance(result, tuple) and result[0] == 'redirect':
            return RedirectResponse(url=result[1])

        jsonp_callback = kwargs.get('callback_func')
        if jsonp_callback:
            # Validate to alphanumeric/underscore/dot only to prevent JSONP injection
            if not re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$.]*$', str(jsonp_callback)):
                return JSONResponse(content={'success': False, 'error': 'Invalid callback'}, status_code=400)
            return Response(
                content=str(jsonp_callback) + '(' + (result if isinstance(result, str) else str(result)) + ')',
                media_type='text/javascript'
            )

        return result

    @app.get(web_base + 'getkey/')
    @app.get(web_base + 'getkey')
    async def get_key(request: Request):
        try:
            username = Env.setting('username')
            password = Env.setting('password')
            u_param = request.query_params.get('u', '')
            p_param = request.query_params.get('p', '')

            api_key_val = None
            # `password and ...`, the same fix as login_post and for the same
            # reason -- `or not password` short-circuited the credential check
            # to True whenever no password was configured.
            #
            # Worse here than at login: this returns the api_key itself, in a
            # JSON body, over GET, with the credentials in the query string --
            # so the request line lands in access logs, proxy logs and browser
            # history, and an unauthenticated caller received the key outright.
            # The `u` parameter is no protection: it is the md5 of the
            # username, which is not a secret.
            if password and (u_param == md5(username) or not username) \
                    and check_password(p_param, password):
                api_key_val = Env.setting('api_key')
                if password and is_legacy_md5_hash(password):
                    Env.setting('password', value=hash_password(p_param))

            return {'success': api_key_val is not None, 'api_key': api_key_val}
        except Exception:
            log.error('Failed doing key request: %s', traceback.format_exc())
            return {'success': False, 'error': 'Failed returning results'}

    @app.get(web_base + 'login/')
    @app.get(web_base + 'login')
    async def login_get(request: Request):
        user = get_current_user(request)
        if user:
            return RedirectResponse(url=web_base)
        # Allowlisted, never reflected. The parameter names a message the
        # server holds; it is not itself the message.
        reason = request.query_params.get('reason')
        if reason not in LOGIN_REASONS_FROM_URL:
            reason = None
        return render_login_page(reason=reason)

    @app.post(web_base + 'login/')
    @app.post(web_base + 'login')
    async def login_post(request: Request):
        form = await request.form()
        username = Env.setting('username')
        password = Env.setting('password')
        form_password = form.get('password', '')
        form_password_md5 = md5(form_password)

        authenticated = False
        # `password and ...`, NOT `... or not password`.
        #
        # The old spelling short-circuited the entire credential check to True
        # whenever no password was configured, so ANY submitted credentials
        # were accepted and a valid `user` cookie -- the api_key itself -- was
        # written to the browser. Not merely a UI bypass: that cookie is the
        # credential the whole API authenticates with.
        #
        # A blank password already means `get_current_user` returns True and
        # the instance is open, so refusing the login here costs nobody a
        # session they needed. What it closes is the state PR 2 introduces:
        # `auth_required` ON with no password set, one click away in the
        # settings UI. That instance LOOKS protected -- there is a login page,
        # it asks for credentials, it refuses nothing -- and admits everyone.
        # A door locked in appearance only is worse than an open one, because
        # it stops the operator looking for the lock.
        if password and (form.get('username') == username or not username) \
                and check_password(form_password_md5, password):
            authenticated = True
            if password and is_legacy_md5_hash(password):
                Env.setting('password', value=hash_password(form_password_md5))

        if not authenticated:
            # Back to the FORM, carrying the failure -- not a redirect to the
            # app root. The old spelling answered a wrong password with exactly
            # the response a correct one produced, so the failure was
            # discarded: the browser bounced to `/`, `require_auth` bounced it
            # back to `/login/`, and the person saw an empty form twice with no
            # explanation. Rendering here also costs zero redirects, so an
            # accidental `/` <-> `/login/` loop cannot hide in this path.
            submitted = form.get('username', '')
            if not isinstance(submitted, str):
                submitted = ''
            return render_login_page(
                reason='empty_password' if not form_password else 'rejected',
                username=submitted[:MAX_REFLECTED_USERNAME],
            )

        response = RedirectResponse(url=web_base, status_code=302)
        # The cookie is a signed token, NOT the api_key. `get_session_secret`
        # only reads -- if the secret is unreadable no cookie is issued at
        # all, because signing with '' or a constant would hand every reader
        # of this source a valid session on every install.
        secret = get_session_secret()
        if secret:
            remember_me = tryInt(form.get('remember_me', 0)) > 0
            lifetime = SESSION_LIFETIME_REMEMBERED if remember_me else SESSION_LIFETIME
            # `max_age` is UNCHANGED from before this PR: 30 days when
            # "remember me" is ticked, absent otherwise so the cookie dies
            # with the browser process. Absent is the more conservative of
            # the two and it is what operators already have; the reason it
            # was called out as a defect was that the value stayed valid
            # SERVER-side regardless, and that is what the signed expiry
            # above fixes. Max-Age was never enforcement anyway -- a replay
            # simply omits it.
            #
            # Every other attribute comes from `session_cookie_attributes`,
            # which the logout deletion uses too so the two cannot drift.
            response.set_cookie(
                SESSION_COOKIE_NAME,
                mint_session_token(secret, lifetime),
                max_age=lifetime if remember_me else None,
                **session_cookie_attributes(),
            )

        return response

    # POST, and authenticated. Both are required, and neither is ceremony.
    #
    # Logging out now ROTATES the shared signing secret (D1), which is the only
    # revocation a stateless signed cookie permits without the new table the
    # plan rules out -- and it ends every session on every device. Left as the
    # public unauthenticated GET it used to be, that would have made
    # `<img src="/logout/">` on any page the operator visited a remote,
    # repeatable, unauthenticated way to sign them out everywhere. The old
    # route was harmless as a GET only because it did nothing but clear one
    # browser's own cookie.
    #
    # `require_auth` is the CSRF defence rather than a token (AC-SIMP-11): a
    # caller who already holds a valid session gains nothing by making the
    # victim discard theirs. `SameSite=Lax` is the second layer, keeping a
    # cross-site POST from carrying the cookie at all.
    #
    # It stays reachable from an EXPIRED session in the only sense that
    # matters: `require_auth` redirects to `/login/`, which is public, so a
    # client whose session is broken lands on the form rather than on an error.
    # That is asserted in tests/unit/test_session_revocation.py, because it is
    # the assertion standing between this change and a lockout.
    @app.post(web_base + 'logout/')
    @app.post(web_base + 'logout')
    async def logout(request: Request, user=Depends(require_auth)):
        try:
            rotate_session_secret()
        except Exception:
            # Do NOT clear the cookie and redirect to the login page here.
            #
            # That is what a successful sign-out looks like, and nothing was
            # revoked: the token in somebody else's hands is still valid, and
            # the one person who could act on that has just been shown the
            # screen that says it is handled. Reporting the failure is worse UX
            # and the only honest option -- and it costs nobody access, because
            # the session that could not be revoked still works.
            log.error('Sign-out FAILED: the session signing secret could not '
                      'be rotated, so every existing session is STILL VALID on '
                      'every device. Nothing has been signed out. Check that '
                      'the database is writable and try again. %s',
                      traceback.format_exc())
            # A real page rather than the plain-text 500 this used to be
            # (spec gap 7). The BEHAVIOUR is unchanged and deliberately so --
            # still 500, still no `Set-Cookie` -- but this is the one screen
            # where the operator most needs to be told plainly that nothing
            # was revoked, and a bare stack-trace-coloured 500 does not do
            # that. It renders the same card, the same status region and the
            # same tokens as the login page: no new component, no new colour.
            return render_login_page(
                reason='sign_out_failed', status_code=500, mode='signout_failed')

        # 303, not 302: this is the response to a POST, and 303 is the status
        # that tells the browser to fetch the login page with GET.
        response = RedirectResponse(
            url='%slogin/?reason=signed_out' % web_base, status_code=303)
        # Asking the browser to drop its copy as well. Not the revocation --
        # the rotation above is -- but without it the client keeps sending a
        # dead cookie and every request logs a rejection.
        response.delete_cookie(SESSION_COOKIE_NAME, **session_cookie_attributes())
        return response

    # Legacy /old/* catch-all — redirect to the new UI root. The dead views
    # dict/addView registry and unreachable view functions were removed in
    # UI-CLEANUP-01, and the last live chain (`index()`/`index.html`/
    # ClientScript) was removed in UI-CLEANUP-02 (see specs/UI-MIGRATION.md).
    @app.get(web_base + 'old/{route:path}')
    @app.get(web_base + 'old/')
    @app.get(web_base + 'old')
    async def web_handler(route: str = ''):
        # 302 (temporary) during the in-progress UI migration to avoid
        # permanently-cached redirects; switch to 301 or remove in the final
        # legacy-cleanup PR.
        return RedirectResponse(url=web_base, status_code=302)

    return app


def page_not_found(request):
    """Legacy page_not_found - kept for compatibility."""
    index_url = Env.get('web_base')
    url = request.url.path[len(index_url):]

    if url[:3] != 'api':
        return RedirectResponse(url=index_url + '#' + url.lstrip('/'))
    else:
        if not Env.get('dev'):
            time.sleep(0.1)
        return Response(content='Wrong API key used', status_code=404)
