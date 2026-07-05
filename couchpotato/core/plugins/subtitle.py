import os
import traceback

from babelfish import Language
import subliminal

from couchpotato.core.event import addEvent
from couchpotato.core.helpers.encoding import toUnicode, sp
from couchpotato.core.helpers.variable import splitString
from couchpotato.core.logger import CPLog
from couchpotato.core.plugins.base import Plugin
from couchpotato.environment import Env


log = CPLog(__name__)

autoload = 'Subtitle'


class Subtitle(Plugin):

    # Movie-relevant providers. opensubtitles.org's legacy XML-RPC API is
    # deprecated in favor of opensubtitles.com's REST API (opensubtitlescom),
    # which is listed first and kept usable even without an account.
    providers = ['opensubtitlescom', 'podnapisi', 'opensubtitles']

    def __init__(self):
        addEvent('renamer.before', self.searchSingle)
        self.configureCache()

    def configureCache(self):
        """Configure subliminal's dogpile.cache region exactly once per process.

        `region.configure()` raises `RegionAlreadyConfigured` if called twice,
        which would otherwise happen every time this plugin is reloaded.
        """
        if subliminal.region.is_configured:
            return

        try:
            cache_file = sp(os.path.join(Env.get('cache_dir'), 'subliminal.dbm'))
            subliminal.region.configure('dogpile.cache.dbm', arguments = {'filename': cache_file})
        except Exception:
            log.error('Failed configuring subliminal cache: %s', traceback.format_exc())

    def searchSingle(self, group):
        if self.isDisabled(): return

        try:
            wanted_languages = self.getLanguageObjects()
            if not wanted_languages:
                return True

            available_languages = set(sum(group['subtitle_language'].values(), []))
            force = self.conf('force')

            files = [toUnicode(x) for x in group['files']['movie']]
            log.debug('Searching for subtitles for: %s', files)

            provider_configs = self.getProviderConfigs()

            for filename in files:
                languages = wanted_languages if force else {
                    lang for lang in wanted_languages if lang.alpha2 not in available_languages
                }

                if not languages:
                    continue

                video = self.scanVideo(filename)
                if video is None:
                    continue

                try:
                    subtitles = subliminal.download_best_subtitles(
                        {video}, languages,
                        providers = self.providers,
                        provider_configs = provider_configs,
                    )
                except Exception:
                    log.error('Failed downloading subtitles for %s: %s', filename, traceback.format_exc())
                    continue

                found = subtitles.get(video) or []
                if not found:
                    continue

                try:
                    saved = subliminal.save_subtitles(video, found)
                except Exception:
                    log.error('Failed saving subtitles for %s: %s', filename, traceback.format_exc())
                    continue

                for subtitle in saved:
                    sub_path = sp(subtitle.get_path(video))
                    log.info('Found subtitle (%s): %s', subtitle.language.alpha2, filename)
                    group['files']['subtitle'].append(sub_path)
                    group['before_rename'].append(sub_path)
                    group['subtitle_language'][sub_path] = [subtitle.language.alpha2]

            return True

        except Exception:
            log.error('Failed searching for subtitle: %s', traceback.format_exc())

        return False

    def scanVideo(self, filename):
        """Build a subliminal `Video` for `filename`.

        Prefers `scan_video`, which uses guessit plus the file on disk and
        never itself requires libmediainfo. Falls back to name-only
        `Video.fromname` for anything that stops `scan_video` from working
        (missing file, unreadable path, unexpected error, ...) so a single bad
        file never crashes the whole search.
        """
        try:
            return subliminal.scan_video(filename)
        except Exception:
            log.debug('Falling back to name-based video scan for %s: %s', filename, traceback.format_exc())

        try:
            return subliminal.Video.fromname(os.path.basename(filename))
        except Exception:
            log.error('Failed building subtitle video for %s: %s', filename, traceback.format_exc())
            return None

    def getLanguages(self):
        return splitString(self.conf('languages'))

    def getLanguageObjects(self):
        languages = set()
        for code in self.getLanguages():
            code = code.strip()
            if not code:
                continue
            try:
                languages.add(Language.fromalpha2(code.lower()))
            except Exception:
                log.error('Invalid subtitle language code %r: %s', code, traceback.format_exc())
        return languages

    def getProviderConfigs(self):
        """Build subliminal's `provider_configs`, wiring in optional OpenSubtitles.com creds.

        opensubtitlescom works anonymously (subliminal ships a default public
        API key), so the username/password are entirely optional; when both
        are set they raise the search/download quota on opensubtitles.com.
        """
        configs = {}

        username = self.conf('opensubtitles_com_user')
        password = self.conf('opensubtitles_com_password')
        if username and password:
            configs['opensubtitlescom'] = {'username': username, 'password': password}

        return configs


config = [{
    'name': 'subtitle',
    'groups': [
        {
            'tab': 'renamer',
            'name': 'subtitle',
            'label': 'Download subtitles',
            'description': 'after rename',
            'options': [
                {
                    'name': 'enabled',
                    'label': 'Search and download subtitles',
                    'default': False,
                    'type': 'enabler',
                },
                {
                    'name': 'languages',
                    'description': ('Comma separated, 2 letter country code.', 'Example: en, nl. See the codes at <a href="http://en.wikipedia.org/wiki/List_of_ISO_639-1_codes" target="_blank">on Wikipedia</a>'),
                },
                {
                    'advanced': True,
                    'name': 'force',
                    'label': 'Force',
                    'description': ('Force download all languages (including embedded).', 'This will also <strong>overwrite</strong> all existing subtitles.'),
                    'default': False,
                    'type': 'bool',
                },
                {
                    'advanced': True,
                    'name': 'opensubtitles_com_user',
                    'label': 'OpenSubtitles.com username',
                    'description': ('Optional. Raises the search/download quota on <a href="https://www.opensubtitles.com" target="_blank">opensubtitles.com</a>.', 'The legacy opensubtitles.org XML-RPC API is deprecated in favor of this REST API; anonymous searches still work without an account.'),
                },
                {
                    'advanced': True,
                    'name': 'opensubtitles_com_password',
                    'label': 'OpenSubtitles.com password',
                    'type': 'password',
                },
            ],
        },
    ],
}]
