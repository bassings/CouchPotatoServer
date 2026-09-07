from bs4 import BeautifulSoup
from couchpotato.core.event import fireEvent
from couchpotato.core.event_names import SCANNER_NAME_YEAR

from couchpotato.core.media._base.providers.userscript.base import UserscriptBase

autoload = 'Filmweb'


class Filmweb(UserscriptBase):

    version = 3

    includes = ['http://www.filmweb.pl/film/*']

    def getMovie(self, url):

        cookie = {'Cookie': 'welcomeScreen=welcome_screen'}

        try:
            data = self.urlopen(url, headers = cookie)
        except Exception:
            return

        html = BeautifulSoup(data)
        name = html.find('meta', {'name': 'title'})['content'][:-9].strip()
        name_year = fireEvent(SCANNER_NAME_YEAR, name, single = True)
        name = name_year.get('name')
        year = name_year.get('year')

        return self.search(name, year)
