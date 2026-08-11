"""T17 follow-up D (python:S113): `Discord.notify` calls `requests.post`
with no timeout -- the same defect class as the Synology fix, and found by
the same rule once it was wired into the gate (`pyproject.toml`'s
`extend-select`).

Reachable on every real notification: `Notification.listen_to` includes
`movie.snatched` and `movie.downloaded`, both genuine event producers, and
dispatch is synchronous on the caller's thread. An unresponsive Discord host
parks that thread indefinitely.

30s, not Synology's 60s: this call carries a short JSON payload, not a file
upload, so the house default (Plugin.urlopen, rtorrent_.py's _RPC_TIMEOUT)
applies.
"""
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


class TestDiscordNotificationTimeout:
    """Assert on the actual value reaching requests.post, not merely that
    the kwarg is present -- a presence-only check cannot tell 30 from 0."""

    def test_notify_passes_the_named_timeout_constant(self):
        notifier = Discord.__new__(Discord)

        mock_response = MagicMock(status_code = 204)
        with patch.object(notifier, 'conf', side_effect = _conf()), \
             patch.object(discord_module.requests, 'post', return_value = mock_response) as mock_post:
            notifier.notify(message = 'a movie was snatched')

        assert mock_post.call_args.kwargs['timeout'] == discord_module._REQUEST_TIMEOUT
        assert mock_post.call_args.kwargs['timeout'] == 30

    def test_timeout_constant_matches_house_default(self):
        assert discord_module._REQUEST_TIMEOUT == 30
