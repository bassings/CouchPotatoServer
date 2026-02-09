import traceback
import re

from couchpotato import fireEvent
from couchpotato.core.helpers.encoding import ss
from couchpotato.core.helpers.rss import RSS
from couchpotato.core.helpers.variable import getImdb, splitString, tryInt
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.providers.base import MultiProvider
from couchpotato.core.media.movie.providers.automation.base import Automation


log = CPLog(__name__)

autoload = 'IMDB'


class IMDB(MultiProvider):

    def getTypes(self):
        return [IMDBWatchlist, IMDBAutomation, IMDBCharts]


class IMDBBase(Automation, RSS):

    interval = 1800

    charts = {
        'theater': {
            'order': 1,
            'name': 'IMDB - Movies in Theaters',
            'url': 'https://www.imdb.com/chart/moviemeter/',
        },
        'boxoffice': {
            'order': 2,
            'name': 'IMDB - Box Office',
            'url': 'https://www.imdb.com/chart/boxoffice/',
        },
        'top250': {
            'order': 3,
            'name': 'IMDB - Top 250 Movies',
            'url': 'https://www.imdb.com/chart/top/',
        },
    }

    def getInfo(self, imdb_id):
        return fireEvent('movie.info', identifier = imdb_id, extended = False, adding = False, merge = True)

    def getFromURL(self, url):
        log.debug('Getting IMDBs from: %s', url)
        html = self.getHTMLData(url)

        if not html:
            log.error('Failed fetching IMDB page "%s"', url)
            return []

        html = ss(html)
        imdbs = getImdb(html, multiple = True) if html else []

        if not imdbs:
            log.warning('No IMDB IDs found on page "%s"', url)

        return imdbs


class IMDBWatchlist(IMDBBase):

    enabled_option = 'automation_enabled'

    def getIMDBids(self):

        movies = []

        watchlist_enablers = [tryInt(x) for x in splitString(self.conf('automation_urls_use'))]
        watchlist_urls = splitString(self.conf('automation_urls'))

        index = -1
        for watchlist_url in watchlist_urls:

            try:
                # Get list ID
                ids = re.findall(r'(?:list/|list_id=)([a-zA-Z0-9\-_]{11})', watchlist_url)
                if len(ids) == 1:
                    watchlist_url = 'http://www.imdb.com/list/%s/?view=compact&sort=created:asc' % ids[0]
                # Try find user id with watchlist
                else:
                    userids = re.findall(r'(ur\d{7,9})', watchlist_url)
                    if len(userids) == 1:
                        watchlist_url = 'http://www.imdb.com/user/%s/watchlist?view=compact&sort=created:asc' % userids[0]
            except Exception:
                log.error('Failed getting id from watchlist: %s', traceback.format_exc())

            index += 1
            if not watchlist_enablers[index]:
                continue

            start = 0
            while True:
                try:

                    w_url = '%s&start=%s' % (watchlist_url, start)
                    imdbs = self.getFromURL(w_url)

                    for imdb in imdbs:
                        if imdb not in movies:
                            movies.append(imdb)

                        if self.shuttingDown():
                            break

                    log.debug('Found %s movies on %s', len(imdbs), w_url)

                    if len(imdbs) < 225:
                        break

                    start = len(movies)

                except Exception:
                    log.error('Failed loading IMDB watchlist: %s %s', watchlist_url, traceback.format_exc())
                    break

        return movies


class IMDBAutomation(IMDBBase):

    enabled_option = 'automation_providers_enabled'

    def getIMDBids(self):

        movies = []

        for name in self.charts:
            chart = self.charts[name]
            url = chart.get('url')

            if self.conf('automation_charts_%s' % name):
                imdb_ids = self.getFromURL(url)

                try:
                    for imdb_id in imdb_ids:
                        info = self.getInfo(imdb_id)
                        if info and self.isMinimalMovie(info):
                            movies.append(imdb_id)

                        if self.shuttingDown():
                            break

                except Exception:
                    log.error('Failed loading IMDB chart results from %s: %s', url, traceback.format_exc())

        return movies


