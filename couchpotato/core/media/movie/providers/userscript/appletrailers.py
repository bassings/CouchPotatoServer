import traceback

from couchpotato import tryInt, CPLog
from couchpotato.core.media._base.providers.userscript.base import UserscriptBase

log = CPLog(__name__)

autoload = 'AppleTrailers'


def _film_id(page):
    if isinstance(page, bytes):
        page = page.decode('utf-8', errors = 'replace')
    elif not isinstance(page, str):
        return None

    for line in page.split('\n'):
        closing_quote = line.rfind("';")
        if closing_quote == -1:
            continue
        opening_quote = line.rfind("'", 0, closing_quote)
        if opening_quote == -1:
            continue
        equals = line.rfind('=', 0, opening_quote)
        if equals == -1:
            continue
        marker = line.find('FilmId', 0, equals + 1)
        if marker == -1 or marker + len('FilmId') > equals:
            continue
        film_id = line[opening_quote + 1:closing_quote]
        if film_id and '\ufffd' not in film_id:
            return film_id
    return None


class AppleTrailers(UserscriptBase):

    includes = ['*://trailers.apple.com/trailers/*']

    def getMovie(self, url):

        try:
            data = self.getUrl(url)
        except Exception:
            return

        try:
            film_id = _film_id(data)
            if not film_id:
                return None

            data = self.getJsonData('https://trailers.apple.com/trailers/feeds/data/%s.json' % film_id)

            name = data['page']['movie_title']
            year = tryInt(data['page']['release_date'][0:4])

            return self.search(name, year)
        except Exception:
            log.error('Failed getting apple trailer info: %s', traceback.format_exc())
            return None
