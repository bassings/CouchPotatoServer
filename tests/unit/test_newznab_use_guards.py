"""A short or malformed Newznab ``use`` list must disable, never crash or enable.

``getHosts`` indexes the stored ``use`` list by the host's position, and
``isEnabled`` reads each entry as an int. Two stored shapes used to raise and
take every Newznab indexer down with them (``getHosts`` and ``isEnabled`` run
for the provider as a whole):

* ``use`` shorter than ``host`` -> ``IndexError`` at ``uses[nr]``;
* an empty ``use`` entry, which the Settings page saves for a row filled in
  without touching its Enable switch -> ``ValueError`` from ``int('')``.

The rule these tests pin is fail closed: anything that is not a number means
"disabled", and a number other than zero is the only thing that enables.
Drives the real ``getHosts`` and ``isEnabled`` over the stored strings.
Hosts use ``.invalid`` and keys are placeholders; nothing here is a credential.
"""
import pytest
from unittest.mock import patch

from couchpotato.core.media._base.providers.nzb import newznab
from couchpotato.core.media._base.providers.nzb.newznab import Base


def _provider_settings(host, api_key, use):
    return {'enabled': '1', 'host': host, 'api_key': api_key, 'use': use}


def _read(host, api_key, use):
    """(getHosts result, isEnabled per host) from the real methods."""
    settings = _provider_settings(host, api_key, use)
    provider = object.__new__(Base)
    with patch.object(Base, 'conf', side_effect=lambda name, *a, **k: settings.get(name, '')):
        hosts = provider.getHosts()
        return hosts, [bool(provider.isEnabled(h)) for h in hosts]


THREE_HOSTS = 'https://indexer-a.invalid,https://indexer-b.invalid,https://indexer-c.invalid'
THREE_KEYS = 'placeholder-key-a,placeholder-key-b,placeholder-key-c'


@pytest.fixture(autouse=True)
def _fresh_length_warning_memo():
    """The length warning is logged once per distinct pair of counts per process."""
    newznab._warned_length_mismatches.clear()


def _logged(settings_use, host=THREE_HOSTS, keys=THREE_KEYS):
    """The formatted warnings getHosts logs for these settings (called once)."""
    settings = _provider_settings(host, keys, settings_use)
    provider = object.__new__(Base)
    with patch.object(newznab.log, 'warning') as warning, \
            patch.object(Base, 'conf', side_effect=lambda name, *a, **k: settings.get(name, '')):
        provider.getHosts()
    return [call.args[0] % call.args[1:] for call in warning.call_args_list]


def test_use_shorter_than_host_disables_every_host_because_no_pairing_can_be_trusted():
    hosts, enabled = _read(THREE_HOSTS, THREE_KEYS, use='1')

    assert [h['host'] for h in hosts] == [
        'https://indexer-a.invalid', 'https://indexer-b.invalid', 'https://indexer-c.invalid',
    ]
    assert [h['use'] for h in hosts] == ['0', '0', '0']
    assert enabled == [False, False, False]


def test_equal_length_lists_are_left_as_stored():
    hosts, enabled = _read(THREE_HOSTS, THREE_KEYS, use='1,0,1')

    assert [h['use'] for h in hosts] == ['1', '0', '1']
    assert enabled == [True, False, True]
    assert _logged('1,0,1') == []


def test_use_longer_than_host_is_tolerated_as_it_always_was():
    hosts, enabled = _read('https://indexer-a.invalid', 'placeholder-key-a', use='1,1,1')

    assert [h['use'] for h in hosts] == ['1']
    assert enabled == [True]
    assert _logged('1,1,1', host='https://indexer-a.invalid', keys='placeholder-key-a') == []


def test_a_length_mismatch_logs_one_warning_with_the_counts_and_no_host_or_key_text():
    messages = _logged('1')

    assert len(messages) == 1
    assert '3' in messages[0] and '1' in messages[0]
    assert 'disabled' in messages[0]
    for private in ('indexer-', 'evil', 'placeholder', 'https', '.invalid'):
        assert private not in messages[0]


def test_the_length_warning_is_not_repeated_for_the_same_counts_but_is_for_new_ones():
    """getHosts runs on every search and every isEnabled(): do not flood the log."""
    first = _logged('1')
    again = _logged('1')
    other_counts = _logged('1', host='https://indexer-a.invalid,https://indexer-b.invalid',
                           keys='placeholder-key-a,placeholder-key-b')

    assert (len(first), len(again), len(other_counts)) == (1, 0, 1)


def _search_with_settings(settings):
    """Run the real search() loop; return the (url, key) of every host queried."""
    queried = []
    provider = object.__new__(Base)
    with patch.object(Base, 'conf', side_effect=lambda name, *a, **k: settings.get(name, '')), \
            patch.object(Base, '_searchOnHost',
                         side_effect=lambda h, *a, **k: queried.append((provider.getUrl(h['host']), h['api_key']))), \
            patch.object(newznab, 'ResultList', lambda *a, **k: []):
        provider.search({}, {})
    return queried


def test_a_comma_in_a_settings_page_url_queries_nothing_and_never_sends_a_key_to_the_wrong_host():
    """What the Settings page stores after row 1's URL gains a comma (host list one longer than use)."""
    queried = _search_with_settings(_provider_settings(
        host='https://indexer-a.invalid/api?x=1,evil.invalid,https://indexer-b.invalid',
        api_key='placeholder-key-a,placeholder-key-b',
        use='1,1',
    ))

    assert queried == []


def test_search_still_queries_every_enabled_host_when_the_lists_line_up():
    queried = _search_with_settings(_provider_settings(THREE_HOSTS, THREE_KEYS, use='1,0,1'))

    assert [key for _, key in queried] == ['placeholder-key-a', 'placeholder-key-c']


def test_empty_use_setting_with_hosts_disables_every_host_instead_of_raising():
    hosts, enabled = _read(THREE_HOSTS, THREE_KEYS, use='')

    assert len(hosts) == 3
    assert enabled == [False, False, False]


def test_an_empty_use_entry_disables_only_that_indexer():
    hosts, enabled = _read(THREE_HOSTS, THREE_KEYS, use='1,,1')

    assert len(hosts) == 3
    assert enabled == [True, False, True]


@pytest.mark.parametrize('entry', ['abc', 'yes', '1.0', ' ', 'None', '-'])
def test_a_non_numeric_use_entry_disables_that_indexer_and_never_enables_it(entry):
    hosts, enabled = _read(THREE_HOSTS, THREE_KEYS, use='1,%s,1' % entry)

    assert len(hosts) == 3
    assert enabled == [True, False, True]


def test_zero_still_disables_and_one_still_enables():
    _, enabled = _read(THREE_HOSTS, THREE_KEYS, use='1,0,1')

    assert enabled == [True, False, True]
