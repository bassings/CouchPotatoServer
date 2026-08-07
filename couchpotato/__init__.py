"""CouchPotato web application module - FastAPI backed.

Provides web views, authentication, and the main application setup.
"""
import asyncio
import hmac
import json
import os
import re
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


def get_current_user(request: Request):
    """FastAPI dependency for cookie-based auth."""
    if not auth_is_required():
        return True

    user = request.cookies.get('user')
    if not user:
        return None
    api_key = Env.setting('api_key')
    if api_key and hmac.compare_digest(str(user).encode('utf-8'), str(api_key).encode('utf-8')):
        return user
    return None


def require_auth(request: Request):
    """FastAPI dependency that requires authentication."""
    user = get_current_user(request)
    if not user:
        web_base = Env.get('web_base')
        raise HTTPException(status_code=302, headers={'Location': '%slogin/' % web_base})
    return user


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
        tmpl = _jinja_env.get_template('login.html')
        return HTMLResponse(tmpl.render(web_base=Env.get('web_base') or '/'))

    @app.post(web_base + 'login/')
    @app.post(web_base + 'login')
    async def login_post(request: Request):
        form = await request.form()
        username = Env.setting('username')
        password = Env.setting('password')
        form_password = form.get('password', '')
        form_password_md5 = md5(form_password)

        api_key_val = None
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
            api_key_val = Env.setting('api_key')
            if password and is_legacy_md5_hash(password):
                Env.setting('password', value=hash_password(form_password_md5))

        response = RedirectResponse(url=web_base, status_code=302)
        if api_key_val:
            remember_me = tryInt(form.get('remember_me', 0))
            max_age = 30 * 24 * 3600 if remember_me > 0 else None
            # Set cookie with path=/ to share session across all routes (new UI, old UI, API)
            # This fixes DEF-004: Classic UI requires separate authentication
            response.set_cookie('user', api_key_val, max_age=max_age, httponly=True, path='/')  # codeql[py/clear-text-storage-sensitive-data]

        return response

    @app.get(web_base + 'logout/')
    @app.get(web_base + 'logout')
    async def logout(request: Request):
        response = RedirectResponse(url='%slogin/' % web_base, status_code=302)
        # Delete cookie with path=/ to match the path set during login
        response.delete_cookie('user', path='/')
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
