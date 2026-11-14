"""Newznab pairs its host, api_key and use settings BY POSITION.

The setup wizard saves three comma-separated strings. ``getHosts`` reads each
with ``splitString(..., clean=False)`` (blanks kept) and indexes all three by
the host's position, so position i must describe one indexer in every list.
These tests drive the real ``getHosts`` over the strings the wizard saves
(tests/e2e/wizard-newznab-pairing.spec.ts asserts the wizard produces them).

Hosts use ``.invalid`` and keys are placeholders; nothing here is a credential.
"""
from unittest.mock import patch

from couchpotato.core.media._base.providers.nzb.newznab import Base


def _hosts_for(host, api_key, use):
    """Run the real getHosts over the given stored setting strings."""
    settings = {'host': host, 'api_key': api_key, 'use': use}
    provider = object.__new__(Base)
    with patch.object(Base, 'conf', side_effect=lambda name, *a, **k: settings.get(name, '')):
        return provider.getHosts()


def _pairs(hosts):
    return [(h['host'], h['api_key'], h['use']) for h in hosts]


def test_url_without_key_then_complete_row_keeps_each_key_with_its_own_host():
    """What the fixed wizard saves for [A with no key, B with KEY_B]."""
    hosts = _hosts_for(
        host='https://indexer-a.invalid,https://indexer-b.invalid',
        api_key=',placeholder-key-b',
        use='1,1',
    )

    assert _pairs(hosts) == [
        ('https://indexer-a.invalid', '', '1'),
        ('https://indexer-b.invalid', 'placeholder-key-b', '1'),
    ]


def test_independently_filtered_lists_send_one_indexers_key_to_another():
    """Why the wizard must not filter the lists independently.

    This is the OLD wizard output for the same rows: the blank key was dropped
    from api_key but not from host, so position 0 receives KEY_B. It documents
    how positional pairing behaves; it is not a supported shape.
    """
    hosts = _hosts_for(
        host='https://indexer-a.invalid,https://indexer-b.invalid',
        api_key='placeholder-key-b',
        use='1,1',
    )

    assert _pairs(hosts) == [
        ('https://indexer-a.invalid', 'placeholder-key-b', '1'),
        ('https://indexer-b.invalid', '', '1'),
    ]


def test_a_zero_in_use_disables_the_indexer_at_the_same_position_not_the_next():
    """A blank row's '0' kept in use (old wizard) disables the indexer after it."""
    hosts = _hosts_for(
        host='https://indexer-a.invalid,https://indexer-c.invalid',
        api_key='placeholder-key-a,placeholder-key-c',
        use='1,0,1',
    )

    assert _pairs(hosts) == [
        ('https://indexer-a.invalid', 'placeholder-key-a', '1'),
        ('https://indexer-c.invalid', 'placeholder-key-c', '0'),
    ]
