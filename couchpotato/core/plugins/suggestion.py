"""Movie suggestions using TMDB recommendations and similar movies.

Replaces the dead couchpotatoapi suggestion feature with local TMDB lookups.
Picks random movies from the user's library, fetches TMDB recommendations,
and filters out movies already in the library.
"""
import random
import time
import traceback
from base64 import b64decode as bd

from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.helpers.encoding import tryUrlencode
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.environment import Env

log = CPLog(__name__)

autoload = 'Suggestion'


class Suggestion(Plugin):
    """Provide movie suggestions based on TMDB recommendations."""

    http_time_between_calls = 0.35

    # Cache for suggestions
    _cache = None
    _cache_time = 0
    _cache_ttl = 3600  # 1 hour

    # TMDB API keys (same as themoviedb provider)
    ak = ['ZTIyNGZlNGYzZmVjNWY3YjU1NzA2NDFmN2NkM2RmM2E=',
          'ZjZiZDY4N2ZmYTYzY2QyODJiNmZmMmM2ODc3ZjI2Njk=']

    # Ignored suggestions (stored as IMDB IDs)
    _ignored = set()

    def __init__(self):
        addApiView('suggestion.view', self.viewSuggestions, docs={
            'desc': 'Get movie suggestions based on your library',
            'return': {'type': 'object: {"success": true, "movies": [], "total": int}'},
        })
        addApiView('suggestion.ignore', self.ignoreSuggestion, docs={
            'desc': 'Ignore a suggestion so it won\'t appear again',
            'params': {
                'imdb': {'desc': 'IMDB ID to ignore'},
                'tmdb': {'desc': 'TMDB ID to ignore'},
                'seen': {'desc': 'Mark as seen (same as ignore)'},
            },
            'return': {'type': 'object: {"success": true}'},
        })

        addEvent('app.load', self._loadIgnored)

    def _loadIgnored(self):
        """Load the set of ignored suggestion IDs from properties."""
        ignored_str = Env.prop('suggestion.ignored', default='')
        if ignored_str:
            self._ignored = set(ignored_str.split(','))

    def _saveIgnored(self):
        """Persist the ignored set to properties."""
        Env.prop('suggestion.ignored', ','.join(self._ignored))

    def getApiKey(self):
        """Get TMDB API key from settings or use built-in."""
        try:
            key = Env.setting('api_key', section='themoviedb')
            if key and key != '9b939aee0aaafc12a65bf448e4af9543':
                return key
        except Exception:
            pass
        decoded = bd(random.choice(self.ak))
        return decoded.decode('utf-8') if isinstance(decoded, bytes) else decoded

    def _tmdbRequest(self, call, params=None):
        """Make a request to the TMDB API."""
        params = params or {}
        params = dict((k, v) for k, v in params.items() if v)
        param_str = tryUrlencode(params) if params else ''

        try:
            url = 'https://api.themoviedb.org/3/%s?api_key=%s%s' % (
                call, self.getApiKey(), '&%s' % param_str if param_str else ''
            )
            data = self.getJsonData(url, show_error=False)
            return data
        except Exception:
            log.debug('TMDB request failed: %s', call)
            return None

    def _getLibraryMovies(self):
        """Get movies from the user's library (wanted + managed)."""
        try:
            movies = fireEvent('media.list', types='movie', single=True) or {}
            return movies.get('movies', []) if isinstance(movies, dict) else movies
        except Exception:
            log.debug('Failed to get library movies: %s', traceback.format_exc())
            return []

    def _getLibraryImdbIds(self, movies):
        """Extract IMDB IDs from library movies."""
        ids = set()
        for movie in movies:
            info = movie.get('info', movie) if isinstance(movie, dict) else {}
            imdb = info.get('imdb') or movie.get('identifiers', {}).get('imdb', '')
            if imdb:
                ids.add(imdb)
        return ids

    def _getLibraryTmdbIds(self, movies):
        """Extract TMDB IDs from library movies."""
        ids = set()
        for movie in movies:
            info = movie.get('info', movie) if isinstance(movie, dict) else {}
            tmdb = info.get('tmdb_id') or movie.get('identifiers', {}).get('tmdb')
            if tmdb:
                ids.add(int(tmdb))
        return ids

    def _fetchRecommendations(self, tmdb_id):
        """Fetch recommendations for a movie from TMDB."""
        data = self._tmdbRequest('movie/%s/recommendations' % tmdb_id,
                                  {'language': 'en-US', 'page': '1'})
        if data and 'results' in data:
            return data['results']
        return []

    def _fetchSimilar(self, tmdb_id):
        """Fetch similar movies from TMDB."""
        data = self._tmdbRequest('movie/%s/similar' % tmdb_id,
                                  {'language': 'en-US', 'page': '1'})
        if data and 'results' in data:
            return data['results']
        return []

    def _tmdbToMovieFormat(self, tmdb_movie):
        """Convert a TMDB movie result to the format expected by the frontend MovieList."""
        poster = tmdb_movie.get('poster_path', '')
        backdrop = tmdb_movie.get('backdrop_path', '')
        base_url = 'https://image.tmdb.org/t/p/'

        images = {
            'poster': ['%sw500%s' % (base_url, poster)] if poster else [],
            'backdrop': ['%sw1280%s' % (base_url, backdrop)] if backdrop else [],
            'poster_original': ['%soriginal%s' % (base_url, poster)] if poster else [],
            'backdrop_original': ['%soriginal%s' % (base_url, backdrop)] if backdrop else [],
        }

        year = 0
        release_date = tmdb_movie.get('release_date', '')
        if release_date:
            try:
                year = int(release_date[:4])
            except (ValueError, IndexError):
                pass

        return {
            'tmdb_id': tmdb_movie.get('id'),
            'titles': [tmdb_movie.get('title', '')],
            'original_title': tmdb_movie.get('original_title', tmdb_movie.get('title', '')),
            'year': year,
            'images': images,
            'rating': {'imdb': [tmdb_movie.get('vote_average', 0), tmdb_movie.get('vote_count', 0)]},
            'plot': tmdb_movie.get('overview', ''),
            'genres': [],  # TMDB returns genre_ids not names in list endpoints
            'imdb': '',  # Would need an extra API call to get IMDB ID
        }

    def getSuggestions(self, limit=12):
        """Get movie suggestions based on the user's library.

        Picks random movies from the library, fetches TMDB recommendations
        and similar movies, deduplicates, and filters out library movies.
        """
        # Check cache
        now = time.time()
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        library_movies = self._getLibraryMovies()
        if not library_movies:
            return []

        library_imdb_ids = self._getLibraryImdbIds(library_movies)
        library_tmdb_ids = self._getLibraryTmdbIds(library_movies)

        # Pick up to 5 random movies that have TMDB IDs
        seed_movies = []
        for movie in library_movies:
            info = movie.get('info', movie) if isinstance(movie, dict) else {}
            tmdb_id = info.get('tmdb_id') or movie.get('identifiers', {}).get('tmdb')
            if tmdb_id:
                seed_movies.append(int(tmdb_id))

        if not seed_movies:
            log.debug('No movies with TMDB IDs in library for suggestions')
            return []

        random.shuffle(seed_movies)
        seeds = seed_movies[:5]

        # Fetch recommendations and similar movies
        candidates = {}
        for tmdb_id in seeds:
            try:
                for movie in self._fetchRecommendations(tmdb_id):
                    mid = movie.get('id')
                    if mid and mid not in candidates:
                        candidates[mid] = movie
            except Exception:
                pass

            try:
                for movie in self._fetchSimilar(tmdb_id):
                    mid = movie.get('id')
                    if mid and mid not in candidates:
                        candidates[mid] = movie
            except Exception:
                pass

        # Filter out movies already in library or ignored
        suggestions = []
        for tmdb_id, movie in candidates.items():
            if tmdb_id in library_tmdb_ids:
                continue
            # We can't easily check IMDB IDs without extra API calls
            # but we filter by TMDB ID which is good enough
            imdb_check = str(tmdb_id)
            if imdb_check in self._ignored:
                continue
            suggestions.append(self._tmdbToMovieFormat(movie))

        # Sort by rating descending
        suggestions.sort(key=lambda m: m.get('rating', {}).get('imdb', [0])[0], reverse=True)

        # Limit
        suggestions = suggestions[:limit]

        # Cache
        self._cache = suggestions
        self._cache_time = now

        return suggestions

    def viewSuggestions(self, **kwargs):
        """API endpoint: Return movie suggestions."""
        limit = int(kwargs.get('limit_offset', '12').split(',')[0]) if kwargs.get('limit_offset') else 12
        try:
            suggestions = self.getSuggestions(limit=limit)
        except Exception:
            log.error('Failed to get suggestions: %s', traceback.format_exc())
            suggestions = []

        return {
            'success': True,
            'movies': suggestions,
            'total': len(suggestions),
        }

    def ignoreSuggestion(self, **kwargs):
        """API endpoint: Ignore a suggestion."""
        imdb_id = kwargs.get('imdb', '')
        tmdb_id = kwargs.get('tmdb', '')

        if imdb_id:
            self._ignored.add(imdb_id)
        if tmdb_id:
            self._ignored.add(str(tmdb_id))

        self._saveIgnored()

        # Clear cache so ignored movie is removed
        self._cache = None

        return {
            'success': True
        }


config = [{
    'name': 'suggestion',
    'groups': [
        {
            'tab': 'display',
            'name': 'suggestion',
            'label': 'Suggestions',
            'options': [
                {
                    'name': 'enabled',
                    'default': True,
                    'type': 'enabler',
                },
            ],
        },
    ],
}]
