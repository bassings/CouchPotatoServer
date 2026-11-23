"""SEC-004 P3: the settings read carries each combine group's state.

The Settings page and the wizard never re-derive alignment in script
(Definitions, "Pairing columns"): the read the page already makes carries, for
every registered combine group, whether it is misaligned and how many rows it
has. Both come from the methods the spec names, `group_misaligned(section)` and
the Definitions' row count (`group_stored_rows`), and nothing here names a
section or a column.

Hosts are ``.invalid`` and every credential is a ``placeholder-`` string.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
import seed_e2e_data  # noqa: E402

from couchpotato.core.settings import Settings  # noqa: E402
from tests.helpers.combine_groups import SECTIONS, group_settings  # noqa: E402


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def state_of(tmp_path, monkeypatch, fixture):
    with group_settings(tmp_path, monkeypatch, stored=seed_e2e_data.config_fixture(fixture)) as settings:
        return settings.combine_state()


def test_every_registered_group_has_an_entry_and_nothing_else(settings):
    assert set(settings.combine_state()) == set(SECTIONS)
    assert set(settings.combine_state()) == set(settings.combine_groups())


def flag_and_rows(entry):
    """An entry without the SEC-006 token, which is tested in test_settings_group_token.py."""
    return {key: value for key, value in entry.items() if key != 'token'}


def test_an_entry_is_exactly_the_flag_and_the_row_count_and_a_token_only_for_a_credential_group(settings):
    for section, entry in settings.combine_state().items():
        assert flag_and_rows(entry).keys() == {'misaligned', 'rows'}
        assert ('token' in entry) == (section in settings.combine_secrets())


def test_the_read_view_includes_it(settings):
    assert settings.view()['combine_state'] == settings.combine_state()


def test_a_fresh_install_reads_aligned_with_the_rows_the_definitions_give(settings):
    state = settings.combine_state()

    assert flag_and_rows(state['newznab']) == {'misaligned': False, 'rows': 6}
    assert flag_and_rows(state['torrentpotato']) == {'misaligned': False, 'rows': 2}
    assert state['itunes'] == {'misaligned': False, 'rows': 2}
    assert state['imdb'] == {'misaligned': False, 'rows': 1}


def test_a_misaligned_stored_group_reads_misaligned_and_aligned_ones_do_not(tmp_path, monkeypatch):
    state = state_of(tmp_path, monkeypatch, 'all_groups_misaligned')

    assert {section: entry['misaligned'] for section, entry in state.items()} == dict.fromkeys(SECTIONS, True)
    assert state['newznab']['rows'] == 3


def test_the_wizard_written_shape_is_aligned_with_surplus_default_cells_not_counted(tmp_path, monkeypatch):
    state = state_of(tmp_path, monkeypatch, 'newznab_wizard_written')

    assert flag_and_rows(state['newznab']) == {'misaligned': False, 'rows': 3}


def test_the_flag_is_whatever_group_misaligned_says(settings, monkeypatch):
    """Not re-derived: a stub that disagrees with the stored data wins."""
    asked = []

    def stub(self, section):
        asked.append(section)
        return True

    monkeypatch.setattr(Settings, 'group_misaligned', stub)

    state = settings.combine_state()

    assert all(entry['misaligned'] is True for entry in state.values())
    assert sorted(asked) == sorted(SECTIONS)


def test_the_row_count_is_whatever_group_stored_rows_says(settings, monkeypatch):
    monkeypatch.setattr(Settings, 'group_stored_rows', lambda self, section, short_cells=None: [{}] * 7)

    assert all(entry['rows'] == 7 for entry in settings.combine_state().values())


def test_a_read_overlapping_a_group_write_is_one_snapshot(settings):
    """`view()` returns the values AND the row count; a read that lands between two
    column writes would pair a new host with an old key beside an aligned count."""
    import threading

    from tests.helpers.combine_groups import placeholder_rows

    rows = placeholder_rows(settings.combine_groups()['newznab'], 3, tag='new')
    original_set = settings.set
    after_first_column = threading.Event()
    proceed = threading.Event()
    calls = []

    def paused_set(section, option, value):
        original_set(section, option, value)
        calls.append(option)
        if len(calls) == 1:
            after_first_column.set()
            proceed.wait(10)

    settings.set = paused_set
    seen = {}
    writer = threading.Thread(target=lambda: settings.save_group('newznab', rows))
    reader = threading.Thread(target=lambda: seen.update(settings.view()))
    try:
        writer.start()
        assert after_first_column.wait(10)
        reader.start()
        reader.join(0.5)
    finally:
        proceed.set()
        writer.join(10)
        reader.join(10)
        settings.set = original_set

    values = seen['values']['newznab']
    new_cells = {column: ','.join(row[column] for row in rows) for column in rows[0]}
    changed = [column for column in new_cells if values[column] == new_cells[column]]
    assert changed in ([], list(new_cells)), 'the read mixed old and new columns: %s' % changed


def test_reading_the_state_writes_nothing(settings):
    before = Path(settings.file).read_bytes()

    settings.view()
    settings.combine_state()

    assert Path(settings.file).read_bytes() == before
