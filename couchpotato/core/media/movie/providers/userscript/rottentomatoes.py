import re
import traceback

from couchpotato.core.event import fireEvent
from couchpotato.core.event_names import SCANNER_NAME_YEAR
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.providers.userscript.base import UserscriptBase


log = CPLog(__name__)

autoload = 'RottenTomatoes'


class RottenTomatoes(UserscriptBase):

    includes = ['*://www.rottentomatoes.com/m/*']
    excludes = ['*://www.rottentomatoes.com/m/*/*/']

    version = 4

    def getMovie(self, url):

        try:
            data = self.getUrl(url)
        except Exception:
            return

        try:
            title = re.findall("<title>(.*)</title>", data)
            title = title[0].split(' - Rotten')[0].replace('&nbsp;', ' ').decode('unicode_escape')
            name_year = fireEvent(SCANNER_NAME_YEAR, title, single = True)

            name = name_year.get('name')
            year = name_year.get('year')

            if name and year:
                return self.search(name, year)

        except Exception:
            log.error('Failed parsing page for title and year: %s', traceback.format_exc())
