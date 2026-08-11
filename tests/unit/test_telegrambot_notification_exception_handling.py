"""T17 review finding 2 (2026-08-11): `TelegramBot.notify` had no
try/except around its `requests.post` call at all -- lower severity than
Discord's finding 1 (same underlying cause), but the same shape: the
`ReadTimeout`/`ConnectionError` the S113 timeout fix (`_REQUEST_TIMEOUT`)
makes reachable against an unresponsive host now propagates UNCAUGHT out
of `notify()`, instead of the module logging its own diagnostic. That
surfaces as a generic "Failed running event handler" traceback rather than
the `log.error('Could not send notification to TelegramBot...')` line this
module already has for the wrong-status-code case.

Consistency matters here: all three downloaders/notifiers touched by T17
(Synology, Discord, Telegram) now share the S113 timeout fix, so all three
must handle the timeout it makes reachable the same way -- caught, logged,
`notify()` returns False.
"""
import logging

import requests
from unittest.mock import patch

from couchpotato.core.notifications import telegrambot as telegrambot_module
from couchpotato.core.notifications.telegrambot import TelegramBot


def _conf(**overrides):
    values = {'bot_token': 'FAKE:TOKEN', 'receiver_user_id': '12345'}
    values.update(overrides)
    return lambda k, **kw: values.get(k, kw.get('default', ''))


class TestTelegramBotNotifyExceptionPath:

    def test_a_request_exception_returns_false_without_raising(self):
        notifier = TelegramBot.__new__(TelegramBot)

        with patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(telegrambot_module.requests, 'post',
                          side_effect = requests.exceptions.ReadTimeout('timed out')):
            result = notifier.notify(message = 'a movie was snatched', data = {})

        assert result is False

    def test_a_request_exception_is_logged_by_this_module_not_left_uncaught(self, caplog):
        notifier = TelegramBot.__new__(TelegramBot)

        with caplog.at_level(logging.ERROR), \
             patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(telegrambot_module.requests, 'post',
                          side_effect = requests.exceptions.ReadTimeout('timed out')):
            notifier.notify(message = 'a movie was snatched', data = {})

        records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(records) == 1, 'exactly one error must be logged, not left to propagate uncaught'
        assert 'timed out' in records[0].getMessage()

    def test_the_200_success_path_still_works(self):
        """Sanity check: wrapping the call in try/except must not disturb
        the existing success path."""
        notifier = TelegramBot.__new__(TelegramBot)

        class _FakeResponse:
            status_code = 200
            text = 'ok'

        with patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(telegrambot_module.requests, 'post', return_value = _FakeResponse()):
            result = notifier.notify(message = 'a movie was snatched', data = {})

        assert result is True

    def test_the_non_200_status_path_still_works(self, caplog):
        """Sanity check: the pre-existing wrong-status-code branch (a
        DIFFERENT failure mode from a raised exception) must be untouched."""
        notifier = TelegramBot.__new__(TelegramBot)

        class _FakeResponse:
            status_code = 403
            text = 'forbidden'

        with caplog.at_level(logging.ERROR), \
             patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(telegrambot_module.requests, 'post', return_value = _FakeResponse()):
            result = notifier.notify(message = 'a movie was snatched', data = {})

        assert result is False
        records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(records) == 1
        assert 'forbidden' in records[0].getMessage()
