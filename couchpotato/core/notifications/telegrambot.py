from couchpotato.core.helpers.variable import getIdentifier
from couchpotato.core.logger import CPLog
from couchpotato.core.notifications.base import Notification
import requests

log = CPLog(__name__)

autoload = 'TelegramBot'

# python:S113 -- requests.post with no timeout can hang the calling thread
# forever against an unresponsive Telegram host. 30s (the house default:
# Plugin.urlopen, rtorrent_.py's _RPC_TIMEOUT), not Synology's longer 60s --
# this carries a short JSON payload, not a file upload.
_REQUEST_TIMEOUT = 30

class TelegramBot(Notification):

    TELEGRAM_API = "https://api.telegram.org/bot%s/%s"

    def notify(self, message = '', data = None, listener = None):
        if not data: data = {}

        # Get configuration data
        token = self.conf('bot_token')
        usr_id = self.conf('receiver_user_id')

        # Add IMDB url to message:
        if data:
            imdb_id = getIdentifier(data)
            if imdb_id:
                url = 'http://www.imdb.com/title/{0}/'.format(imdb_id)
                message = '{0}\n{1}'.format(message, url)

        # Cosntruct message
        payload = {'chat_id': usr_id, 'text': message, 'parse_mode': 'Markdown'}

        # Send message user Telegram's Bot API. Wrapped: an unresponsive
        # host raises (ReadTimeout, ConnectionError, ...), which the S113
        # timeout fix above made reachable -- uncaught, that propagates out
        # of notify() as a generic "Failed running event handler" traceback
        # instead of this module's own diagnostic.
        try:
            response = requests.post(self.TELEGRAM_API % (token, "sendMessage"), data=payload, timeout=_REQUEST_TIMEOUT)
        except Exception as e:
            log.error('Could not send notification to TelegramBot (token=%s): %s', token, e)
            return False

        # Error logging
        sent_successfuly = True
        if not response.status_code == 200:
            log.error('Could not send notification to TelegramBot (token=%s). Response: [%s]', token, response.text)
            sent_successfuly = False

        return sent_successfuly


config = [{
    'name': 'telegrambot',
    'groups': [
        {
            'tab': 'notifications',
            'list': 'notification_providers',
            'name': 'telegrambot',
            'label': 'Telegram',
            'description': 'Send notifications via a Telegram bot.',
            'options': [
                {
                    'name': 'enabled',
                    'default': 0,
                    'type': 'enabler',
                },
                {
                    'name': 'bot_token',
                    'type': 'password',
                    'label': 'Bot Token',
                    'description': 'Get one from <a href="http://telegram.me/BotFather" target="_blank">@BotFather</a> on Telegram.',
                },
                {
                    'name': 'receiver_user_id',
                    'label': 'Chat ID',
                    'description': 'User or group ID to send notifications to. Use <a href="http://telegram.me/myidbot" target="_blank">@myidbot</a> to find yours.',
                },
                {
                    'name': 'on_snatch',
                    'default': 0,
                    'type': 'bool',
                    'label': 'Notify on Snatch',
                    'advanced': True,
                    'description': 'Also notify when a release is snatched (not just downloaded).',
                },
            ],
        }
    ],
}]
