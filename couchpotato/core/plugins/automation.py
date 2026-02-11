from couchpotato.api import addApiView
from couchpotato.core.event import addEvent, fireEvent
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.environment import Env

log = CPLog(__name__)

autoload = 'Automation'


class Automation(Plugin):

    def __init__(self):

        addEvent('app.load', self.setCrons)

        if not Env.get('dev'):
            addEvent('app.load', self.addMovies)

        addApiView('automation.add_movies', self.addMoviesFromApi, docs = {
            'desc': 'Manually trigger the automation scan. Hangs until scan is complete. Useful for webhooks.',
            'return': {'type': 'object: {"success": true}'},
        })
        addApiView('automation.list', self.listAutomationMovies, docs = {
            'desc': 'List movies found by automation providers without adding them.',
            'return': {'type': 'object: {"success": true, "movies": []}'},
        })
        addEvent('setting.save.automation.hour.after', self.setCrons)

    def setCrons(self):
        fireEvent('schedule.interval', 'automation.add_movies', self.addMovies, hours = self.conf('hour', default = 12))

    def addMoviesFromApi(self, **kwargs):
        self.addMovies()
        return {
            'success': True
        }

    def listAutomationMovies(self, **kwargs):
        """Return the list of movies found by automation providers without adding them."""
        movies = fireEvent('automation.get_movies', merge = True)
        return {
            'success': True,
            'movies': movies if movies else []
        }

    def addMovies(self):

        movies = fireEvent('automation.get_movies', merge = True)
        movie_ids = []

        for imdb_id in movies:

            if self.shuttingDown():
                break

            prop_name = 'automation.added.%s' % imdb_id
            added = Env.prop(prop_name, default = False)
            if not added:
                added_movie = fireEvent('movie.add', params = {'identifier': imdb_id}, force_readd = False, search_after = False, update_after = True, single = True)
                if added_movie:
                    movie_ids.append(added_movie['_id'])
                Env.prop(prop_name, True)

        for movie_id in movie_ids:

            if self.shuttingDown():
                break

            movie_dict = fireEvent('media.get', movie_id, single = True)
            if movie_dict:
                fireEvent('movie.searcher.single', movie_dict)

        return True


config = [{
    'name': 'automation',
    'order': 101,
    'groups': [
        {
            'tab': 'automation',
            'name': 'automation',
            'label': 'Auto-Add Filters',
            'description': 'Minimum quality requirements for movies added automatically from watchlists and popular lists below.',
            'options': [
                {
                    'name': 'year',
                    'default': 2011,
                    'type': 'int',
                    'label': 'Minimum Year',
                    'description': 'Only add movies released in this year or later.',
                },
                {
                    'name': 'votes',
                    'default': 1000,
                    'type': 'int',
                    'label': 'Minimum Votes',
                    'description': 'Only add movies with at least this many votes on IMDB.',
                },
                {
                    'name': 'rating',
                    'default': 7.0,
                    'type': 'float',
                    'label': 'Minimum Rating',
                    'description': 'Only add movies rated this high or above on IMDB.',
                },
                {
                    'name': 'hour',
                    'advanced': True,
                    'default': 12,
                    'label': 'Check Interval',
                    'type': 'int',
                    'unit': 'hours',
                    'description': 'How often to check watchlists for new movies (in hours).',
                },
                {
                    'name': 'required_genres',
                    'label': 'Required Genres',
                    'default': '',
                    'placeholder': 'Example: Action, Crime & Drama',
                    'description': 'Only add movies matching at least one genre set. Sets separated by ",", words within a set by "&".',
                },
                {
                    'name': 'ignored_genres',
                    'label': 'Ignored Genres',
                    'default': '',
                    'placeholder': 'Example: Horror, Comedy & Drama & Romance',
                    'description': 'Skip movies matching any genre set. Same format as above.',
                },
            ],
        },
    ],
}]
