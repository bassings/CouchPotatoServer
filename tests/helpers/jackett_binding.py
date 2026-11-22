"""Shared fixtures for the SEC-005 Jackett key binding tests.

The binding is the normalised address a saved Jackett API key was saved for
(``torrentpotato.jackett_key_binding``). This module holds the one table of
saved addresses and the literal string each must normalise to, so the unit test
of the normaliser and the test that a key save stores that string cannot
disagree. Every expected string is written out here; none is computed by the
function under test.

Hosts are ``.invalid`` or ``.local`` names and every credential is an obvious
placeholder, so nothing here resembles a real key.
"""
import configparser
import contextlib

from couchpotato.environment import Env
from tests.helpers.combine_groups import group_settings

SECTION = 'torrentpotato'
KEY_OPTION = 'jackett_api_key'
URL_OPTION = 'jackett_url'
BINDING_OPTION = 'jackett_key_binding'
BINDING_FLAG_OPTION = BINDING_OPTION + '_internal_meta'
PLACEHOLDER_KEY = 'placeholder-jackett-key-one'
OTHER_KEY = 'placeholder-jackett-key-two'

PLAIN_HOST = 'http://jackett.local'
HOST_9117 = 'http://jackett.local:9117'

# (label, the address as saved, the binding a key save must store for it).
NORMALISER_TABLE = [
    ('no scheme', 'localhost:9117', 'http://localhost:9117'),
    ('no scheme and no port', 'jackett.local', PLAIN_HOST),
    ('trailing slash', 'http://jackett.local:9117/', HOST_9117),
    ('upper case scheme and host', 'HTTP://Jackett.Local:9117', HOST_9117),
    ('explicit default http port', 'http://jackett.local:80', PLAIN_HOST),
    ('explicit default http port and slash', 'HTTP://Jackett.Local:80/', PLAIN_HOST),
    ('explicit default https port', 'https://jackett.local:443/', 'https://jackett.local'),
    ('a port that is only default for the other scheme', 'https://jackett.local:80',
     'https://jackett.local:80'),
    ('a path prefix', 'http://jackett.local:9117/jackett/', 'http://jackett.local:9117/jackett'),
    ('an IPv6 literal', 'http://[::1]:9117', 'http://[::1]:9117'),
    ('an upper-case IPv6 literal', 'http://[FE80::1]:9117', 'http://[fe80::1]:9117'),
    ('userinfo', 'http://test-user:test-pass@jackett.local:9117',
     'http://test-user:test-pass@jackett.local:9117'),
    ('empty parts of the userinfo are still userinfo', 'http://:@jackett.local', 'http://:@jackett.local'),
    ('userinfo keeps its case, the host does not', 'http://Test-User:Test-Pass@Jackett.Local',
     'http://Test-User:Test-Pass@jackett.local'),
    ('a bytes-literal wrapper', "b'http://jackett.local:9117/'", HOST_9117),
    ('surrounding whitespace', '  http://jackett.local:9117  ', HOST_9117),
]

# Saved addresses that cannot be normalised: no value, and an empty binding.
# The first four are the AC-DATA-6 fixtures (`urllib3.util.parse_url` raises on
# all four; `urllib.parse` on the first three). The rest are shapes the two
# parsers read differently, or that carry something the key must never follow.
UNPARSEABLE = [
    ('a port out of range', 'localhost:99999'),
    ('a port that is not a number', 'http://h:abc'),
    ('an unterminated IPv6 literal', 'http://[::1'),
    ('a tab inside the host', 'http://jackett\t.local'),
    ('empty', ''),
    ('blank', '   '),
    ('no host', 'http://'),
    ('a port and no host', 'http://:9117'),
    ('another scheme', 'ftp://jackett.local'),
    ('an empty userinfo before the host', 'http://@jackett.local'),
    ('a query', 'http://jackett.local:9117?x=1'),
    ('an empty query after a path', 'http://jackett.local:9117/a?'),
    ('an empty query after the port', 'http://jackett.local:9117?'),
    ('an empty fragment after a slash', 'http://jackett.local:9117/#'),
    ('an empty fragment after a path', 'http://jackett.local:9117/a#'),
    ('a fragment hiding a second host', 'http://jackett.local#@evil.invalid'),
    ('a fragment ahead of a host', 'http://evil.invalid#@jackett.local:9117'),
    ('a backslash before the real host', r'http://evil.invalid\@jackett.local:9117'),
    ('a backslash after the real host', r'http://jackett.local:9117\@evil.invalid/'),
    ('a space before the real host', 'http://jackett.local:9117 @evil.invalid/'),
    ('an internationalised host the parsers read differently', 'http://bücher.example'),
    ('a path the transport would rewrite', 'http://jackett.local/a/../b'),
    ('an IPv6 zone', 'http://[fe80::1%25eth0]:9117'),
]


