from couchpotato.core.logger import CPLog
from couchpotato.core.notifications.base import Notification
import json
import requests

log = CPLog(__name__)
autoload = 'Discord'


class Discord(Notification):
    required_confs = ('webhook_url',)

    def notify(self, message='', data=None, listener=None):
        for key in self.required_confs:
            if not self.conf(key):
                log.warning('Discord notifications are enabled, but '
                            '"{0}" is not specified.'.format(key))
                return False

        data = data or {}
        message = message.strip()

        if self.conf('include_imdb') and 'identifier' in data:
            template = ' http://www.imdb.com/title/{0[identifier]}/'
            message += template.format(data)

        headers = {b"Content-Type": b"application/json"}
        try:
            r = requests.post(self.conf('webhook_url'), data=json.dumps(dict(content=message, username=self.conf('bot_name'), avatar_url=self.conf('avatar_url'), tts=self.conf('discord_tts'))), headers=headers)
            r.status_code
        except Exception as e:
            log.warning('Error Sending Discord response error code: {0}'.format(r.status_code))
            return False
        return True


config = [{
    'name': 'discord',
    'groups': [
        {
            'tab': 'notifications',
            'list': 'notification_providers',
            'name': 'discord',
            'options': [
                {
                    'name': 'enabled',
                    'default': 0,
                    'type': 'enabler',
                },
                {
                    'name': 'webhook_url',
                    'label': 'Webhook URL',
                    'description': 'Discord webhook URL. Create one in your channel\'s Integrations settings.',
                },
                {
                    'name': 'include_imdb',
                    'default': True,
                    'type': 'bool',
                    'label': 'Include IMDB Link',
                    'description': 'Add a link to the movie\'s IMDB page in notifications.',
                },
                {
                    'name': 'bot_name',
                    'label': 'Bot Name',
                    'description': 'Display name for the webhook bot.',
                    'default': 'CouchPotato',
                    'advanced': True,
                },
                {
                    'name': 'avatar_url',
                    'label': 'Avatar URL',
                    'description': 'URL to an image used as the bot avatar.',
                    'default': 'https://raw.githubusercontent.com/bassings/CouchPotatoServer/master/couchpotato/static/images/logo.png',
                    'advanced': True,
                },
                {
                    'name': 'discord_tts',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Text-to-Speech',
                    'advanced': True,
                    'description': 'Send notifications using Discord TTS.',
                },
                {
                    'name': 'on_snatch',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Notify on Snatch',
                    'advanced': True,
                    'description': 'Also send message when movie is snatched.',
                },
            ],
        }
    ],
}]
