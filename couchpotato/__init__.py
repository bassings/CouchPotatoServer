"""CouchPotato web application module - FastAPI backed.

Provides web views, authentication, and the main application setup.
"""
import asyncio
import json
import os
import time
import traceback

from couchpotato.api import api_docs, api_docs_missing, api, api_nonblock, callApiHandler
from couchpotato.core.event import fireEvent
from couchpotato.core.helpers.encoding import sp, toUnicode
from couchpotato.core.helpers.variable import check_password, hash_password, is_legacy_md5_hash, md5, tryInt
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env

from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment as JinjaEnv, FileSystemLoader

log = CPLog(__name__)

views = {}

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
    return json.dumps(value, cls=CPJSONEncoder)


_jinja_env = JinjaEnv(loader=FileSystemLoader(_template_dir))
_jinja_env.filters['tojson'] = _cp_tojson
_jinja_env.policies['json.dumps_kwargs'] = {'cls': CPJSONEncoder}


def addView(route, func):
    views[route] = func


def get_db():
    return Env.get('db')


# --- Authentication ---

def get_current_user(request: Request):
    """FastAPI dependency for cookie-based auth."""
    username = Env.setting('username')
    password = Env.setting('password')

    if username and password:
        user = request.cookies.get('user')
        if not user:
            return None
        return user
    else:
        return True


def require_auth(request: Request):
    """FastAPI dependency that requires authentication."""
    user = get_current_user(request)
    if not user:
        web_base = Env.get('web_base')
        raise HTTPException(status_code=302, headers={'Location': '%slogin/' % web_base})
    return user


# --- Web Views ---

def index(*args):
    tmpl = _jinja_env.get_template('index.html')
    return tmpl.render(sep=os.sep, fireEvent=fireEvent, Env=Env)

addView('', index)


def robots(*args):
    return 'User-agent: * \nDisallow: /'

addView('robots.txt', robots)


def manifest(*args):
    web_base = Env.get('web_base')
    static_base = Env.get('static_path')

    lines = [
        'CACHE MANIFEST',
        '# %s theme' % ('dark' if Env.setting('dark_theme') else 'light'),
        '',
        'CACHE:',
        ''
    ]

    if not Env.get('dev'):
        for url in fireEvent('clientscript.get_styles', single=True):
            lines.append(web_base + url)
        for url in fireEvent('clientscript.get_scripts', single=True):
            lines.append(web_base + url)
        lines.append(static_base + 'images/favicon.ico')

        font_folder = sp(os.path.join(Env.get('app_dir'), 'couchpotato', 'static', 'fonts'))
        for subfolder, dirs, files in os.walk(font_folder, topdown=False):
            for file in files:
                if '.woff' in file:
                    lines.append(static_base + 'fonts/' + file + ('?%s' % os.path.getmtime(os.path.join(font_folder, file))))
    else:
        lines.append('# Not caching anything in dev mode')

    lines.extend(['', 'NETWORK: ', '*'])
    return '\n'.join(lines)

addView('couchpotato.appcache', manifest)


def apiDocs(*args):
    routes = list(api.keys())

    if api_docs.get(''):
        del api_docs['']
        del api_docs_missing['']

    tmpl = _jinja_env.get_template('api.html')
    return tmpl.render(fireEvent=fireEvent, routes=sorted(routes), api_docs=api_docs, api_docs_missing=sorted(api_docs_missing), Env=Env)

addView('docs', apiDocs)


def databaseManage(*args):
    tmpl = _jinja_env.get_template('database.html')
    return tmpl.render(fireEvent=fireEvent, Env=Env)

addView('database', databaseManage)


# --- FastAPI Route Handlers ---

def create_app(api_key: str, web_base: str, static_dir: str = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(docs_url=None, redoc_url=None)

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

            if os.path.isfile(real_path):
                return FileResponse(real_path)
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
        result = callApiHandler(route, **kwargs)

        if isinstance(result, tuple) and result[0] == 'redirect':
            return RedirectResponse(url=result[1])

        jsonp_callback = kwargs.get('callback_func')
        if jsonp_callback:
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
            if (u_param == md5(username) or not username) and (check_password(p_param, password) or not password):
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
        return HTMLResponse(tmpl.render(sep=os.sep, fireEvent=fireEvent, Env=Env))

    @app.post(web_base + 'login/')
    @app.post(web_base + 'login')
    async def login_post(request: Request):
        form = await request.form()
        username = Env.setting('username')
        password = Env.setting('password')
        form_password = form.get('password', '')
        form_password_md5 = md5(form_password)

        api_key_val = None
        if (form.get('username') == username or not username) and (check_password(form_password_md5, password) or not password):
            api_key_val = Env.setting('api_key')
            if password and is_legacy_md5_hash(password):
                Env.setting('password', value=hash_password(form_password_md5))

        response = RedirectResponse(url=web_base, status_code=302)
        if api_key_val:
            remember_me = tryInt(form.get('remember_me', 0))
            max_age = 30 * 24 * 3600 if remember_me > 0 else None
            # Set cookie with path=/ to share session across all routes (new UI, old UI, API)
            # This fixes DEF-004: Classic UI requires separate authentication
            response.set_cookie('user', api_key_val, max_age=max_age, httponly=True, path='/')

        return response

    @app.get(web_base + 'logout/')
    @app.get(web_base + 'logout')
    async def logout(request: Request):
        response = RedirectResponse(url='%slogin/' % web_base, status_code=302)
        # Delete cookie with path=/ to match the path set during login
        response.delete_cookie('user', path='/')
        return response

    # Classic UI catch-all (moved to /old/)
    @app.get(web_base + 'old/{route:path}')
    @app.get(web_base + 'old')
    async def web_handler(route: str = '', request: Request = None, user=Depends(require_auth)):
        route = route.strip('/')
        if route in views:
            try:
                content = views[route](request)
                if route == 'robots.txt':
                    return Response(content=content, media_type='text/plain')
                elif route == 'couchpotato.appcache':
                    return Response(content=content, media_type='text/cache-manifest')
                return HTMLResponse(content=content)
            except Exception:
                log.error("Failed doing web request '%s': %s", route, traceback.format_exc())
                return JSONResponse({'success': False, 'error': 'Failed returning results'})

        # Page not found - redirect to classic SPA
        old_base = web_base + 'old/'
        url = route
        if url.startswith('static/'):
            return Response(content='Not found', status_code=404)
        elif url[:3] != 'api':
            return RedirectResponse(url=old_base + '#' + url.lstrip('/'))
        else:
            if not Env.get('dev'):
                time.sleep(0.1)
            return Response(content='Wrong API key used', status_code=404)

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