def on_disk(settings, option, section=SECTION):
    """One option as a fresh parser reads it from the file, or None when it is absent."""
    parser = configparser.RawConfigParser()
    parser.read(settings.file, encoding='utf-8')
    return parser.get(section, option, fallback=None)


@contextlib.contextmanager
def jackett_world(tmp_path, monkeypatch, stored=None):
    """The real settings routes over a real ``Settings`` and a real provider.

    Yields ``(settings, client, provider)``. The provider is built, not stubbed,
    because the value hook that writes the binding is registered by its
    constructor. Only the network call is replaced, by the tests that make one.
    """
    from tests.integration.test_settings_group_save_route import live_world
    with live_world(tmp_path, monkeypatch, stored=stored) as (settings, client):
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        yield settings, client, TorrentPotato()


@contextlib.contextmanager
def jackett_settings(tmp_path, monkeypatch, stored=None):
    """A real ``Settings`` with the real torrentpotato declaration and a real provider.

    The provider is built, not stubbed, because the value hook that writes the
    binding is registered by its constructor. Only the network call is replaced
    by tests that need one.
    """
    with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
        monkeypatch.setattr(Env, '_settings', settings)
        from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
        provider = TorrentPotato()
        yield settings, provider


# --- SEC-005 P2: the guard ---------------------------------------------------

REFUSAL = ('Check the Jackett URL is right, then copy the API key from your Jackett dashboard, '
           'paste it above and press Sync. This is needed once after this update, or after the URL changes.')
KEY_REJECTED = 'Jackett did not accept the API key. Copy it again from your Jackett dashboard.'
REQUIRED = 'Jackett URL and API key are required'
INDEXERS_XML = ('<indexers><indexer id="alpha" configured="true"><title>Alpha</title></indexer>'
                '</indexers>')
OPERATIONS = ('jackettTest', 'jackettSync')
ROUTE_OF = {'jackettTest': 'torrentpotato.jackett_test', 'jackettSync': 'torrentpotato.jackett_sync'}


class Reply:
    """What the HTTP session hands back: enough of a ``requests.Response`` for ``HttpClient``.

    A status other than 200 raises, as ``requests`` does, an ``HTTPError`` whose own text carries the
    request URL (which carries the key): code that reports a failure must never use that text.
    """

    def __init__(self, body, status_code=200, url=''):
        self.content = body.encode('utf-8')
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(
                f'{self.status_code} Client Error: for url: {self.url}', response=self)


class Transport:
    """The HTTP session behind ``Env.get('http_opener')``: records every request that would leave.

    ``HttpClient`` runs for real in front of it, so what is recorded is what the
    process would have put on the wire.
    """

    def __init__(self, body=INDEXERS_XML, status=200):
        self.requests = []
        self.body = body
        self.status = status

    def request(self, method, url, **kwargs):
        self.requests.append(url)
        return Reply(self.body, self.status, url)


@contextlib.contextmanager
def guarded_world(tmp_path, monkeypatch, stored=None):
    """``jackett_world`` plus a recording transport. Yields ``(settings, client, provider, transport)``."""
    with jackett_world(tmp_path, monkeypatch, stored=stored) as (settings, client, provider):
        transport = Transport()
        monkeypatch.setattr(Env, '_http_opener', transport)
        provider.http_client.time_between_calls = 0
        yield settings, client, provider, transport


def bind_saved_pair(settings, address, key):
    """Enter the saved Jackett pair the way a user does: a ``settings.save`` of the address, then of the key.

    The key save is the production writer of the binding, so a test that needs
    "an install with a working saved key" gets one that is bound, and never
    writes the binding's name or a precomputed value (AC-QA-20). It builds a
    real provider so that the value hook the writer runs through is registered
    on the event bus the caller's ``Settings`` isolates.
    """
    from couchpotato.core.media.movie.providers.torrent.torrentpotato import TorrentPotato
    TorrentPotato()
    for name, value in ((URL_OPTION, address), (KEY_OPTION, key)):
        saved = settings.saveView(section=SECTION, name=name, value=value)
        assert saved['success'] is True, saved