class IMDBCharts(IMDBBase):

    def getChartList(self):
        # Nearly identical to 'getIMDBids', but we don't care about minimalMovie and return all movie data (not just id)
        movie_lists = []
        max_items = 10

        for name in self.charts:
            chart = self.charts[name].copy()
            cache_key = 'imdb.chart_display_%s' % name

            if self.conf('chart_display_%s' % name):

                cached = self.getCache(cache_key)
                if cached:
                    chart['list'] = cached
                    movie_lists.append(chart)
                    continue

                url = chart.get('url')

                chart['list'] = []
                imdb_ids = self.getFromURL(url)

                try:
                    for imdb_id in imdb_ids[0:max_items]:

                        is_movie = fireEvent('movie.is_movie', identifier = imdb_id, adding = False, single = True)
                        if not is_movie:
                            continue

                        info = self.getInfo(imdb_id)
                        chart['list'].append(info)

                        if self.shuttingDown():
                            break
                except Exception:
                    log.error('Failed loading IMDB chart results from %s: %s', url, traceback.format_exc())

                self.setCache(cache_key, chart['list'], timeout = 259200)

                if chart['list']:
                    movie_lists.append(chart)

        return movie_lists


config = [{
    'name': 'imdb',
    'groups': [
        {
            'tab': 'automation',
            'list': 'watchlist_providers',
            'name': 'imdb_automation_watchlist',
            'label': 'IMDB',
            'description': 'From any <strong>public</strong> IMDB watchlists.',
            'options': [
                {
                    'name': 'automation_enabled',
                    'default': False,
                    'type': 'enabler',
                },
                {
                    'name': 'automation_urls_use',
                    'label': 'Use',
                },
                {
                    'name': 'automation_urls',
                    'label': 'url',
                    'type': 'combined',
                    'combine': ['automation_urls_use', 'automation_urls'],
                },
            ],
        },
        {
            'tab': 'automation',
            'list': 'automation_providers',
            'name': 'imdb_automation_charts',
            'label': 'IMDB',
            'description': 'Import movies from IMDB Charts',
            'options': [
                {
                    'name': 'automation_providers_enabled',
                    'default': False,
                    'type': 'enabler',
                },
                {
                    'name': 'automation_charts_theater',
                    'type': 'bool',
                    'label': 'In Theaters',
                    'description': 'New Movies <a href="http://www.imdb.com/movies-in-theaters/" target="_blank">In-Theaters</a> chart',
                    'default': True,
                },
                {
                    'name': 'automation_charts_top250',
                    'type': 'bool',
                    'label': 'TOP 250',
                    'description': 'IMDB <a href="http://www.imdb.com/chart/top/" target="_blank">TOP 250</a> chart',
                    'default': False,
                },
                {
                    'name': 'automation_charts_boxoffice',
                    'type': 'bool',
                    'label': 'Box office TOP 10',
                    'description': 'IMDB Box office <a href="http://www.imdb.com/chart/" target="_blank">TOP 10</a> chart',
                    'default': True,
                },
            ],
        },
        {
            'tab': 'display',
            'list': 'charts_providers',
            'name': 'imdb_charts_display',
            'label': 'IMDB',
            'description': 'Display movies from IMDB Charts',
            'options': [
                {
                    'name': 'chart_display_enabled',
                    'default': True,
                    'type': 'enabler',
                },
                {
                    'name': 'chart_display_theater',
                    'type': 'bool',
                    'label': 'In Theaters',
                    'description': 'New Movies <a href="http://www.imdb.com/movies-in-theaters/" target="_blank">In-Theaters</a> chart',
                    'default': False,
                },
                {
                    'name': 'chart_display_top250',
                    'type': 'bool',
                    'label': 'TOP 250',
                    'description': 'IMDB <a href="http://www.imdb.com/chart/top/" target="_blank">TOP 250</a> chart',
                    'default': False,
                },
                {
                    'name': 'chart_display_boxoffice',
                    'type': 'bool',
                    'label': 'Box office TOP 10',
                    'description': 'IMDB Box office <a href="http://www.imdb.com/chart/" target="_blank">TOP 10</a> chart',
                    'default': True,
                },
            ],
        },
    ],
}]
