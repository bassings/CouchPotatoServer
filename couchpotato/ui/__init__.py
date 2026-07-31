"""New UI module — htmx + Tailwind + Alpine.js served under /new/."""

import html
import json
import os
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment as JinjaEnv, FileSystemLoader
from starlette.concurrency import run_in_threadpool

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


def _to_str(value):
    """Convert bytes to str, pass through strings."""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value) if value is not None else ''

_jinja.filters['to_str'] = _to_str


def _to_num(value):
    """Coerce a release's numeric field to a float, defaulting junk to 0.

    Providers do NOT normalise these: `torrentpotato.py:102` (the Jackett
    integration) passes the tracker's raw JSON `seeders` straight through, and
    `scenetime.py:61` stores a scraped **string**. `release/main.py` copies
    provider fields into `info` preserving type, and `media.get` hands them
    back uncoerced. Comparing or rounding those in a template raises
    TypeError, which Jinja does not catch and which happens outside the
    route's try/except -- so a single string `seeders` 500s the entire
    movie-detail body, not just one cell.
    """
    from couchpotato.core.helpers.variable import tryFloat
    return tryFloat(value)

_jinja.filters['to_num'] = _to_num


def _ctx(extra=None):
    """Common template context."""
    api_key = Env.setting('api_key')
    web_base = Env.get('web_base') or '/'
    ctx = {
        'api_key': api_key,
        'api_base': '%sapi/%s' % (web_base, api_key),
        'web_base': web_base,
        'new_base': web_base,
    }
    if extra:
        ctx.update(extra)
    return ctx


def _absolute_base(request: Request) -> str:
    """Build the app's real, externally-reachable base URL (scheme+host+web_base).

    Used for things like the add-by-URL bookmarklet, which must navigate to an
    absolute URL (it runs from an arbitrary third-party page), not a
    site-relative one.

    The scheme/host come from ``request.base_url`` which Starlette derives from
    the client-supplied ``Host`` header (there is no TrustedHostMiddleware). That
    value is untrusted, so we hard-sanitize it: force an http(s) scheme and strip
    the host to the characters legal in a URL authority. This neutralises header
    injection at the source (belt to the template's ``| tojson`` suspenders) so a
    ``Host: evil'};alert()//`` can't break out of the bookmarklet's JS string.
    """
    web_base = Env.get('web_base') or '/'
    parts = urlsplit(str(request.base_url))
    scheme = parts.scheme if parts.scheme in ('http', 'https') else 'http'
    netloc = re.sub(r'[^A-Za-z0-9.\-:\[\]]', '', parts.netloc)
    return '%s://%s%s' % (scheme, netloc, web_base)


def _releases_ctx(movie, movie_id, params):
    """Everything the releases partial (partials/movie_releases.html) needs,
    computed once so the full-page render and the standalone htmx route agree.

    Also returns `title`, using the SAME chain
    (`titles[0] or original_title or movie.title or 'Unknown'`) that
    `partials/movie_detail.html`'s `<h1>` uses -- both the full page and the
    standalone `/partial/movie/{id}/releases` route (which has no other
    source for the table's `<caption>`) now agree on one title, computed
    here only. `movie_detail.html` used to recompute its own copy of this
    chain and silently shadow this one, which let the two derivations drift:
    with `titles=[]` and an `original_title` set, the full page showed the
    real title while the standalone releases route showed "Unknown".
    """
    from couchpotato.ui.releases_view import (
        filter_and_sort_releases, filter_options, normalise_controls, sort_columns,
    )

    movie = movie or {}
    profile = movie.get('profile') or {}
    profile_qualities = profile.get('qualities') or []

    all_releases = movie.get('releases') or []
    # Same profile-matching rule the template used to apply inline.
    matching = [r for r in all_releases
                if not profile_qualities or r.get('quality') in profile_qualities]

    controls = normalise_controls(params)
    web_base = Env.get('web_base') or '/'

    info = movie.get('info') or {}
    titles = info.get('titles') or []
    title = titles[0] if titles else (info.get('original_title') or movie.get('title') or 'Unknown')

    return {
        'movie_id': movie_id,
        'title': title,
        'releases': filter_and_sort_releases(matching, controls, profile_qualities),
        # Profile-matching count: drives the filter controls, the table, and
        # the "N of M releases" live region.
        'total_releases': len(matching),
        # Raw (pre-profile-filter) count: lets the template tell "no releases
        # exist yet" apart from "releases exist but none match the profile's
        # quality list" -- the second case is actionable (the profile is
        # hiding something) and used to render its own message, restoring
        # what master showed before total_releases became profile-filtered.
        'raw_release_count': len(all_releases),
        'controls': controls,
        'options': filter_options(matching, profile_qualities),
        'columns': sort_columns(controls, movie_id, web_base),
    }


