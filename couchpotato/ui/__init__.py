"""New UI module — htmx + Tailwind + Alpine.js served under /new/."""

import json
import os

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from jinja2 import Environment as JinjaEnv, FileSystemLoader

from couchpotato.environment import Env
from couchpotato.core.logger import CPLog

log = CPLog(__name__)

_template_dir = os.path.join(os.path.dirname(__file__), 'templates')
_jinja = JinjaEnv(loader=FileSystemLoader(_template_dir), autoescape=True)


class _BytesEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, bytes):
            return o.decode('utf-8', errors='replace')
        return super().default(o)


def _tojson(value):
    return json.dumps(value, cls=_BytesEncoder)

_jinja.filters['tojson'] = _tojson


def _ctx(extra=None):
    """Common template context."""
    api_key = Env.setting('api_key')
    web_base = Env.get('web_base') or '/'
    ctx = {
        'api_key': api_key,
        'api_base': '%sapi/%s' % (web_base, api_key),
        'web_base': web_base,
        'new_base': '%snew/' % web_base,
    }
    if extra:
        ctx.update(extra)
    return ctx


def create_router(require_auth) -> APIRouter:
    """Create the /new/ router. require_auth is the FastAPI dependency."""
    router = APIRouter()

    @router.get('/')
    @router.get('/wanted/')
    @router.get('/wanted')
    async def wanted(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('wanted.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'wanted'})))

    @router.get('/available/')
    @router.get('/available')
    async def available(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('wanted.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'available'})))

    @router.get('/movie/{movie_id}/')
    @router.get('/movie/{movie_id}')
    async def movie_detail(movie_id: str, request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('detail.html')
        return HTMLResponse(tmpl.render(**_ctx({'movie_id': movie_id})))

    @router.get('/add/')
    @router.get('/add')
    async def add_movie(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('add.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'add'})))

    # --- htmx partials ---

    @router.get('/partial/movies')
    async def partial_movies(request: Request, status: str = 'active', user=Depends(require_auth)):
        """Return movie card grid as HTML partial for htmx."""
        from couchpotato.api import callApiHandler
        try:
            result = callApiHandler('media.list', type='movie', status=status)
            if isinstance(result, dict):
                movies = result.get('movies', [])
            else:
                movies = []
        except Exception:
            log.error('Failed to fetch movies for new UI')
            movies = []
        tmpl = _jinja.get_template('partials/movie_cards.html')
        return HTMLResponse(tmpl.render(movies=movies, **_ctx()))

    @router.get('/partial/movie/{movie_id}')
    async def partial_movie_detail(movie_id: str, request: Request, user=Depends(require_auth)):
        """Return movie detail as HTML partial."""
        from couchpotato.api import callApiHandler
        try:
            result = callApiHandler('movie.get', id=movie_id)
            if isinstance(result, dict):
                movie = result.get('movie', result)
            else:
                movie = {}
        except Exception:
            log.error('Failed to fetch movie detail')
            movie = {}
        tmpl = _jinja.get_template('partials/movie_detail.html')
        return HTMLResponse(tmpl.render(movie=movie, **_ctx()))

    @router.get('/partial/search')
    async def partial_search(request: Request, q: str = '', user=Depends(require_auth)):
        """Search TMDB and return results as HTML partial."""
        from couchpotato.api import callApiHandler
        movies = []
        if q:
            try:
                result = callApiHandler('movie.search', q=q)
                if isinstance(result, dict):
                    movies = result.get('movies', [])
                elif isinstance(result, list):
                    movies = result
            except Exception:
                log.error('Failed to search movies')
        tmpl = _jinja.get_template('partials/search_results.html')
        return HTMLResponse(tmpl.render(movies=movies, **_ctx()))

    @router.get('/partial/profiles')
    async def partial_profiles(request: Request, user=Depends(require_auth)):
        """Return quality profiles as options."""
        from couchpotato.api import callApiHandler
        try:
            result = callApiHandler('profile.list')
            if isinstance(result, dict):
                profiles = result.get('list', result.get('profiles', []))
            else:
                profiles = []
        except Exception:
            profiles = []
        tmpl = _jinja.get_template('partials/profile_options.html')
        return HTMLResponse(tmpl.render(profiles=profiles))

    return router
