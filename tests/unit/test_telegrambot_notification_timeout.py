"""T17 follow-up D (python:S113): `TelegramBot.notify` calls `requests.post`
with no timeout -- same defect class as the Synology and Discord fixes,
found by the same rule once it was wired into the gate.

Reachable on every real notification: `Notification.listen_to` includes
`movie.snatched` and `movie.downloaded`, both genuine event producers, and
dispatch is synchronous on the caller's thread. An unresponsive Telegram
host parks that thread indefinitely.

30s, not Synology's 60s: this call carries a short JSON payload, not a file
upload, so the house default (Plugin.urlopen, rtorrent_.py's _RPC_TIMEOUT)
applies.
"""
from unittest.mock import MagicMock, patch

from couchpotato.core.notifications import telegrambot as telegrambot_module
from couchpotato.core.notifications.telegrambot import TelegramBot


def _conf(**overrides):
    values = {'bot_token': 'FAKE:TOKEN', 'receiver_user_id': '12345'}
    values.update(overrides)
    return lambda k, **kw: values.get(k, kw.get('default', ''))


class TestTelegramBotNotificationTimeout:
    """Assert on the actual value reaching requests.post, not merely that
    the kwarg is present -- a presence-only check cannot tell 30 from 0."""

    def test_notify_passes_the_named_timeout_constant(self):
        notifier = TelegramBot.__new__(TelegramBot)

        mock_response = MagicMock(status_code = 200, text = 'ok')
        with patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(telegrambot_module.requests, 'post', return_value = mock_response) as mock_post:
            notifier.notify(message = 'a movie was snatched', data = {})

        assert mock_post.call_args.kwargs['timeout'] == telegrambot_module._REQUEST_TIMEOUT
        assert mock_post.call_args.kwargs['timeout'] == 30

    def test_timeout_constant_matches_house_default(self):
        assert telegrambot_module._REQUEST_TIMEOUT == 30
