"""SEC-006 P1a: which columns of a combined row are credentials, and where each is sent.

The `combined` option declares `secret` (the credential columns) and `address`
(the column each secret is sent to, parallel to `secret`) beside `combine` and
`pairing`. Settings derives both the way `combine_groups()` derives the columns.

The sweep below reads the REAL provider declarations: it fails for a column that
is neither declared secret nor exempt with a stated reason, for a secret column
that is not in `combine` or `pairing`, and for a secret without a valid
`address`. A synthetic option proves the sweep can fail in each of those ways,
because a sweep that cannot fail guards nothing.
"""
import pytest

from tests.helpers import combine_groups
from tests.helpers.combine_groups import EXPECTED_COMBINED, group_settings, provider_configs

CREDENTIAL_WORDS = ('key', 'pass', 'token', 'secret')

#: Every combined column that is not a credential, and why. A new column of a
#: registered group fails the sweep until it is classified here or declared secret.
EXEMPT = {
    ('newznab', 'use'): 'on/off switch for the indexer row',
    ('newznab', 'host'): 'the indexer address, the place a secret is sent to',
    ('newznab', 'extra_score'): 'a number that adjusts ranking',
    ('newznab', 'custom_tag'): 'a category tag the person types as plain text',
    ('torrentpotato', 'use'): 'on/off switch for the indexer row',
    ('torrentpotato', 'host'): 'the indexer address, the place a secret is sent to',
    ('torrentpotato', 'name'): 'a display name',
    ('torrentpotato', 'seed_ratio'): 'a number',
    ('torrentpotato', 'seed_time'): 'a number',
    ('torrentpotato', 'extra_score'): 'a number that adjusts ranking',
    ('imdb', 'automation_urls_use'): 'on/off switch for the list row',
    ('imdb', 'automation_urls'): 'a public list address; automation groups carry no credential',
    ('itunes', 'automation_urls_use'): 'on/off switch for the list row',
    ('itunes', 'automation_urls'): 'a public feed address; automation groups carry no credential',
    ('letterboxd', 'automation_urls_use'): 'on/off switch for the list row',
    ('letterboxd', 'automation_urls'): 'a public list address; automation groups carry no credential',
}


def credential_shaped(column):
    return any(word in column.lower() for word in CREDENTIAL_WORDS)


def declaration_problems(section, option, exempt):
    """Every way one raw `combined` declaration breaks the secret/address contract."""
    problems = []
    combine = list(option.get('combine') or [])
    pairing = list(option.get('pairing') or [])
    secret = list(option.get('secret') or [])
    address = list(option.get('address') or [])
    for column in combine:
        if column in secret and (section, column) in exempt:
            problems.append('%s.%s is both secret and exempt' % (section, column))
        elif column not in secret and not exempt.get((section, column)):
            problems.append('%s.%s is neither secret nor exempt with a reason' % (section, column))
    for (exempt_section, column) in exempt:
        if exempt_section == section and column not in combine:
            problems.append('%s.%s is exempt but is not a column' % (section, column))
    if len(address) != len(secret):
        problems.append('%s has %d secret columns and %d addresses' % (section, len(secret), len(address)))
    for position, column in enumerate(secret):
        if column not in combine:
            problems.append('%s.%s is secret but not in combine' % (section, column))
        if column not in pairing:
            problems.append('%s.%s is secret but not in pairing' % (section, column))
        where = address[position] if position < len(address) else None
        if not where or not isinstance(where, str):
            problems.append('%s.%s has no address' % (section, column))
        elif where not in combine:
            problems.append('%s.%s has address %s, which is not in combine' % (section, column, where))
        elif where in secret:
            problems.append('%s.%s has a secret column as its address' % (section, column))
    return problems


def real_combined_options():
    for config in provider_configs():
        for section in config:
            for group in section['groups']:
                for option in group['options']:
                    if option.get('type') == 'combined' and option.get('combine'):
                        yield section['name'], option


