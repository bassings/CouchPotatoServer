import traceback

from couchpotato.core.event import fireEvent
from couchpotato.core.event_names import SCANNER_NAME_YEAR
from couchpotato.core.logger import CPLog
from couchpotato.core.media._base.providers.userscript.base import UserscriptBase


log = CPLog(__name__)

autoload = 'Flickchart'


class Flickchart(UserscriptBase):

    version = 2

    includes = ['http://www.flickchart.com/movie/*']

    def getMovie(self, url):

        try:
            data = self.getUrl(url)
        except Exception:
            return

        try:
            start = data.find('<title>')
            end = data.find('</title>', start)
            page_title = data[start + len('<title>'):end].strip().split('- Flick')

            year_name = fireEvent(SCANNER_NAME_YEAR, page_title[0], single = True)

            return self.search(year_name.get('name'), year_name.get('year'))
        except Exception:
            log.error('Failed parsing page for title and year: %s', traceback.format_exc())

