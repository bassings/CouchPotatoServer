"""SEC-004 P2: reading a stored combine group back as rows, without naming a section.

``Settings.group_cells`` and ``Settings.group_stored_rows`` apply the
Definitions (Cells, Row count) and AC-DATA-13's row derivation to ANY registered
group. Neither names a section or a column: the caller states which columns pair
rows up. A synthetic section ``zz_test`` is registered with no production code
edited, which is what makes a literal in ``settings.py`` fail here.

Hosts are ``.invalid`` and every credential is a ``placeholder-`` string.
"""
import pytest

from couchpotato.core.settings import unstorable_cell
from tests.helpers.combine_groups import group_settings

PAIRING = ('host', 'key', 'use')


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        live.addOptions('zz_test', {'name': 'zz_test', 'groups': [{'options': [
            {'name': 'use', 'default': ''},
            {'name': 'host', 'default': ''},
            {'name': 'weight', 'default': '5'},
            {'name': 'tag', 'default': ''},
            {'name': 'key', 'default': ',', 'type': 'combined',
             'combine': ['use', 'host', 'key', 'weight', 'tag']},
        ]}]})
        yield live


def store(settings, **columns):
    settings.addSection('zz_test')
    for column, value in columns.items():
        settings.set('zz_test', column, value)


class TestCells:

    def test_a_column_is_its_stored_value_split_on_a_comma_and_nothing_is_dropped(self, settings):
        store(settings, host='a,,c,', key='', use=',', weight='5', tag=' x ,')

        cells = settings.group_cells('zz_test')

        assert cells['host'] == ['a', '', 'c', '']
        assert cells['tag'] == [' x ', ''], 'a cell is not trimmed'

    def test_an_empty_stored_value_is_one_empty_cell(self, settings):
        store(settings, host='', key='', use='', weight='', tag='')

        assert settings.group_cells('zz_test')['host'] == ['']

    def test_an_option_that_was_never_stored_is_one_empty_cell(self, settings):
        store(settings, host='a', key='k', use='1', weight='1', tag='t')
        settings.p.remove_option('zz_test', 'tag')

        assert settings.group_cells('zz_test')['tag'] == ['']


class TestStoredRows:

    def rows(self, settings):
        return settings.group_stored_rows('zz_test', PAIRING, {'use': '0'})

    def test_aligned_columns_become_rows_in_order(self, settings):
        store(settings, host='a,b', key='ka,kb', use='1,0', weight='7,8', tag='t1,t2')

        assert self.rows(settings) == [
            {'use': '1', 'host': 'a', 'key': 'ka', 'weight': '7', 'tag': 't1'},
            {'use': '0', 'host': 'b', 'key': 'kb', 'weight': '8', 'tag': 't2'},
        ]

    def test_the_row_count_is_the_largest_pairing_column_so_a_trailing_blank_row_is_a_row(
            self, settings):
        store(settings, host='a,', key='ka,', use='1,0', weight='7,8', tag='t1,t2')

        assert len(self.rows(settings)) == 2

    def test_a_short_use_column_supplies_the_stated_cell_and_a_short_key_an_empty_one(
            self, settings):
        store(settings, host='a,b', key='ka', use='1', weight='7,8', tag='t1,t2')

        rows = self.rows(settings)

        assert rows[1]['use'] == '0'
        assert rows[1]['key'] == ''

    def test_a_short_non_pairing_column_supplies_its_declared_default(self, settings):
        store(settings, host='a,b', key='ka,kb', use='1,1', weight='7', tag='t1')

        rows = self.rows(settings)

        assert rows[1]['weight'] == '5', 'the declared default of weight'
        assert rows[1]['tag'] == '', 'the declared default of tag is empty'

    def test_surplus_cells_in_a_non_pairing_column_are_not_rows(self, settings):
        store(settings, host='a', key='ka', use='1', weight='7,5,5', tag='t,,')

        assert len(self.rows(settings)) == 1

    def test_nothing_stored_is_one_row_of_empty_cells(self, settings):
        store(settings, host='', key='', use='', weight='', tag='')

        assert len(self.rows(settings)) == 1


class TestTheWritersOwnCellTest:
    """The sync skips an indexer that the writer would refuse, by asking the
    writer's own test rather than repeating it."""

    @pytest.mark.parametrize('cell', ['A, B', ',', 'a\nb', 'a\rb', 'a\tb', 'a\x00b',
                                      '\ud800x', None, 5, ['a']])
    def test_an_unstorable_cell_is_named(self, cell):
        assert unstorable_cell(cell) is not None

    @pytest.mark.parametrize('cell', ['', 'Alpha', ' spaced ', 'https://h.invalid/a?b=c&d=e',
                                      'café テスト'])
    def test_a_storable_cell_is_not(self, cell):
        assert unstorable_cell(cell) is None
