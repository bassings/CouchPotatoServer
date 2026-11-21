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
