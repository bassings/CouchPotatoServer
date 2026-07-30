import traceback

from couchpotato import tryInt
from couchpotato.core.event import addEvent
from couchpotato.core.logger import CPLog
from couchpotato.core.media.movie.providers.base import MovieProvider
from requests import HTTPError


log = CPLog(__name__)

autoload = 'FanartTV'


class FanartTV(MovieProvider):

    urls = {
        'api': 'http://webservice.fanart.tv/v3/movies/%s?api_key=%s'
    }

    MAX_EXTRAFANART = 20
    http_time_between_calls = 0

    def __init__(self):
        addEvent('movie.info', self.getArt, priority = 1)

    def getArt(self, identifier = None, extended = True, **kwargs):

        if not identifier or not extended:
            return {}

        if self.isDisabled():
            return {}

        images = {}

        try:
            url = self.urls['api'] % (identifier, self.conf('api_key'))
            fanart_data = self.getJsonData(url, show_error = False)

            if fanart_data:
                log.debug('Found images for %s', fanart_data.get('name'))
                images = self._parseMovie(fanart_data)
        except HTTPError as e:
            log.debug('Failed getting extra art for %s: %s',
                      (identifier, e))
        except Exception:
            log.error('Failed getting extra art for %s: %s',
                      (identifier, traceback.format_exc()))
            return {}

        return {
            'images': images
        }

    def _parseMovie(self, movie):
        images = {
            'landscape': self._getMultImages(movie.get('moviethumb', []), 1),
            'logo': [],
            'disc_art': self._getMultImages(self._trimDiscs(movie.get('moviedisc', [])), 1),
            'clear_art': self._getMultImages(movie.get('hdmovieart', []), 1),
            'banner': self._getMultImages(movie.get('moviebanner', []), 1),
            'extra_fanart': [],
        }

        if len(images['clear_art']) == 0:
            images['clear_art'] = self._getMultImages(movie.get('movieart', []), 1)

        images['logo'] = self._getMultImages(movie.get('hdmovielogo', []), 1)
        if len(images['logo']) == 0:
            images['logo'] = self._getMultImages(movie.get('movielogo', []), 1)

        fanarts = self._getMultImages(movie.get('moviebackground', []), self.MAX_EXTRAFANART + 1)

        if fanarts:
            images['backdrop_original'] = [fanarts[0]]
            images['extra_fanart'] = fanarts[1:]

        return images

    def _trimDiscs(self, disc_images):
        """
        Return a subset of discImages. Only bluray disc images will be returned.
        """

        trimmed = []
        for disc in disc_images:
            if disc.get('disc_type') == 'bluray':
                trimmed.append(disc)

        if len(trimmed) == 0:
            return disc_images

        return trimmed

    def _getImage(self, images):
        image_url = None
        highscore = -1
        for image in images:
            if tryInt(image.get('likes')) > highscore:
                highscore = tryInt(image.get('likes'))
                image_url = image.get('url') or image.get('href')

        return image_url

    def _getMultImages(self, images, n):
        """
        Chooses the best n images and returns them as a list.
        If n<0, all images will be returned.
        """
        image_urls = []
        pool = []
        for image in images:
            if image.get('lang') == 'en':
                pool.append(image)
        orig_pool_size = len(pool)

        while len(pool) > 0 and (n < 0 or orig_pool_size - len(pool) < n):
            best = None
            highscore = -1
            for image in pool:
                if tryInt(image.get('likes')) > highscore:
                    highscore = tryInt(image.get('likes'))
                    best = image
            url = best.get('url') or best.get('href')
            if url:
                image_urls.append(url)
            pool.remove(best)

        return image_urls

    def isDisabled(self):
        if not self.conf('api_key'):
            # WARNING, not ERROR: fanart.tv requires every install to supply
            # its own free API key -- there is no shared fallback key any
            # more (the one previously baked in here was removed, see
            # docs/technical-debt.md). Running without a key is an expected,
            # recoverable state for installs that haven't configured one yet,
            # not an application fault, so ERROR would misrepresent it and
            # drown genuine failures.
            log.warning(
                'No fanart.tv API key configured -- skipping extra art. Posters '
                'still come from TheMovieDB; this only affects extra artwork '
                '(logos, banners, discs). Get a free key at '
                'https://fanart.tv/get-an-api-key/ and set it in '
                'Settings > General > Fanart.tv.'
            )
            return True
        return False


config = [{
    'name': 'fanarttv',
    'groups': [
        {
            # 'general', NOT 'providers' — and deliberately not `hidden`.
            #
            # This block was first written by copying themoviedb.py's, which uses
            # `tab: 'providers'` + `hidden: True`. That is faithful to the
            # existing pattern and completely unreachable: the new settings UI
            # filters the whole tab out (`hiddenTabs: new Set(['providers',
            # 'automation'])` in partials/settings/scripts.html), so the setting
            # could only be changed by hand-editing config.ini on the server.
            # Shipping a key requirement with no way to enter the key is worse
            # than the public upstream key this replaced.
            #
            # TheMovieDB has the same problem; it is masked there by a baked-in
            # fallback key, which is why nobody noticed. Surfacing the Providers
            # tab properly is the real fix — see docs/technical-debt.md.
            'tab': 'general',
            'name': 'fanarttv',
            'label': 'Fanart.tv',
            'description': 'Optional. Adds extra artwork (logos, banners, discs) '
                            'on top of the posters TheMovieDB already provides. '
                            'Without a key CouchPotato simply skips that extra art. '
                            'Free key from '
                            '<a href="https://fanart.tv/get-an-api-key/" target="_blank" rel="noopener">fanart.tv</a>.',
            'options': [
                {
                    'name': 'api_key',
                    'default': '',
                    'label': 'Api Key',
                },
            ],
        },
    ],
}]