def synthetic(**changes):
    option = {'type': 'combined', 'combine': ['use', 'host', 'key'], 'pairing': ['host', 'key', 'use'],
              'secret': ['key'], 'address': ['host']}
    option.update(changes)
    return option


SYNTHETIC_EXEMPT = {('zz', 'use'): 'switch', ('zz', 'host'): 'address'}


class TestRealDeclarations:
    def test_every_real_combined_option_passes_the_sweep(self):
        seen = []
        for section, option in real_combined_options():
            seen.append(section)
            assert declaration_problems(section, option, EXEMPT) == []
        assert sorted(seen) == ['imdb', 'itunes', 'letterboxd', 'newznab', 'torrentpotato']

    def test_the_two_credential_groups_declare_their_secret_and_address(self):
        declared = {section: (option.get('secret'), option.get('address'))
                    for section, option in real_combined_options()}

        assert declared['newznab'] == (['api_key'], ['host'])
        assert declared['torrentpotato'] == (['pass_key'], ['host'])
        for section in ('imdb', 'itunes', 'letterboxd'):
            assert not declared[section][0]

    def test_every_credential_shaped_real_column_is_secret(self):
        for section, option in real_combined_options():
            for column in option['combine']:
                if credential_shaped(column):
                    assert column in option['secret'], '%s.%s' % (section, column)


class TestDiscoveryDoesNotDependOnAList:
    """The groups are found by searching `couchpotato/`, so a provider nobody listed is still swept."""

    def test_the_discovered_options_are_exactly_the_expected_five(self):
        found = {(config['name'], option['name'])
                 for configs in provider_configs() for config in configs
                 for group in config['groups'] for option in group['options']
                 if option.get('type') == 'combined'}

        assert found == set(EXPECTED_COMBINED)

    def test_a_new_provider_with_a_combined_column_fails_discovery(self, tmp_path, monkeypatch):
        (tmp_path / 'zz_fake_provider.py').write_text(
            "config = [{'name': 'zz_fake', 'groups': [{'options': [{'name': 'api_key', 'type': 'combined',"
            " 'combine': ['use', 'api_key'], 'pairing': ['api_key', 'use']}]}]}]\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(combine_groups, 'combined_declaring_modules',
                            lambda: [*real_modules, 'zz_fake_provider'])

        with pytest.raises(AssertionError, match=r"new \[\('zz_fake', 'api_key'\)\]"):
            provider_configs()

    def test_a_combined_type_written_through_a_constant_is_still_found_at_runtime(self, tmp_path, monkeypatch):
        """The source search matches the literal spelling; the runtime check does not care."""
        (tmp_path / 'zz_constant_provider.py').write_text(
            "COMBINED = 'combined'\n"
            "config = [{'name': 'zz_const', 'groups': [{'options': [dict(name='api_key', type=COMBINED,"
            " combine=['use', 'api_key'], pairing=['api_key', 'use'])]}]}]\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(combine_groups, 'config_declaring_modules',
                            lambda: [*real_config_modules, 'zz_constant_provider'])
        # The source search sees nothing wrong, which is exactly why the runtime check exists.
        monkeypatch.setattr(combine_groups, 'combined_declaring_modules', lambda: list(real_modules))

        with pytest.raises(AssertionError, match=r"runtime new \[\('zz_const', 'api_key'\)\]"):
            provider_configs()

    def test_the_runtime_check_finds_the_same_five(self):
        assert combine_groups.runtime_combined_options() == set(EXPECTED_COMBINED)

    def test_a_lost_group_fails_discovery_too(self, monkeypatch):
        monkeypatch.setattr(combine_groups, 'combined_declaring_modules',
                            lambda: [name for name in real_modules if not name.endswith('.imdb')])

        with pytest.raises(AssertionError, match=r"lost \[\('imdb', 'automation_urls'\)\]"):
            provider_configs()


real_modules = combine_groups.combined_declaring_modules()
real_config_modules = combine_groups.config_declaring_modules()


