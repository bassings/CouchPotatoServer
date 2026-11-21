"""SEC-005 P1, AC-OPS-7 and AC-ARCH-5 (normaliser clauses): one function, literal expectations.

``normalise_jackett_address`` produces the string a Jackett API key is bound to.
The expected string for every row is written out in
``tests/helpers/jackett_binding.py``; none is computed by calling the function.
The function is final in this slice: the guard of the next one reads what is
stored here, so a change to any row of the table is a change to every stored
binding.
"""
import re
import urllib.parse

import pytest

from couchpotato.core.media._base.providers.torrent.torrentpotato import normalise_jackett_address
from tests.helpers.jackett_binding import NORMALISER_TABLE, UNPARSEABLE

TABLE_ARGS = 'label,saved,expected'
PLAIN = 'http://jackett.local'
WITH_PORT = 'http://jackett.local:9117'


@pytest.mark.parametrize(TABLE_ARGS, NORMALISER_TABLE, ids=[row[0] for row in NORMALISER_TABLE])
def test_each_saved_shape_normalises_to_its_literal_string(label, saved, expected):
    assert normalise_jackett_address(saved) == expected


@pytest.mark.parametrize('label,saved', UNPARSEABLE, ids=[row[0] for row in UNPARSEABLE])
def test_an_address_either_parser_rejects_gives_no_value_and_never_raises(label, saved):
    assert normalise_jackett_address(saved) is None


@pytest.mark.parametrize('hostile', [None, 0, 1, False, True, [], [PLAIN], {}, 1.5,
                                     object(), b'\xff\xfe', b'', "b'", 'b\'\xff\''])
def test_a_value_that_is_not_an_address_gives_no_value_and_never_raises(hostile):
    assert normalise_jackett_address(hostile) is None


def test_bytes_are_read_as_utf_8_text():
    assert normalise_jackett_address(b'http://jackett.local:9117/') == WITH_PORT


@pytest.mark.parametrize(TABLE_ARGS, NORMALISER_TABLE, ids=[row[0] for row in NORMALISER_TABLE])
def test_normalising_the_output_changes_nothing(label, saved, expected):
    assert normalise_jackett_address(expected) == expected


def test_two_spellings_of_one_address_give_one_string():
    assert normalise_jackett_address('HTTP://Jackett.Local:80/') == normalise_jackett_address(
        PLAIN)


@pytest.mark.parametrize('first,second', [
    (WITH_PORT, 'http://jackett.local:9118'),
    (PLAIN, 'https://jackett.local'),
    ('http://jackett.local/a', 'http://jackett.local/b'),
    ('http://jackett.local/a', 'http://jackett.local/A'),
    (PLAIN, 'http://sibling.local'),
    (PLAIN, 'http://jackett.local.'),
    (PLAIN, 'http://test-user@jackett.local'),
    ('http://test-user:one@jackett.local', 'http://test-user:two@jackett.local'),
    ('http://Test-User@jackett.local', 'http://test-user@jackett.local'),
])
def test_addresses_that_reach_different_places_give_different_strings(first, second):
    assert normalise_jackett_address(first) != normalise_jackett_address(second)


@pytest.mark.parametrize(TABLE_ARGS, NORMALISER_TABLE, ids=[row[0] for row in NORMALISER_TABLE])
def test_the_string_is_one_both_parsers_read_the_same_way(label, saved, expected):
    """What is stored is what the transport connects to, whichever parser reads it."""
    from urllib3.util import parse_url

    std = urllib.parse.urlsplit(expected)
    ref = parse_url(expected)
    assert (std.hostname or '') == re.sub(r'^\[|\]$', '', ref.host)
    assert std.port == ref.port
    assert std.path == (ref.path or '')
    assert not std.query
    assert not std.fragment


@pytest.mark.parametrize('unsafe', ['\t', '\n', '\r', ' ', '\\', '\x00', '\x01', '\x1f', '\x7f'])
@pytest.mark.parametrize('template', ['http://jackett{}.local:9117', 'http://jackett.local:9117/a{}b',
                                      'http://us{}er@jackett.local:9117'])
def test_whitespace_a_control_character_and_a_backslash_are_refused_even_if_both_parsers_agree(
        monkeypatch, template, unsafe):
    """The parsers agree on every one of these today, so the explicit refusal is not what stops them.

    It is what stops them if a parser release changes how it reads one: the same
    check, with the cross-check replaced by one that accepts anything, must still
    give no value.
    """
    from couchpotato.core.media._base.providers.torrent import torrentpotato
    monkeypatch.setattr(torrentpotato, '_agreed_parts',
                        lambda candidate: ('http', None, 'jackett.local', 9117, ''))

    assert normalise_jackett_address(template.format(unsafe)) is None


def test_that_same_stand_in_does_accept_a_clean_address(monkeypatch):
    """The control for the test above: without an unsafe character the stand-in gives a value."""
    from couchpotato.core.media._base.providers.torrent import torrentpotato
    monkeypatch.setattr(torrentpotato, '_agreed_parts',
                        lambda candidate: ('http', None, 'jackett.local', 9117, ''))

    assert normalise_jackett_address(WITH_PORT) == WITH_PORT


BASE = WITH_PORT


@pytest.mark.parametrize('field,different', [
    ('scheme', 'https'), ('host', 'other.local'), ('port', 9118), ('auth', 'other-user'),
    ('path', '/other'), ('query', 'x=1'), ('fragment', 'frag'),
], ids=lambda value: str(value))
def test_a_transport_that_reads_the_address_differently_leaves_it_with_no_value(monkeypatch, field, different):
    """AC-SEC-2: `urllib3.util.parse_url` decides where a request goes, so any difference refuses.

    The two parsers agree on every address the other tests use, so the real ones
    cannot show each comparison separately; here the transport's reading of one
    part is replaced and nothing else is.
    """
    from couchpotato.core.media._base.providers.torrent import torrentpotato
    real = torrentpotato.parse_url
    monkeypatch.setattr(torrentpotato, 'parse_url', lambda text: real(text)._replace(**{field: different}))

    assert normalise_jackett_address(BASE) is None


@pytest.mark.parametrize('changed', [
    {'netloc': 'jackett.local:9118'}, {'netloc': 'other.local:9117'}, {'netloc': 'someone@jackett.local:9117'},
    {'query': 'x=1'}, {'fragment': 'frag'}, {'path': '/other'},
], ids=lambda value: next(iter(value.items()))[0] + '=' + next(iter(value.items()))[1])
def test_a_standard_reading_that_differs_from_the_transports_leaves_it_with_no_value(monkeypatch, changed):
    from couchpotato.core.media._base.providers.torrent import torrentpotato
    real = torrentpotato.urlsplit
    monkeypatch.setattr(torrentpotato, 'urlsplit', lambda text: real(text)._replace(**changed))

    assert normalise_jackett_address(BASE) is None


def test_with_both_readings_untouched_the_same_address_has_a_value(monkeypatch):
    """The control for the two tests above."""
    assert normalise_jackett_address(BASE) == BASE
