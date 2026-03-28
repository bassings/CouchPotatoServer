"""TMDB Charts provider for movie suggestions.

Replaces IMDB Charts which are now blocked by WAF protection.
Uses TMDB's official API for reliable chart data.
"""
import random
import traceback
from base64 import b64decode as bd

from couchpotato import fireEvent
from couchpotato.core.helpers.variable import tryInt
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.providers.base import MultiProvider
from couchpotato.core.media.movie.providers.automation.base import Automation
from couchpotato.environment import Env

log = CPLog(__name__)

autoload = 'TMDBCharts'


class TMDBCharts(MultiProvider):

    def getTypes(self):
        return [TMDBChartsAutomation, TMDBChartsDisplay]


class TMDBChartsBase(Automation):
    """Base class for TMDB chart providers."""

    interval = 1800
    http_time_between_calls = 0.35

    # TMDB API keys (same as themoviedb info provider)
    ak = ['ZTIyNGZlNGYzZmVjNWY3YjU1NzA2NDFmN2NkM2RmM2E=',
          'ZjZiZDY4N2ZmYTYzY2QyODJiNmZmMmM2ODc3ZjI2Njk=']

    charts = {
        'now_playing': {
            'order': 1,
            'name': 'TMDB - Now Playing',
            'endpoint': '/movie/now_playing',
            'description': 'Movies currently in theaters.',
        },
        'popular': {
            'order': 2,
            'name': 'TMDB - Popular',
            'endpoint': '/movie/popular',
            'description': 'Current popular movies.',
        },
        'top_rated': {
            'order': 3,
            'name': 'TMDB - Top Rated',
            'endpoint': '/movie/top_rated',
            'description': 'Highest rated movies of all time.',
        },
        'upcoming': {
            'order': 4,
            'name': 'TMDB - Upcoming',
            'endpoint': '/movie/upcoming',
            'description': 'Movies coming soon to theaters.',
        },
    }

    _validated_key = None

    def getApiKey(self):
        """Get TMDB API key from settings or use built-in."""
        if self._validated_key:
            return self._validated_key

        # Try config key first
        try:
            import requests
            key = Env.setting('api_key', section='themoviedb')
            if key:
                r = requests.get(
                    'https://api.themoviedb.org/3/configuration?api_key=%s' % key,
                    timeout=5
                )
                if r.status_code == 200:
                    self._validated_key = key
                    return key
                log.debug('Config TMDB API key is invalid, using built-in')
        except Exception:
            pass

        decoded = bd(random.choice(self.ak))
        key = decoded.decode('utf-8') if isinstance(decoded, bytes) else decoded
        self._validated_key = key
        return key

    def _tmdbRequest(self, endpoint, params=None):
        """Make a request to the TMDB API."""
        import requests
        params = params or {}
        params['api_key'] = self.getApiKey()

        url = 'https://api.themoviedb.org/3%s' % endpoint
        log.debug('TMDB request: %s', url)

        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            else:
                log.error('TMDB API error: %s %s', response.status_code, response.text[:200])
                return None
        except Exception:
            log.error('TMDB request failed: %s', traceback.format_exc())
            return None

    def getInfo(self, tmdb_id):
        """Get movie info from TMDB ID."""
        return fireEvent('movie.info', identifier='tmdb:%s' % tmdb_id, extended=False, adding=False, merge=True)

    def getChartMovies(self, chart_name, max_items=40):
        """Fetch movies from a TMDB chart endpoint."""
        chart = self.charts.get(chart_name)
        if not chart:
            return []

        endpoint = chart['endpoint']
        movies = []
        page = 1

        while len(movies) < max_items:
            data = self._tmdbRequest(endpoint, {'page': page, 'region': 'AU'})
            if not data or not data.get('results'):
                break

            for movie in data['results']:
                if len(movies) >= max_items:
                    break

                tmdb_id = movie.get('id')
                if tmdb_id:
                    info = self.getInfo(tmdb_id)
                    if info:
                        movies.append(info)

                if self.shuttingDown():
                    return movies

            # Check if there are more pages
            if page >= data.get('total_pages', 1):
                break
            page += 1

        return movies