#: `/movie/{id}` is content-negotiated on htmx's request headers (full page vs
#: releases fragment), so every response from that path must advertise it or a
#: caching proxy will hand the wrong body to the wrong request.
_HTMX_VARY = {'Vary': 'HX-Request, HX-History-Restore-Request'}


async def _render_releases_partial(movie_id, params):
    """Render partials/movie_releases.html for `movie_id`, filtered/sorted per
    `params`. Shared by the standalone GET /partial/movie/{id}/releases route
    and movie_detail's htmx branch below -- see that route's comment for why
    a filter change needs this rather than the full-page shell.
    """
    from couchpotato.api import callApiHandler
    movie = {}
    try:
        result = await run_in_threadpool(callApiHandler, 'media.get', id=movie_id)
        if isinstance(result, dict):
            movie = result.get('media', result) or {}
    except Exception:
        log.error('Failed to fetch movie for release list')
    tmpl = _jinja.get_template('partials/movie_releases.html')
    releases_ctx = _releases_ctx(movie, movie_id, params)
    return HTMLResponse(tmpl.render(**releases_ctx, **_ctx()), headers = _HTMX_VARY)


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
        wanted_path = request.url.path.rstrip('/')
        wanted_path = wanted_path.rsplit('/available', 1)[0] + '/wanted'
        return RedirectResponse(url='%s?filter=available' % wanted_path)

    @router.get('/library/')
    @router.get('/library')
    async def library(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('wanted.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'library'})))


    @router.get('/movie/{movie_id}/')
    @router.get('/movie/{movie_id}')
    async def movie_detail(movie_id: str, request: Request, user=Depends(require_auth)):
        # The release-list filter form (partials/movie_releases.html)
        # targets THIS path with hx-get (not the standalone
        # /partial/movie/{id}/releases endpoint) specifically so its
        # hx-push-url="true" pushes a URL that is also valid to land on
        # directly -- the standalone endpoint returns a bare, unstyled
        # fragment, which would look broken if it ended up in the address
        # bar after a filter change (sort links already avoid this by
        # pushing an explicit href distinct from what they fetch; a form's
        # values are chosen at submit time, so it cannot pre-compute a
        # per-selection href the same way). htmx marks every request it
        # issues with `HX-Request: true`, so branch on that: an htmx
        # (fragment) request gets exactly the releases partial -- matching
        # #movie-releases, the form's hx-target -- while a real navigation
        # (no header) still gets the full-page shell below.
        #
        # `hx-history-restore-request` must be excluded: on a Back/Forward
        # whose history snapshot htmx no longer has cached (after a reload, or
        # once the snapshot is evicted), htmx re-requests the URL with BOTH
        # headers set and replaces the ENTIRE body with the response. Serving
        # the bare releases partial there would leave the whole page as just
        # the release table -- no nav, no movie. A restore wants the full page.
        is_htmx_fragment = (request.headers.get('hx-request') == 'true'
                            and request.headers.get('hx-history-restore-request') != 'true')
        if is_htmx_fragment:
            return await _render_releases_partial(movie_id, dict(request.query_params))

        tmpl = _jinja.get_template('detail.html')
        # Forward the release-list controls (source/quality/sort/dir/...) into
        # the initial hx-get, so a filtered/sorted URL like
        # /movie/{id}?source=nzb&sort=size is bookmarkable and shareable
        # (FEAT-007 B8) -- detail.html is an htmx shell with no other way to
        # apply them on first paint.
        query = request.url.query
        detail_query = ('?' + query) if query else ''
        # Vary: this URL returns two different bodies (full shell vs releases
        # fragment) depending on request headers, so anything caching in front
        # of the app -- a reverse proxy, a CDN -- must key on them or it will
        # serve a bare table to a browser asking for the page, or vice versa.
        # Set on BOTH branches; the header has to be present on the cacheable
        # response, not just the fragment one.
        return HTMLResponse(tmpl.render(**_ctx({'movie_id': movie_id, 'detail_query': detail_query})),
                            headers = _HTMX_VARY)

    @router.get('/suggestions/')
    @router.get('/suggestions')
    async def suggestions_page(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('suggestions.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'suggestions'})))

    @router.get('/collections/')
    @router.get('/collections')
    async def collections_page(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('collections.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'collections'})))

    @router.get('/add/')
    @router.get('/add')
    async def add_movie(request: Request, url: str = None, user=Depends(require_auth)):
        tmpl = _jinja.get_template('add.html')
        ctx = {
            'current_page': 'add',
            'url': url or '',
            'absolute_base': _absolute_base(request),
        }
        return HTMLResponse(tmpl.render(**_ctx(ctx)))

    @router.get('/settings/')
    @router.get('/settings')
    async def settings_page(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('settings.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'settings'})))

    @router.get('/wizard/')
    @router.get('/wizard')
    async def wizard_page(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('wizard.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'wizard'})))

    @router.get('/logs/')
    @router.get('/logs')
    async def logs_page(request: Request, user=Depends(require_auth)):
        tmpl = _jinja.get_template('logs.html')
        return HTMLResponse(tmpl.render(**_ctx({'current_page': 'logs'})))

    # --- htmx partials ---

    @router.get('/partial/movies')
    async def partial_movies(request: Request, status: str = 'active', with_releases: bool = False, user=Depends(require_auth)):
        """Return movie card grid as HTML partial for htmx."""
        from couchpotato.api import callApiHandler
        try:
            params = {'type': 'movie', 'status': status}
            # with_releases=True  → Available page: active movies that have any release
            # with_releases=False → Wanted page: active movies with no releases yet
            params['has_releases'] = with_releases

            result = await run_in_threadpool(callApiHandler, 'media.list', **params)
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
            result = await run_in_threadpool(callApiHandler, 'media.get', id=movie_id)
            if isinstance(result, dict):
                movie = result.get('media', result)
            else:
                movie = {}
        except Exception:
            log.error('Failed to fetch movie detail')
            movie = {}
        movie = movie or {}
        tmpl = _jinja.get_template('partials/movie_detail.html')
        # Same builder the standalone releases route uses, so the inline
        # first paint and a later htmx swap of #movie-releases agree, and so
        # a bookmarked/shared filtered URL (FEAT-007 B8) renders filtered on
        # first paint too.
        releases_ctx = _releases_ctx(movie, movie_id, dict(request.query_params))
        return HTMLResponse(tmpl.render(movie=movie, **releases_ctx, **_ctx()))

    @router.get('/partial/movie/{movie_id}/releases')
    async def partial_movie_releases(movie_id: str, request: Request, user=Depends(require_auth)):
        """Return the release list, filtered and sorted per the query params.

        Behind htmx: the sort links in partials/movie_releases.html target
        #movie-releases with hx-swap="outerHTML" against this route (the
        filter form targets movie_detail's own path instead -- see its
        comment for why).
        """
        return await _render_releases_partial(movie_id, dict(request.query_params))

    @router.get('/partial/search')
    async def partial_search(request: Request, q: str = '', user=Depends(require_auth)):
        """Search TMDB and return results as HTML partial."""
        from couchpotato.api import callApiHandler
        movies = []
        if q:
            try:
                result = await run_in_threadpool(callApiHandler, 'movie.search', q=q)
                if isinstance(result, dict):
                    movies = result.get('movies', [])
                elif isinstance(result, list):
                    movies = result
            except Exception:
                log.error('Failed to search movies')
        tmpl = _jinja.get_template('partials/search_results.html')
        return HTMLResponse(tmpl.render(movies=movies, **_ctx()))

    @router.get('/partial/add-via-url')
    async def partial_add_via_url(request: Request, url: str = '', user=Depends(require_auth)):
        """Resolve a movie page URL (IMDb/TMDB/Trakt/Letterboxd/etc.) via the
        userscript.add_via_url API view and render it as a movie card.

        userscript.add_via_url (Userscript.getViaUrl) always returns a dict:
        {'url': url, 'movie': <dict>} on success, or
        {'url': url, 'movie': <falsy or error string>, 'error': <str>} on failure.
        """
        from couchpotato.api import callApiHandler
        movie = None
        error = None
        if url:
            try:
                result = await run_in_threadpool(callApiHandler, 'userscript.add_via_url', url=url)
                candidate = result.get('movie') if isinstance(result, dict) else None
                # `and candidate` guards the empty-dict case: getViaUrl treats a
                # truthy-but-empty {} movie as success (no error key), but the
                # partial renders {} as "no movie" — without this it'd show the
                # empty state with no explanatory error text.
                if isinstance(candidate, dict) and candidate:
                    movie = candidate
                elif isinstance(result, dict) and result.get('error'):
                    error = result['error']
                else:
                    error = 'Failed getting movie info'
            except Exception:
                # Defensive/effectively-dead: callApiHandler already catches all
                # handler exceptions and returns {'success': False, ...}, so this
                # never fires today (mirrors partial_search). Kept in case that
                # contract changes.
                log.error('Failed to resolve movie via url: %s', url)
                error = 'Failed getting movie info'
        else:
            error = 'No URL provided'
        tmpl = _jinja.get_template('partials/add_via_url_result.html')
        return HTMLResponse(tmpl.render(movie=movie, error=error, url=url, **_ctx()))

    @router.get('/partial/suggestions')
    async def partial_suggestions(request: Request, user=Depends(require_auth)):
        """Return movie suggestions as HTML partial."""
        from couchpotato.api import callApiHandler
        try:
            result = await run_in_threadpool(callApiHandler, 'suggestion.view')
            # callApiHandler swallows handler exceptions and returns
            # {'success': False, ...} rather than raising, so an error-shaped
            # result — not just a thrown exception — is the real failure signal.
            # Surface it as a non-2xx so the loader shows its error / Try-again
            # state (htmx:response-error). A genuinely empty (success) result
            # still renders normally with 200.
            if not isinstance(result, dict) or result.get('success') is False:
                # WARNING, not ERROR: a provider returning success=False is an
                # expected/recoverable third-party degradation that can recur per
                # page-load; logging it at ERROR would drown genuine app errors.
                log.warning('Suggestions unavailable (provider failure): %r', result)
                return HTMLResponse('Failed to load suggestions', status_code=500)
            movies = result.get('movies', [])
        except Exception:
            log.error('Failed to fetch suggestions', exc_info=True)
            return HTMLResponse('Failed to load suggestions', status_code=500)
        tmpl = _jinja.get_template('partials/suggestions.html')
        return HTMLResponse(tmpl.render(movies=movies, **_ctx()))

    @router.get('/partial/charts')
    async def partial_charts(request: Request, user=Depends(require_auth)):
        """Return chart lists (IMDB, Blu-ray, etc.) as HTML partial."""
        from couchpotato.api import callApiHandler
        try:
            result = await run_in_threadpool(callApiHandler, 'charts.view')
            # callApiHandler swallows handler exceptions and returns
            # {'success': False, ...} rather than raising, so an error-shaped
            # result — not just a thrown exception — is the real failure signal.
            # Surface it as a non-2xx so the loader shows its error / Try-again
            # state (htmx:response-error). A genuinely empty (success) result
            # still renders normally with 200.
            if not isinstance(result, dict) or result.get('success') is False:
                # WARNING, not ERROR: a chart source returning success=False is an
                # expected/recoverable third-party degradation that can recur per
                # page-load; logging it at ERROR would drown genuine app errors.
                log.warning('Charts unavailable (provider failure): %r', result)
                return HTMLResponse('Failed to load charts', status_code=500)
            charts = result.get('charts', [])
        except Exception:
            log.error('Failed to fetch charts', exc_info=True)
            return HTMLResponse('Failed to load charts', status_code=500)
        tmpl = _jinja.get_template('partials/charts.html')
        return HTMLResponse(tmpl.render(charts=charts, **_ctx()))

    @router.get('/partial/collections')
    async def partial_collections(request: Request, user=Depends(require_auth)):
        """Return movie collections as an HTML partial."""
        from couchpotato.api import callApiHandler
        collections = []
        try:
            result = await run_in_threadpool(callApiHandler, 'collection.list')
            if isinstance(result, dict):
                collections = result.get('collections', [])
        except Exception:
            log.error('Failed to fetch collections')
        tmpl = _jinja.get_template('partials/collections.html')
        return HTMLResponse(tmpl.render(collections=collections, **_ctx()))

    @router.get('/partial/movie/{movie_id}/collections')
    async def partial_movie_collections(movie_id: str, request: Request, user=Depends(require_auth)):
        """Return collection controls for one movie."""
        from couchpotato.api import callApiHandler
        collections = []
        try:
            result = await run_in_threadpool(callApiHandler, 'collection.list', include_movies='0')
            if isinstance(result, dict):
                collections = result.get('collections', [])
        except Exception:
            log.error('Failed to fetch movie collections')
        tmpl = _jinja.get_template('partials/movie_collections.html')
        return HTMLResponse(tmpl.render(collections=collections, movie_id=movie_id, **_ctx()))

    @router.get('/partial/settings/profiles')
    async def partial_settings_profiles(request: Request, user=Depends(require_auth)):
        """Return quality profiles management partial for the Settings Profiles tab."""
        tmpl = _jinja.get_template('partials/settings/profiles.html')
        return HTMLResponse(tmpl.render(**_ctx()))

    @router.get('/partial/settings/{section}')
    async def partial_settings_section(section: str, request: Request, user=Depends(require_auth)):
        """Return settings section as HTML partial (placeholder)."""
        safe_section = html.escape(section)
        return HTMLResponse('<p class="text-xs text-cp-muted">Settings for %s will be loaded here.</p>' % safe_section)

    @router.get('/partial/profiles')
    async def partial_profiles(request: Request, user=Depends(require_auth)):
        """Return quality profiles as options."""
        from couchpotato.api import callApiHandler
        try:
            result = await run_in_threadpool(callApiHandler, 'profile.list')
            if isinstance(result, dict):
                profiles = result.get('list', result.get('profiles', []))
            else:
                profiles = []
        except Exception:
            profiles = []
        tmpl = _jinja.get_template('partials/profile_options.html')
        return HTMLResponse(tmpl.render(profiles=profiles))

    return router