class TestTheSweepCanFail:
    """One synthetic declaration per way to be wrong, so the sweep is shown to fail."""

    def test_a_sound_synthetic_option_passes(self):
        assert declaration_problems('zz', synthetic(), SYNTHETIC_EXEMPT) == []

    def test_a_credential_column_with_no_secret_entry_or_exemption_fails(self):
        option = synthetic(combine=['use', 'host', 'key', 'api_token'])

        problems = declaration_problems('zz', option, SYNTHETIC_EXEMPT)

        assert any('api_token is neither secret nor exempt' in p for p in problems)

    def test_an_exemption_without_a_reason_fails(self):
        problems = declaration_problems('zz', synthetic(), {**SYNTHETIC_EXEMPT, ('zz', 'host'): ''})

        assert any('zz.host is neither' in p for p in problems)

    def test_a_secret_missing_from_combine_fails(self):
        problems = declaration_problems('zz', synthetic(secret=['key', 'ghost'], address=['host', 'host']),
                                        SYNTHETIC_EXEMPT)

        assert any('ghost is secret but not in combine' in p for p in problems)

    def test_a_secret_missing_from_pairing_fails(self):
        problems = declaration_problems('zz', synthetic(pairing=['host', 'use']), SYNTHETIC_EXEMPT)

        assert any('key is secret but not in pairing' in p for p in problems)

    def test_a_secret_without_an_address_fails(self):
        option = synthetic()
        del option['address']

        problems = declaration_problems('zz', option, SYNTHETIC_EXEMPT)

        assert any('key has no address' in p for p in problems)

    def test_a_secret_with_an_empty_address_fails(self):
        problems = declaration_problems('zz', synthetic(address=['']), SYNTHETIC_EXEMPT)

        assert any('key has no address' in p for p in problems)

    def test_a_secret_with_an_unknown_address_fails(self):
        problems = declaration_problems('zz', synthetic(address=['nowhere']), SYNTHETIC_EXEMPT)

        assert any('address nowhere, which is not in combine' in p for p in problems)

    def test_an_address_with_no_secret_to_pair_with_fails(self):
        problems = declaration_problems('zz', synthetic(address=['host', 'use']), SYNTHETIC_EXEMPT)

        assert any('1 secret columns and 2 addresses' in p for p in problems)

    def test_a_secret_that_is_its_own_address_fails(self):
        problems = declaration_problems('zz', synthetic(address=['key']), SYNTHETIC_EXEMPT)

        assert any('a secret column as its address' in p for p in problems)

    def test_a_stale_exemption_fails(self):
        problems = declaration_problems('zz', synthetic(), {**SYNTHETIC_EXEMPT, ('zz', 'gone'): 'old'})

        assert any('zz.gone is exempt but is not a column' in p for p in problems)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


class TestDerivation:
    def test_secret_columns_are_derived_from_the_registered_options(self, settings):
        assert settings.combine_secrets() == {'newznab': ('api_key',), 'torrentpotato': ('pass_key',)}

    def test_each_secret_maps_to_the_column_it_is_sent_to(self, settings):
        assert settings.combine_addresses() == {'newznab': {'api_key': 'host'},
                                                'torrentpotato': {'pass_key': 'host'}}

    def test_a_group_registered_later_is_derived_with_no_production_edit(self, settings):
        settings.addOptions('zz_test', {'name': 'zz_test', 'groups': [{'options': [
            {'name': 'use'}, {'name': 'host'}, {'name': 'secret_cell'},
            {'name': 'cells', 'type': 'combined', 'combine': ['use', 'host', 'secret_cell'],
             'pairing': ['host', 'secret_cell', 'use'], 'secret': ['secret_cell'], 'address': ['host']},
        ]}]})

        assert settings.combine_secrets()['zz_test'] == ('secret_cell',)
        assert settings.combine_addresses()['zz_test'] == {'secret_cell': 'host'}

    def test_a_group_that_declares_no_secret_is_not_listed(self, settings):
        assert 'imdb' not in settings.combine_secrets()
