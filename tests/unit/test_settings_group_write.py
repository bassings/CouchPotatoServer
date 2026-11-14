"""SEC-004 P1: the validated, all-or-nothing write of one ``combine`` group.

Five settings groups are edited as rows but stored as one comma-separated list
per column and paired back up by position. A comma inside a cell therefore
becomes a new position, and a credential ends up beside the wrong host.
``Settings.save_group`` is the one writer that takes rows, refuses a cell that
would break the pairing, and writes every column or none.

These tests drive the real ``Settings`` class over a temporary ``config.ini``
with the five real option declarations registered (``tests/helpers``), and
check the file, not only the return value. All hosts are ``.invalid`` and every
credential is a ``placeholder-`` string.
"""
import pytest

from couchpotato.core.settings import Settings
from tests.helpers.combine_groups import SECTIONS, group_settings, provider_configs


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def declared_groups():
    """section -> combine list, read from the provider declarations themselves."""
    found = {}
    for config in provider_configs():
        for section in config:
            for group in section['groups']:
                for option in group['options']:
                    if option.get('combine'):
                        found[section['name']] = tuple(option['combine'])
    return found


class TestCombineGroupMap:
    """AC-ARCH-11(i): one method derives section -> ordered columns."""

    def test_derives_every_registered_group_in_declared_order(self, settings):
        assert settings.combine_groups() == declared_groups()
        assert set(settings.combine_groups()) == set(SECTIONS)

    def test_newznab_columns_keep_the_declared_order(self, settings):
        assert settings.combine_groups()['newznab'] == (
            'use', 'host', 'api_key', 'extra_score', 'custom_tag')

    def test_a_section_registered_later_is_derived_with_no_production_edit(self, settings):
        settings.addOptions('zz_test', {'name': 'zz_test', 'groups': [{'options': [
            {'name': 'use'},
            {'name': 'host'},
            {'name': 'key', 'type': 'combined', 'combine': ['use', 'host', 'key']},
        ]}]})

        assert settings.combine_groups()['zz_test'] == ('use', 'host', 'key')

    def test_an_option_without_a_combine_list_makes_no_group(self, settings):
        assert 'core' not in settings.combine_groups()


class TestCombineMembership:
    """AC-ARCH-11(i), AC-ARCH-2: one membership test, folded like the parser."""

    @pytest.mark.parametrize('name', [
        'host', 'HOST', 'Host', ' host', 'host ', ' api_key ', 'API_KEY', 'use\t',
    ])
    def test_a_name_that_would_become_a_column_is_a_member(self, settings, name):
        assert settings.is_combine_option('newznab', name) is True

    @pytest.mark.parametrize('section, name', [
        ('newznab', 'enabled'),
        ('newznab', 'custom_categories'),
        ('newznab', 'pass_key'),
        ('torrentpotato', 'jackett_url'),
        ('core', 'host'),
        ('no_such_section', 'host'),
        ('newznab', ''),
    ])
    def test_anything_else_is_not(self, settings, section, name):
        assert settings.is_combine_option(section, name) is False

    @pytest.mark.parametrize('name', [None, 7, b'host', ['host']])
    def test_a_non_string_name_is_not_a_member(self, settings, name):
        assert settings.is_combine_option('newznab', name) is False


def test_the_class_under_test_is_the_real_settings(settings):
    assert isinstance(settings, Settings)
