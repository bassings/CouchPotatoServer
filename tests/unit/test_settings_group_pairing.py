"""SEC-004 P2 fix round: each group declares its pairing columns once.

The Definitions' "pairing columns" are the columns whose cells pair up across a
row. A provider declares them as a ``pairing`` list on its ``combined`` option,
beside ``combine``, and ``Settings`` derives them the way it derives the groups
(``combine_pairing``). ``group_misaligned(section)`` and
``group_stored_rows(section)`` take no column list, so nothing restates them.

A group declared without ``pairing`` is a programming error. It is caught here,
over every registered group, not at runtime.

Hosts are ``.invalid`` and every credential is a ``placeholder-`` string.
"""
import inspect

import pytest

from couchpotato.core.settings import Settings
from tests.helpers.combine_groups import SECTIONS, group_settings

EXPECTED = {
    'newznab': ('host', 'api_key', 'use'),
    'torrentpotato': ('host', 'pass_key', 'use', 'name'),
    'imdb': ('automation_urls_use', 'automation_urls'),
    'itunes': ('automation_urls_use', 'automation_urls'),
    'letterboxd': ('automation_urls_use', 'automation_urls'),
}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def store(settings, section, **columns):
    settings.addSection(section)
    for column, value in columns.items():
        settings.set(section, column, value)


class TestTheDeclaration:

    def test_the_derived_pairing_of_all_five_groups(self, settings):
        assert settings.combine_pairing() == EXPECTED

    def test_every_registered_group_declares_a_pairing_inside_its_columns(self, settings):
        groups = settings.combine_groups()
        assert set(groups) == set(SECTIONS)
        for section, columns in groups.items():
            pairing = settings.combine_pairing()[section]
            assert pairing, '%s declares no pairing' % section
            assert set(pairing) <= set(columns), '%s pairs a column it does not have' % section

    def test_the_methods_take_no_column_list(self):
        for method in (Settings.group_misaligned, Settings.group_stored_rows):
            assert 'pairing_columns' not in inspect.signature(method).parameters

    def test_a_group_declared_without_pairing_is_treated_as_all_columns_pairing(self, settings):
        """Not a runtime check (the test above is the check): the fallback only
        has to fail toward refusing."""
        settings.addOptions('zz_bare', {'name': 'zz_bare', 'groups': [{'options': [
            {'name': 'a', 'default': ''},
            {'name': 'b', 'default': '', 'type': 'combined', 'combine': ['a', 'b']},
        ]}]})
        store(settings, 'zz_bare', a='1,2', b='x')

        assert settings.combine_pairing()['zz_bare'] == ('a', 'b')
        assert settings.group_misaligned('zz_bare') is True


class TestTheWorkedTable:
    """Definitions, worked cases, through the real declarations."""

    def test_a_fresh_newznab_install_is_aligned_with_six_rows(self, settings):
        assert settings.group_misaligned('newznab') is False
        assert len(settings.group_stored_rows('newznab', {'use': '0'})) == 6

    def test_a_key_in_default_row_four_is_aligned(self, settings):
        store(settings, 'newznab', api_key=',,,placeholder-key-four,,')

        assert settings.group_misaligned('newznab') is False
        assert settings.group_stored_rows('newznab', {'use': '0'})[3]['api_key'] == 'placeholder-key-four'

    def test_hosts_a_b_c_with_one_key_is_misaligned(self, settings):
        store(settings, 'newznab', host='https://a.invalid,https://b.invalid,https://c.invalid',
              api_key='placeholder-key-b', use='1,1,1', extra_score='0,0,0', custom_tag=',,')

        assert settings.group_misaligned('newznab') is True

    def test_a_comma_in_a_url_seven_hosts_against_six_is_misaligned(self, settings):
        hosts = settings.get('host', section='newznab').split(',') + ['https://after-the-comma.invalid']

        store(settings, 'newznab', host=','.join(hosts))

        assert settings.group_misaligned('newznab') is True

    def test_the_wizard_written_shape_is_aligned_and_has_n_rows(self, settings):
        store(settings, 'newznab', host='https://a.invalid,https://b.invalid,https://c.invalid',
              api_key='placeholder-ka,placeholder-kb,placeholder-kc', use='1,1,1')

        assert settings.group_misaligned('newznab') is False
        assert len(settings.group_stored_rows('newznab', {'use': '0'})) == 3

    def test_the_shipped_itunes_default_is_aligned_with_two_rows(self, settings):
        assert settings.group_misaligned('itunes') is False
        assert len(settings.group_stored_rows('itunes')) == 2

    def test_imdb_and_letterboxd_as_shipped_are_aligned(self, settings):
        assert settings.group_misaligned('imdb') is False
        assert settings.group_misaligned('letterboxd') is False

    def test_a_short_automation_enabler_column_is_misaligned(self, settings):
        store(settings, 'imdb', automation_urls='https://a.invalid,https://b.invalid',
              automation_urls_use='1')

        assert settings.group_misaligned('imdb') is True

    def test_the_shipped_torrentpotato_defaults_are_aligned_with_two_rows(self, settings):
        """pass_key is `,`: two cells, so two rows, although every pairing cell is
        empty."""
        assert settings.get('pass_key', section='torrentpotato') == ','
        assert settings.group_misaligned('torrentpotato') is False
        rows = settings.group_stored_rows('torrentpotato', {'use': '0'})
        assert len(rows) == 2
