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

    def conf(self, attr, *args, **kwargs):
        """Override conf to read OAuth credentials from automation settings."""
        # These settings are shared with the automation module
        shared_settings = ['automation_client_id', 'automation_client_secret', 
                          'automation_oauth_token', 'automation_oauth_refresh']
        
        if attr in shared_settings:
            # Read from the automation config section
            from couchpotato.environment import Env
            value = Env.setting(attr, 'trakt_automation')
            return value
        
        return super(Trakt, self).conf(attr, *args, **kwargs)

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
