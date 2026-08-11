"""T17 review finding 1 (2026-08-11): `Discord.notify`'s except block
referenced `r.status_code` to build its warning message, but `r` is only
assigned if `requests.post` returns -- exactly the branch the S113 timeout
fix (this branch, `_REQUEST_TIMEOUT`) made reachable. Before that fix, an
unresponsive host just hung the thread forever, silently; after it, the
same host raises `requests.exceptions.Timeout`, `r = requests.post(...)`
never completes, and the except block's own
`'...'.format(r.status_code)` raises:

    UnboundLocalError: cannot access local variable 'r' where it is not
    associated with a value

That crashes while building the log message, so the intended
`log.warning(...)` never fires and `notify()` never returns False -- the
graceful failure this whole try/except exists to produce. `fireEvent`'s
per-handler try/except catches the UnboundLocalError so the app itself
does not crash, but the caller sees a confusing traceback about a local
variable instead of the module's own diagnostic, and the timeout fix made
this reliably reachable on the one path it targeted.

Fix: log the caught exception `e`, not the response that was never
assigned.
"""
import logging

import requests
from unittest.mock import MagicMock, patch

from couchpotato.core.notifications import discord as discord_module
from couchpotato.core.notifications.discord import Discord


def _conf(**overrides):
    values = {
        'webhook_url': 'https://discord.example/api/webhooks/x/y',
        'bot_name': 'CouchPotato',
        'avatar_url': 'https://example.invalid/avatar.png',
        'discord_tts': False,
        'include_imdb': False,
    }
    values.update(overrides)
    return lambda k, **kw: values.get(k, kw.get('default', ''))


class TestDiscordNotifyExceptionPath:

    def test_a_request_exception_returns_false_without_raising(self):
        """The exact scenario the timeout fix made reachable: requests.post
        raises before `r` is ever assigned. notify() must catch this and
        return False, not raise UnboundLocalError."""
        notifier = Discord.__new__(Discord)

        with patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(discord_module.requests, 'post',
                          side_effect = requests.exceptions.Timeout('timed out')):
            result = notifier.notify(message = 'a movie was snatched')

        assert result is False

    def test_a_request_exception_logs_the_exception_not_a_missing_response(self, caplog):
        notifier = Discord.__new__(Discord)

        with caplog.at_level(logging.WARNING), \
             patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(discord_module.requests, 'post',
                          side_effect = requests.exceptions.Timeout('timed out')):
            notifier.notify(message = 'a movie was snatched')

        records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(records) == 1, 'exactly one warning must be logged, not a raised UnboundLocalError'
        assert 'timed out' in records[0].getMessage(), (
            'the warning must describe the actual exception, not a missing response object'
        )

    def test_the_204_success_path_still_works(self):
        """Sanity check: the fix to the except block must not disturb the
        existing success path."""
        notifier = Discord.__new__(Discord)

        mock_response = MagicMock(status_code = 204)
        with patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(discord_module.requests, 'post', return_value = mock_response):
            result = notifier.notify(message = 'a movie was snatched')

        assert result is True
