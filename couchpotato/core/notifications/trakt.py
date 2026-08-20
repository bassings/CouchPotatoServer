from couchpotato.core.helpers.variable import getTitle, getIdentifier
from couchpotato.core.logger import CPLog
from couchpotato.core.media.movie.providers.automation.trakt.main import TraktBase
from couchpotato.core.notifications.base import Notification

log = CPLog(__name__)

autoload = 'Trakt'


class Trakt(Notification, TraktBase):
    """Trakt notification provider - adds movies to your collection and removes from watchlist.

    Uses the OAuth credentials configured in the Trakt automation settings.
    """

    urls = {
        'library': 'sync/collection',
        'unwatchlist': 'sync/watchlist/remove',
        'test': 'sync/last_activities',
    }

    listen_to = ['renamer.after']
    enabled_option = 'notification_enabled'

    # T53: no `conf()` override here any more. This class and the automation
    # provider (`.../automation/trakt/main.py`) both declare their plugin
    # `config` under the SAME top-level entry name, `'trakt'` -- see that
    # module's `config[0]['name']` and this file's own, below -- and
    # `Plugin.conf()`'s default section is `self.getName().lower()`, which is
    # `'trakt'` for this class too (nothing calls `setName` on it). So the
    # inherited `Plugin.conf()` already reads the OAuth credentials the
    # automation module writes; a previous version of this method
    # deliberately redirected `automation_client_id` and friends to section
    # `'trakt_automation'`, which is the automation module's GROUP name, not
    # its entry name -- `loader.py` never registers anything under a group
    # name -- so every read there came back `''` and this notifier could
    # never authorise.

    def notify(self, message='', data=None, listener=None):
        if not data:
            data = {}

        if listener == 'test':
            # Check if credentials are configured
            if not self.get_client_id():
                log.warning('Trakt Client ID not configured in automation settings')
                return False
            if not self.conf('automation_oauth_token'):
                log.warning('Trakt not authorized. Authorize in the Automation tab first.')
                return False

            result = self.call(self.urls['test'])
            return bool(result)

        else:
            # Add to collection
            post_data = {
                'movies': [{'ids': {'imdb': getIdentifier(data)}}] if data else []
            }

            result = self.call((self.urls['library']), post_data)
            if self.conf('remove_watchlist_enabled'):
                result = result and self.call((self.urls['unwatchlist']), post_data)

            return result


config = [{
    'name': 'trakt',
    'groups': [
        {
            'tab': 'notifications',
            'list': 'notification_providers',
            'name': 'trakt',
            'label': 'Trakt',
            'description': 'Add movies to your Trakt collection once downloaded. Configure credentials in the Automation tab.',
            'options': [
                {
                    'name': 'notification_enabled',
                    'default': False,
                    'type': 'enabler',
                },
                {
                    'name': 'remove_watchlist_enabled',
                    'label': 'Remove from watchlist',
                    'default': False,
                    'type': 'bool',
                    'description': 'Remove movies from your Trakt watchlist after adding to collection.',
                },
            ],
        }
    ],
}]
