"""Python 2 leftovers in the Plex notification server.

Two latent crashes, both in the plex.tv token-fetch path and both inside
error handling — so they replaced a real diagnostic with a confusing one at
exactly the moment someone was debugging their Plex setup:

- `ex(e)`, a Python 2 helper that no longer exists, called from inside
  `except (ValueError, IndexError)`.
- `response` left unbound when `urllib.request.urlopen` raises, because that
  handler only logs — `etree.parse(response)` then raised UnboundLocalError,
  which neither except clause catches, so it escaped `request()` entirely.

Split out of test_release_info_population.py, which is about
`createFromSearch()` not populating release metadata — a different fix in the
same PR.
"""

from unittest.mock import MagicMock, patch


class TestPlexErrorFormatting:
    """The `ex(e)` fix, exercised rather than grepped.

    The call sat inside an `except (ValueError, IndexError)` block, so the
    NameError replaced the real diagnostic at exactly the moment someone was
    debugging their Plex setup — and, because it escaped that handler, it
    aborted `request()` entirely instead of continuing.
    """

    def _server(self):
        from couchpotato.core.notifications.plex.server import PlexServer

        plex = MagicMock()
        # Drive the username/password branch that fetches a token: no
        # auth_token, but a username and password present.
        plex.conf.side_effect = lambda name, **kw: {
            'media_server': 'plex.local',
            'auth_token': '',
            'username': 'user',
            'password': 'pass',
        }.get(name, '')
        plex.urlopen.return_value = '<MediaContainer/>'

        server = PlexServer(plex)
        return server

    def test_a_response_without_a_token_does_not_raise(self):
        """Bug repro: `findall(...)[0]` raises IndexError, the handler runs,
        and on master `ex(e)` raised NameError straight out of `request()`."""
        server = self._server()

        tree = MagicMock()
        tree.findall.return_value = []          # no authentication-token node

        with patch('urllib.request.urlopen'), \
                patch('couchpotato.core.notifications.plex.server.etree.parse', return_value=tree):
            # Must complete without propagating NameError.
            server.request('library/sections')

    def test_a_failed_token_fetch_does_not_raise_nameerror(self):
        """Adjacent latent crash, same class: when urlopen raises URLError the
        handler only logs, leaving `response` unbound -- and the next block's
        `etree.parse(response)` then raised NameError, which neither except
        clause catches, so it escaped `request()` entirely."""
        import urllib.error

        server = self._server()

        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('boom')), \
                patch('couchpotato.core.notifications.plex.server.etree.parse') as parse:
            result = server.request('library/sections')

        assert result is None
        parse.assert_not_called(), 'must not try to parse a response we never got'

    def test_the_error_is_logged_with_the_exception(self):
        server = self._server()

        tree = MagicMock()
        tree.findall.return_value = []

        with patch('urllib.request.urlopen'), \
                patch('couchpotato.core.notifications.plex.server.etree.parse', return_value=tree), \
                patch('couchpotato.core.notifications.plex.server.log') as mock_log:
            server.request('library/sections')

        messages = [str(call) for call in mock_log.info.call_args_list]
        assert any('Error parsing plex.tv response' in m for m in messages), (
            'the parse failure must still be reported, got: %s' % messages
        )
