import json
from couchpotato.core.logger import CPLog
from couchpotato.core.notifications.base import Notification

log = CPLog(__name__)
autoload = 'Slack'


class Slack(Notification):
    url = 'https://slack.com/api/chat.postMessage'
    required_confs = ('token', 'channels',)

    def notify(self, message='', data=None, listener=None):
        for key in self.required_confs:
            if not self.conf(key):
                log.warning('Slack notifications are enabled, but '
                            '"{0}" is not specified.'.format(key))
                return False

        data = data or {}
        message = message.strip()

        if self.conf('include_imdb') and 'identifier' in data:
            template = ' http://www.imdb.com/title/{0[identifier]}/'
            message += template.format(data)

        payload = {
            'token': self.conf('token'),
            'text': message,
            'username': self.conf('bot_name'),
            'unfurl_links': self.conf('include_imdb'),
            'as_user': self.conf('as_user'),
            'icon_url': self.conf('icon_url'),
            'icon_emoji': self.conf('icon_emoji')
        }

        channels = self.conf('channels').split(',')
        for channel in channels:
            payload['channel'] = channel.strip()
            response = self.urlopen(self.url, data=payload)
            response = json.loads(response)
            if not response['ok']:
                log.warning('Notification sending to Slack has failed. Error '
                            'code: %s.', response['error'])
                return False
        return True


config = [{
    'name': 'slack',
    'groups': [
        {
            'tab': 'notifications',
            'list': 'notification_providers',
            'name': 'slack',
            'label': 'Slack',
            'options': [
                {
                    'name': 'enabled',
                    'default': 0,
                    'type': 'enabler',
                },
                {
                    'name': 'token',
                    'label': 'Bot Token',
                    'description': 'Slack bot or user token. Create one at <a href="https://api.slack.com/apps" target="_blank">api.slack.com</a>.',
                },
                {
                    'name': 'channels',
                    'label': 'Channel',
                    'description': 'Channel name (e.g. #movies) or ID. Separate multiple with commas.',
                },
                {
                    'name': 'include_imdb',
                    'default': True,
                    'type': 'bool',
                    'label': 'Include IMDB Link',
                    'description': 'Add a link to the movie\'s IMDB page.',
                },
                {
                    'name': 'bot_name',
                    'label': 'Bot Name',
                    'description': 'Display name for the bot.',
                    'default': 'CouchPotato',
                    'advanced': True,
                },
                {
                    'name': 'as_user',
                    'label': 'Send as User',
                    'description': 'Post as the token owner instead of the bot.',
                    'default': False,
                    'type': 'bool',
                    'advanced': True
                },
                {
                    'name': 'icon_url',
                    'label': 'Icon URL',
                    'description': 'URL for the bot\'s avatar image.',
                    'advanced': True,
                },
                {
                    'name': 'icon_emoji',
                    'label': 'Icon Emoji',
                    'description': 'Emoji for the bot icon (e.g. :movie_camera:). Overrides Icon URL.',
                    'advanced': True,
                },
                {
                    'name': 'on_snatch',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Notify on Snatch',
                    'advanced': True,
                    'description': 'Also notify when a release is snatched.',
                },
            ],
        }
    ],
}]
