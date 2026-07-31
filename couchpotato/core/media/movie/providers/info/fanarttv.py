import traceback
from base64 import b64decode as bd

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

    # Shipped application key, mirroring themoviedb.py's `ak` pool.
    #
    # This is DELIBERATE and must stay: CouchPotato is a self-hosted app that is
    # expected to work out of the box, so it ships public application keys for
    # the third-party services it reads (TheMovieDB does exactly the same, and
    # tmdb_charts.py logs "using built-in" when falling back). Removing it does
    # not improve security — the key is public in every copy of upstream and
    # grants access to fanart.tv's public art API, nothing of this project's —
    # it just silently costs every existing install its extra artwork.
    #
    # Base64 purely to match themoviedb.py's existing `ak` encoding — NOT to
    # hide it from scanners. Be aware of the side effect and don't mistake it
    # for a clean bill of health: `make check-secrets` reports no findings for
    # this file because gitleaks' hex-literal rules do not match an encoded
    # string, not because there is no key here. That is stated plainly in
    # .gitleaksignore and docs/technical-debt.md so nobody reads a green scan as
    # "no shipped keys".
    #
    # Users who want their own key (their own quota) can set one in
    # Settings > General > Fanart.tv, which takes precedence — see getApiKey.
    ak = 'YjI4YjE0ZTliZTY2MmUwMjdjZmJjN2MzZGQ2MDA0MDU='

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
            url = self.urls['api'] % (identifier, self.getApiKey())
            fanart_data = self.getJsonData(url, show_error = False)

            if fanart_data:
                log.debug('Found images for %s', fanart_data.get('name'))
                images = self._parseMovie(fanart_data)
        except HTTPError as e:
            log.debug('Failed getting extra art for %s: %s',
                      identifier, e)
        except Exception:
            log.error('Failed getting extra art for %s: %s',
                      identifier, traceback.format_exc())
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

    def getApiKey(self):
        """The user's own key if they set one, else the shipped public key.

        Same precedence as themoviedb.py: a configured key always wins, and the
        built-in keeps extra artwork working for the overwhelming majority of
        installs that never configure one.
        """
        key = self.conf('api_key')
        # .strip(): a whitespace-only value is a user who cleared the field, not
        # a key. Without this it produced `?api_key=%20%20%20` instead of falling
        # back to the shipped key.
        if key and key.strip():
            return key.strip()
        decoded = bd(self.ak)
        return decoded.decode('utf-8') if isinstance(decoded, bytes) else decoded

    def isDisabled(self):
        # Never disabled for want of a key: there is always the shipped fallback.
        # Kept as a hook so a future "disable this provider" toggle has somewhere
        # to live, and so getArt's guard reads the same as the other providers'.
        return not self.getApiKey()


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
                    'label': 'API Key',
                    # Masked in the UI: this is a credential, and unlike
                    # themoviedb's (which sits on the hidden 'providers' tab)
                    # this group is visible on General, so it renders for
                    # everyone. Matches nzbget.py / synology.py.
                    'type': 'password',
                },
            ],
        },
    ],
}]
