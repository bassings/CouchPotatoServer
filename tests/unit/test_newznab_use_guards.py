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


def test_use_shorter_than_host_disables_the_extra_hosts_and_keeps_the_earlier_ones():
    hosts, enabled = _read(THREE_HOSTS, THREE_KEYS, use='1')

    assert [h['host'] for h in hosts] == [
        'https://indexer-a.invalid', 'https://indexer-b.invalid', 'https://indexer-c.invalid',
    ]
    assert [h['use'] for h in hosts] == ['1', '0', '0']
    assert enabled == [True, False, False]


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
