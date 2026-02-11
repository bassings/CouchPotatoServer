import traceback

from couchpotato.core.helpers.encoding import toUnicode
from couchpotato.core.helpers.variable import getIdentifier
from couchpotato.core.logger import CPLog
from couchpotato.core.notifications.base import Notification


log = CPLog(__name__)

autoload = 'Webhook'

class Webhook(Notification):

    def notify(self, message = '', data = None, listener = None):
        if not data: data = {}

        post_data = {
            'message': toUnicode(message)
        }

        if getIdentifier(data):
            post_data.update({
                'imdb_id': getIdentifier(data)
            })

        headers = {
            'Content-type': 'application/x-www-form-urlencoded'
        }

        try:
            self.urlopen(self.conf('url'), headers = headers, data = post_data, show_error = False)
            return True
        except Exception:
            log.error('Webhook notification failed: %s', traceback.format_exc())

        return False


config = [{
    'name': 'webhook',
    'groups': [
        {
            'tab': 'notifications',
            'list': 'notification_providers',
            'name': 'webhook',
            'label': 'Webhook',
            'options': [
                {
                    'name': 'enabled',
                    'default': 0,
                    'type': 'enabler',
                },
                {
                    'name': 'url',
                    'label': 'Webhook URL',
                    'description': 'URL that receives a JSON POST when movies are snatched or downloaded.',
                },
                {
                    'name': 'on_snatch',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Notify on Snatch',
                    'advanced': True,
                    'description': 'Also notify when a release is snatched.',
                }
            ]
        }
    ]
}]
