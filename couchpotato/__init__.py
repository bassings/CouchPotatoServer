"""CouchPotato web application module - FastAPI backed.

Provides web views, authentication, and the main application setup.
"""
import os
import time
import traceback

from couchpotato.api import api_docs, api_docs_missing, api, callApiHandler
from couchpotato.core.event import fireEvent
from couchpotato.core.helpers.encoding import sp
from couchpotato.core.helpers.variable import md5, tryInt
from couchpotato.core.logger import CPLog
from couchpotato.environment import Env

from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment as JinjaEnv, FileSystemLoader

log = CPLog(__name__)

views = {}

# Jinja2 template environment
_template_dir = os.path.join(os.path.dirname(__file__), 'templates')
_jinja_env = JinjaEnv(loader=FileSystemLoader(_template_dir))


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

def create_app(api_key: str, web_base: str) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(docs_url=None, redoc_url=None)

    api_base = '%sapi/%s' % (web_base, api_key)

    @app.get(api_base + '/{route:path}')
    @app.post(api_base + '/{route:path}')
    async def api_handler(route: str, request: Request):
        route = route.strip('/')
        if not route:
            return RedirectResponse(url=web_base + 'docs/')

        # Check nonblock routes
        if route in api.get('nonblock', {}):
            pass  # TODO: SSE support

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
            if (u_param == md5(username) or not username) and (p_param == password or not password):
                api_key_val = Env.setting('api_key')

            return {'success': api_key_val is not None, 'api_key': api_key_val}
        except:
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

        api_key_val = None
        if (form.get('username') == username or not username) and (md5(form.get('password', '')) == password or not password):
            api_key_val = Env.setting('api_key')

        response = RedirectResponse(url=web_base, status_code=302)
        if api_key_val:
            remember_me = tryInt(form.get('remember_me', 0))
            max_age = 30 * 24 * 3600 if remember_me > 0 else None
            response.set_cookie('user', api_key_val, max_age=max_age, httponly=True)

        return response

    @app.get(web_base + 'logout/')
    @app.get(web_base + 'logout')
    async def logout(request: Request):
        response = RedirectResponse(url='%slogin/' % web_base, status_code=302)
        response.delete_cookie('user')
        return response

    # Catch-all web handler
    @app.get(web_base + '{route:path}')
    async def web_handler(route: str, request: Request, user=Depends(require_auth)):
        route = route.strip('/')
        if route in views:
            try:
                content = views[route](request)
                if route == 'robots.txt':
                    return Response(content=content, media_type='text/plain')
                elif route == 'couchpotato.appcache':
                    return Response(content=content, media_type='text/cache-manifest')
                return HTMLResponse(content=content)
            except:
                log.error("Failed doing web request '%s': %s", route, traceback.format_exc())
                return JSONResponse({'success': False, 'error': 'Failed returning results'})

        # Page not found - redirect to SPA
        index_url = web_base
        url = request.url.path[len(index_url):]
        if url[:3] != 'api':
            return RedirectResponse(url=index_url + '#' + url.lstrip('/'))
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
