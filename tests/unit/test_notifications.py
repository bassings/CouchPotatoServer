"""Task 18: Notification tests — Pushover, Telegram, Discord, Webhook.

Uses unittest.mock to avoid real outbound HTTP.
"""
import json
import os
import sys
import threading
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from couchpotato.environment import Env


@pytest.fixture(autouse=True)
def setup_env():
    Env.set('appname', 'CouchPotato')
    Env.set('dev', False)
    yield


def _make_notification(cls_path, cls_name):
    """Create a notification instance without triggering __init__."""
    import importlib
    with patch('couchpotato.core.event.addEvent'), \
         patch('couchpotato.api.addApiView', create=True), \
         patch('couchpotato.core._base.downloader.main.addApiView', create=True), \
         patch('couchpotato.core.notifications.base.addApiView', create=True):
        mod = importlib.import_module(cls_path)
        klass = getattr(mod, cls_name)
        inst = klass.__new__(klass)
        inst._running = []
        inst._running_lock = threading.Lock()
        inst._locks = {}
        inst._http_client = None
        inst._needs_shutdown = False
        inst.http_time_between_calls = 0
        inst.ssl_verify = True
        return inst


# ===========================================================================
# Pushover
# ===========================================================================

class TestPushover:

    def _make(self):
        p = _make_notification('couchpotato.core.notifications.pushover', 'Pushover')
        p.api_url = 'https://api.pushover.net'
        return p

    def test_notify_success(self):
        p = self._make()
        with patch.object(p, 'conf', side_effect=lambda k, **kw: {
            'user_key': 'userkey123', 'api_token': 'apptoken456',
            'priority': 0, 'sound': 'pushover'
        }.get(k, kw.get('default', ''))), \
             patch.object(p, 'urlopen', return_value=b'{"status":1}') as mock_url:
            result = p.notify(message='Movie downloaded!', data={})

        assert result is True
        mock_url.assert_called_once()
        call_kwargs = mock_url.call_args
        assert '1/messages.json' in call_kwargs[0][0]
        assert call_kwargs[1]['data']['message'] == 'Movie downloaded!'

    def test_notify_with_imdb_data(self):
        p = self._make()
        data = {'identifier': 'tt1375666', 'info': {'titles': ['Inception']}}
        with patch.object(p, 'conf', side_effect=lambda k, **kw: {
            'user_key': 'u', 'api_token': 't', 'priority': 0, 'sound': ''
        }.get(k, kw.get('default', ''))), \
             patch.object(p, 'urlopen', return_value=b'{"status":1}') as mock_url, \
             patch('couchpotato.core.notifications.pushover.getIdentifier', return_value='tt1375666'), \
             patch('couchpotato.core.notifications.pushover.getTitle', return_value='Inception'):
            result = p.notify(message='Snatched!', data=data)

        assert result is True
        post_data = mock_url.call_args[1]['data']
        assert 'imdb.com' in post_data.get('url', '')

    def test_notify_failure(self):
        p = self._make()
        with patch.object(p, 'conf', side_effect=lambda k, **kw: {
            'user_key': 'u', 'api_token': 't', 'priority': 0, 'sound': ''
        }.get(k, kw.get('default', ''))), \
             patch.object(p, 'urlopen', side_effect=Exception('Connection failed')):
            result = p.notify(message='test')

        assert result is False


# ===========================================================================
# Telegram
# ===========================================================================

class TestTelegram:

    def _make(self):
        return _make_notification('couchpotato.core.notifications.telegrambot', 'TelegramBot')

    def test_notify_success(self):
        t = self._make()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch.object(t, 'conf', side_effect=lambda k, **kw: {
            'bot_token': '123:ABC', 'receiver_user_id': '456'
        }.get(k, kw.get('default', ''))), \
             patch('couchpotato.core.notifications.telegrambot.requests.post', return_value=mock_resp) as mock_post:
            result = t.notify(message='Movie available!')

        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert '123:ABC' in call_args[0][0]
        assert call_args[1]['data']['chat_id'] == '456'
        assert call_args[1]['data']['text'] == 'Movie available!'

    def test_notify_with_imdb(self):
        t = self._make()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        data = {'identifier': 'tt1375666'}
        with patch.object(t, 'conf', side_effect=lambda k, **kw: {
            'bot_token': '123:ABC', 'receiver_user_id': '456'
        }.get(k, kw.get('default', ''))), \
             patch('couchpotato.core.notifications.telegrambot.requests.post', return_value=mock_resp) as mock_post, \
             patch('couchpotato.core.notifications.telegrambot.getIdentifier', return_value='tt1375666'):
            result = t.notify(message='Snatched!', data=data)

        assert result is True
        text = mock_post.call_args[1]['data']['text']
        assert 'imdb.com' in text

    def test_notify_failure(self):
        t = self._make()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = 'Forbidden'

        with patch.object(t, 'conf', side_effect=lambda k, **kw: {
            'bot_token': 'bad', 'receiver_user_id': '456'
        }.get(k, kw.get('default', ''))), \
             patch('couchpotato.core.notifications.telegrambot.requests.post', return_value=mock_resp):
            result = t.notify(message='test')

        assert result is False


