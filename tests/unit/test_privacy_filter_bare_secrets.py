"""`PrivacyFilter` redacted only query-string secrets, not bare `name=value`.

The filter's substitutions were anchored on `?name=` and `&name=`, so anything
logged outside a URL went through untouched. Three live call sites did exactly
that:

  * `notifications/telegrambot.py:37` -- `token=%s` at **ERROR** level, so it
    reaches production logs, not just a debug run. The Telegram bot token is a
    full send-as-this-bot credential.
  * `downloaders/synology.py:125` -- `sid=%s`, the Synology session id.
  * `http_client.py:236` -- logs the full URL, which the query-param pass DOES
    cover, provided the parameter name is in the list. `token`, `authkey`,
    `torrent_pass` and `sid` were not.

Why it matters beyond tidiness: this branch made those logs travel. The E2E
harness attaches a console handler and CI uploads that stream as a build
artefact, and the same filter is what the `--console_log` path relies on. A
secret that used to sit in a local file now leaves the machine.

The bare-name pass is deliberately conservative about where it stops -- see
`test_redaction_stops_at_the_value` -- because a filter that eats the rest of
the line destroys the diagnostic the operator needed, and a redaction nobody
can read around gets switched off.
"""
import logging

import pytest

from couchpotato.core.logger import PrivacyFilter


@pytest.fixture
def record_filter(monkeypatch):
    """A PrivacyFilter with dev mode off and a known api_key."""
    f = PrivacyFilter()
    monkeypatch.setattr(PrivacyFilter, '_is_develop', False, raising=False)
    monkeypatch.setattr(PrivacyFilter, '_api_key', 'THEAPIKEY', raising=False)
    return f


def _filtered(f, msg, *args):
    record = logging.LogRecord('t', logging.INFO, __file__, 1, msg, args or None, None)
    f.filter(record)
    return str(record.msg)


class TestBareSecretsAreRedacted:

    @pytest.mark.parametrize('name,secret', [
        ('token', '123456:AAH-SUPERSECRETBOTTOKEN'),
        ('sid', 'abcdef0123456789'),
        ('authkey', 'AUTHKEYVALUE'),
        ('torrent_pass', 'TORRENTPASSVALUE'),
        ('passkey', 'PASSKEYVALUE'),
        ('api_key', 'APIKEYVALUE'),
        ('password', 'hunter2'),
    ])
    def test_a_bare_name_equals_value_is_redacted(self, record_filter, name, secret):
        out = _filtered(record_filter, 'something failed (%s=%s)' % (name, secret))

        assert secret not in out, (
            '%s= was logged in the clear outside a query string: %r' % (name, out)
        )

    def test_the_telegram_call_site_shape(self, record_filter):
        """The exact message from notifications/telegrambot.py:37, at ERROR."""
        out = _filtered(
            record_filter,
            'Could not send notification to TelegramBot (token=%s). Response: [%s]',
            '123456:AAH-SUPERSECRET', 'Bad Request',
        )

        assert '123456:AAH-SUPERSECRET' not in out, out
        assert 'Bad Request' in out, 'the diagnostic was destroyed along with the secret'

    def test_the_synology_call_site_shape(self, record_filter):
        out = _filtered(record_filter, 'sid=%s', 'SYNOSESSIONID')

        assert 'SYNOSESSIONID' not in out, out


class TestRedactionStaysUseful:
    """A filter that eats the line destroys the diagnostic and gets turned off."""

    def test_redaction_stops_at_the_value(self, record_filter):
        out = _filtered(record_filter, 'token=SECRETVALUE and the response was 404 Not Found')

        assert 'SECRETVALUE' not in out
        assert '404 Not Found' in out, (
            'the redaction consumed the rest of the message: %r' % out
        )

    def test_an_unrelated_assignment_is_left_alone(self, record_filter):
        out = _filtered(record_filter, 'retries=3 timeout=30 status=ok')

        assert 'retries=3' in out
        assert 'timeout=30' in out
        assert 'status=ok' in out

    def test_query_string_redaction_still_works(self, record_filter):
        """The pass that already existed must not regress."""
        out = _filtered(record_filter, 'Opening url: get https://api.example/3/x?api_key=SECRET&page=2')

        assert 'SECRET' not in out
        assert 'page=2' in out, 'a non-secret query parameter was redacted too'

    def test_the_api_key_itself_is_still_redacted(self, record_filter):
        out = _filtered(record_filter, 'GET /api/THEAPIKEY/movie.list')

        assert 'THEAPIKEY' not in out, out


class TestPrefixedAndMixedCaseSecretNames:
    """`X-Plex-Token=` reaches the log and neither pass caught it.

    `notifications/plex/server.py:85` builds
    `'%s/%s?X-Plex-Token=%s' % (host, path, auth_token)` and hands it to
    `urlopen`, and `http_client.py:236` logs `'Opening url: %s %s'` with the
    full URL at INFO. So the Plex auth token was written to the log on every
    Plex notification.

    Neither redaction pass matched it: the query-string pass wants an exact
    lowercase `token` immediately after `?` or `&`, and the bare pass was
    case-sensitive and anchored with `\\b` directly against the name. Raised as
    a nit; it is a live secret leak.

    Prefix matching is applied ONLY to names long and distinctive enough to
    carry it -- see `test_short_names_are_not_prefix_matched`.
    """

    @pytest.mark.parametrize('spelling', [
        'token=SECRETVALUE',
        'access_token=SECRETVALUE',
        'bot_token=SECRETVALUE',
        'X-Plex-Token=SECRETVALUE',
        'Token=SECRETVALUE',
        'API_KEY=SECRETVALUE',
        'new_password=SECRETVALUE',
    ])
    def test_prefixed_and_mixed_case_names_are_redacted(self, record_filter, spelling):
        out = _filtered(record_filter, 'request failed: %s' % spelling)

        assert 'SECRETVALUE' not in out, (
            '%s went to the log in the clear: %r' % (spelling, out)
        )

    def test_the_real_plex_url_shape(self, record_filter):
        out = _filtered(
            record_filter,
            'Opening url: %s %s, data: %s',
            'get', 'http://plex:32400/library?X-Plex-Token=PLEXAUTHTOKEN', "['a']",
        )

        assert 'PLEXAUTHTOKEN' not in out, out
        assert 'plex:32400' in out, 'the host was destroyed along with the token'

    def test_short_names_are_not_prefix_matched(self, record_filter):
        """`sid` is three characters; prefix-matching it would eat ordinary words.

        The redaction has to stay narrow enough that people leave it on.
        """
        out = _filtered(record_filter, 'basid=notasecret and resid=alsofine')

        assert 'notasecret' in out, out
        assert 'alsofine' in out, out