class TMDBChartsAutomation(TMDBChartsBase):
    """Auto-add movies from TMDB charts to wanted list."""

    enabled_option = 'automation_providers_enabled'

    def conf(self, attr, value=None, default=None, section=None):
        """Override conf to use tmdb_charts section."""
        return super().conf(attr, value=value, default=default, section='tmdb_charts')

    def getIMDBids(self):
        """Get IMDB IDs from enabled charts for automation."""
        movies = []

        for name in self.charts:
            if self.conf('automation_charts_%s' % name):
                log.info('Fetching TMDB chart for automation: %s', name)

                chart_movies = self.getChartMovies(name, max_items=40)
                for info in chart_movies:
                    if info and self.isMinimalMovie(info):
                        imdb_id = info.get('imdb')
                        if imdb_id and imdb_id not in movies:
                            movies.append(imdb_id)

                    if self.shuttingDown():
                        break

        return movies


class TMDBChartsDisplay(TMDBChartsBase):
    """Display TMDB charts on the Suggestions page."""

    chart_enabled_option = 'chart_display_enabled'

    def conf(self, attr, value=None, default=None, section=None):
        """Override conf to use tmdb_charts section."""
        return super().conf(attr, value=value, default=default, section='tmdb_charts')

    def getChartList(self):
        """Get chart data for display on suggestions page."""
        movie_lists = []
        max_items = 40

        for name in self.charts:
            chart = self.charts[name].copy()
            cache_key = 'tmdb.chart_display_%s' % name

            chart_enabled = self.conf('chart_display_%s' % name)
            log.info('TMDB Chart %s enabled=%s', name, chart_enabled)

            if chart_enabled:
                cached = self.getCache(cache_key)
                log.info('TMDB Chart %s cache: %s', name, 'HIT (%d items)' % len(cached) if cached else 'MISS')

                if cached:
                    chart['list'] = cached
                    movie_lists.append(chart)
                    continue

                chart['list'] = self.getChartMovies(name, max_items=max_items)
                log.info('TMDB Chart %s: fetched %d movies', name, len(chart['list']))

                # Cache for 3 days
                self.setCache(cache_key, chart['list'], timeout=259200)

                if chart['list']:
                    movie_lists.append(chart)

        return movie_lists


config = [{
    'name': 'tmdb_charts',
    'groups': [
        {
            'tab': 'automation',
            'list': 'automation_providers',
            'name': 'tmdb_charts_automation',
            'label': 'TMDB Charts Auto-Add',
            'description': 'Automatically add movies from TMDB chart lists.',
            'options': [
                {
                    'name': 'automation_providers_enabled',
                    'default': False,
                    'type': 'enabler',
                },
                {
                    'name': 'automation_charts_now_playing',
                    'type': 'bool',
                    'label': 'Now Playing',
                    'description': 'Movies currently in theaters.',
                    'default': True,
                },
                {
                    'name': 'automation_charts_popular',
                    'type': 'bool',
                    'label': 'Popular',
                    'description': 'Current popular movies.',
                    'default': True,
                },
                {
                    'name': 'automation_charts_top_rated',
                    'type': 'bool',
                    'label': 'Top Rated',
                    'description': 'Highest rated movies of all time.',
                    'default': False,
                },
                {
                    'name': 'automation_charts_upcoming',
                    'type': 'bool',
                    'label': 'Upcoming',
                    'description': 'Movies coming soon.',
                    'default': False,
                },
            ],
        },
        {
            'tab': 'display',
            'list': 'charts_providers',
            'name': 'tmdb_charts_display',
            'label': 'TMDB Charts',
            'description': 'Show TMDB chart data on the Suggestions page.',
            'options': [
                {
                    'name': 'chart_display_enabled',
                    'default': True,
                    'type': 'enabler',
                },
                {
                    'name': 'chart_display_now_playing',
                    'type': 'bool',
                    'label': 'Now Playing',
                    'description': 'Movies currently in theaters.',
                    'default': True,
                },
                {
                    'name': 'chart_display_popular',
                    'type': 'bool',
                    'label': 'Popular',
                    'description': 'Current popular movies.',
                    'default': True,
                },
                {
                    'name': 'chart_display_top_rated',
                    'type': 'bool',
                    'label': 'Top Rated',
                    'description': 'Highest rated movies of all time.',
                    'default': False,
                },
                {
                    'name': 'chart_display_upcoming',
                    'type': 'bool',
                    'label': 'Upcoming',
                    'description': 'Movies coming soon.',
                    'default': False,
                },
            ],
        },
    ],
}]