# ===========================================================================
# Discord
# ===========================================================================

class TestDiscord:

    def _make(self):
        return _make_notification('couchpotato.core.notifications.discord', 'Discord')

    def test_notify_success(self):
        d = self._make()
        mock_resp = MagicMock()
        mock_resp.status_code = 204

        with patch.object(d, 'conf', side_effect=lambda k, **kw: {
            'webhook_url': 'https://discord.com/api/webhooks/123/abc',
            'include_imdb': False, 'bot_name': 'CouchPotato',
            'avatar_url': '', 'discord_tts': False
        }.get(k, kw.get('default', ''))), \
             patch('couchpotato.core.notifications.discord.requests.post', return_value=mock_resp) as mock_post:
            result = d.notify(message='Movie downloaded!')

        assert result is True
        mock_post.assert_called_once()
        payload = json.loads(mock_post.call_args[1]['data'])
        assert payload['content'] == 'Movie downloaded!'
        assert payload['username'] == 'CouchPotato'

    def test_notify_with_imdb(self):
        d = self._make()
        mock_resp = MagicMock()
        mock_resp.status_code = 204

        with patch.object(d, 'conf', side_effect=lambda k, **kw: {
            'webhook_url': 'https://discord.com/api/webhooks/123/abc',
            'include_imdb': True, 'bot_name': 'CP',
            'avatar_url': '', 'discord_tts': False
        }.get(k, kw.get('default', ''))), \
             patch('couchpotato.core.notifications.discord.requests.post', return_value=mock_resp) as mock_post:
            result = d.notify(message='Snatched!', data={'identifier': 'tt1375666'})

        assert result is True
        payload = json.loads(mock_post.call_args[1]['data'])
        assert 'imdb.com' in payload['content']

    def test_notify_missing_webhook(self):
        d = self._make()
        with patch.object(d, 'conf', side_effect=lambda k, **kw: {
            'webhook_url': '', 'include_imdb': False, 'bot_name': '',
            'avatar_url': '', 'discord_tts': False
        }.get(k, kw.get('default', ''))):
            result = d.notify(message='test')

        assert result is False

    def test_notify_connection_error(self):
        """Discord notifier has a bug: UnboundLocalError on 'r' when requests.post raises.
        This test documents the bug — it raises instead of returning False."""
        d = self._make()
        with patch.object(d, 'conf', side_effect=lambda k, **kw: {
            'webhook_url': 'https://discord.com/api/webhooks/123/abc',
            'include_imdb': False, 'bot_name': 'CP',
            'avatar_url': '', 'discord_tts': False
        }.get(k, kw.get('default', ''))), \
             patch('couchpotato.core.notifications.discord.requests.post', side_effect=Exception('timeout')):
            with pytest.raises(UnboundLocalError):
                d.notify(message='test')


# ===========================================================================
# Webhook
# ===========================================================================

class TestWebhook:

    def _make(self):
        return _make_notification('couchpotato.core.notifications.webhook', 'Webhook')

    def test_notify_success(self):
        w = self._make()
        with patch.object(w, 'conf', return_value='http://example.com/hook'), \
             patch.object(w, 'urlopen', return_value=b'ok') as mock_url:
            result = w.notify(message='Movie ready!')

        assert result is True
        mock_url.assert_called_once()
        call_kwargs = mock_url.call_args
        assert call_kwargs[1]['data']['message'] == 'Movie ready!'

    def test_notify_with_imdb_id(self):
        w = self._make()
        data = {'identifier': 'tt1375666'}

        with patch.object(w, 'conf', return_value='http://example.com/hook'), \
             patch.object(w, 'urlopen', return_value=b'ok') as mock_url, \
             patch('couchpotato.core.notifications.webhook.getIdentifier', return_value='tt1375666'):
            result = w.notify(message='Snatched!', data=data)

        assert result is True
        post_data = mock_url.call_args[1]['data']
        assert post_data['imdb_id'] == 'tt1375666'

    def test_notify_failure(self):
        w = self._make()
        with patch.object(w, 'conf', return_value='http://example.com/hook'), \
             patch.object(w, 'urlopen', side_effect=Exception('Connection refused')):
            result = w.notify(message='test')

        assert result is False

    def test_notify_payload_format(self):
        w = self._make()
        with patch.object(w, 'conf', return_value='http://example.com/hook'), \
             patch.object(w, 'urlopen', return_value=b'ok') as mock_url:
            w.notify(message='Test message')

        call_kwargs = mock_url.call_args[1]
        assert call_kwargs['headers']['Content-type'] == 'application/x-www-form-urlencoded'
        assert 'message' in call_kwargs['data']
