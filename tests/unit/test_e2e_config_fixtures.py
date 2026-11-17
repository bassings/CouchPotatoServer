"""The named starting configurations the E2E suite seeds (SEC-004 AC-QA-10).

A starting state for a misaligned group cannot be created through the API once
per-column saves are refused, so each is a named fixture written into the worker's
`config.ini` before its server starts. These tests do not trust the fixtures'
own descriptions: each one is loaded into the REAL `Settings` with the five real
provider declarations, and the classification the spec's Definitions give it is
read back from the real `group_misaligned` and `group_stored_rows`. A fixture that
was gentler than its name (an "unaligned" group that is in fact aligned) would
make the E2E that depends on it pass for the wrong reason.
"""
import configparser
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / 'libs'))
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
sys.path.insert(0, str(REPO_ROOT))
import seed_e2e_data  # noqa: E402
from tests.helpers.combine_groups import group_settings  # noqa: E402

# (fixture, section) -> (misaligned, row count), straight from the Definitions'
# worked table and the criteria that name each fixture.
CLASSIFICATION = {
    ('fresh_defaults', 'newznab'): (False, 6),
    ('fresh_defaults', 'torrentpotato'): (False, 2),
    ('fresh_defaults', 'itunes'): (False, 2),
    ('fresh_defaults', 'imdb'): (False, 1),
    ('newznab_aligned', 'newznab'): (False, 3),
    ('newznab_wizard_written', 'newznab'): (False, 3),
    ('newznab_key_in_row_four', 'newznab'): (False, 6),
    ('newznab_misaligned_key_short', 'newznab'): (True, 3),
    ('newznab_misaligned_use_short', 'newznab'): (True, 3),
    ('newznab_untrimmed', 'newznab'): (False, 2),
    ('newznab_legacy_bytes', 'newznab'): (False, 2),
    ('newznab_two_stored', 'newznab'): (False, 2),
    ('newznab_interleaved', 'newznab'): (False, 5),
    ('newznab_hostless', 'newznab'): (False, 4),
    ('newznab_hostile_cells', 'newznab'): (False, 3),
    ('newznab_sentinels', 'newznab'): (False, 2),
    ('itunes_shipped', 'itunes'): (False, 2),
    ('torrentpotato_aligned', 'torrentpotato'): (False, 3),
    ('torrentpotato_misaligned', 'torrentpotato'): (True, 3),
    ('torrentpotato_use_short', 'torrentpotato'): (True, 3),
    ('all_groups_aligned', 'newznab'): (False, 3),
    ('all_groups_aligned', 'torrentpotato'): (False, 3),
    ('all_groups_aligned', 'imdb'): (False, 2),
    ('all_groups_aligned', 'itunes'): (False, 2),
    ('all_groups_aligned', 'letterboxd'): (False, 2),
    ('all_groups_misaligned', 'newznab'): (True, 3),
    ('all_groups_misaligned', 'torrentpotato'): (True, 3),
    ('all_groups_misaligned', 'imdb'): (True, 3),
    ('all_groups_misaligned', 'itunes'): (True, 3),
    ('all_groups_misaligned', 'letterboxd'): (True, 3),
}


@pytest.mark.parametrize(('name', 'section'), sorted(CLASSIFICATION))
def test_the_fixture_is_classified_as_its_definitions_row_says(name, section, tmp_path, monkeypatch):
    misaligned, rows = CLASSIFICATION[(name, section)]
    stored = seed_e2e_data.config_fixture(name)

    with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
        assert settings.group_misaligned(section) is misaligned
        assert len(settings.group_stored_rows(section)) == rows


def test_the_legacy_fixture_really_stores_bytes_literals(tmp_path):
    """Without this the fixture could quietly be a plain one and prove nothing."""
    stored = seed_e2e_data.config_fixture('newznab_legacy_bytes')['newznab']

    assert all(value.startswith("b'") and value.endswith("'") for value in stored.values())


def test_the_untrimmed_fixture_has_a_space_after_a_separator():
    stored = seed_e2e_data.config_fixture('newznab_untrimmed')['newznab']

    assert ', ' in stored['host']


def _newznab_rows(name):
    """A newznab fixture as rows of cells, straight from its stored columns."""
    stored = seed_e2e_data.config_fixture(name)['newznab']
    columns = {column: value.split(',') for column, value in stored.items()}
    return [{column: cells[index] for column, cells in columns.items()} for index in range(len(columns['host']))]


def test_the_interleaved_fixture_has_hidden_rows_between_the_stored_indexers():
    rows = _newznab_rows('newznab_interleaved')

    shown = [bool(row['host'] and row['api_key']) for row in rows]
    assert shown == [False, True, False, True, False]


def test_the_interleaved_fixture_gives_every_row_its_own_cells_in_every_column():
    """A shifted column would otherwise land on an identical neighbour and go unseen."""
    rows = _newznab_rows('newznab_interleaved')

    for column in ('use', 'host', 'extra_score', 'custom_tag'):
        assert len({row[column] for row in rows}) > 1, column
    assert len({row['custom_tag'] for row in rows}) == len(rows)
    assert len({row['extra_score'] for row in rows}) == len(rows)


def test_the_two_stored_indexers_differ_in_every_column():
    first, second = _newznab_rows('newznab_two_stored')

    assert [first[column] != second[column] for column in first] == [True] * len(first)


def test_the_hostless_fixture_holds_a_key_with_no_host_between_stored_indexers():
    rows = _newznab_rows('newznab_hostless')

    hostless = [row for row in rows if not row['host'] and row['api_key']]
    stored = [row for row in rows if row['host'] and row['api_key']]
    assert len(hostless) == 1
    assert len(stored) == 2
    assert rows.index(stored[0]) < rows.index(hostless[0]) < rows.index(stored[1])


def test_the_hostile_fixture_carries_each_character_the_wizard_must_not_alter():
    stored = ' '.join(seed_e2e_data.config_fixture('newznab_hostile_cells')['newznab'].values())

    for fragment in ('%', '+', '&', '=', '%2C'):
        assert fragment in stored, fragment
    cells = seed_e2e_data.config_fixture('newznab_hostile_cells')['newznab']['api_key'].split(',')
    assert any(cell != cell.strip() for cell in cells[1:-1])


def test_an_unknown_name_is_refused():
    with pytest.raises(ValueError, match='unknown config fixture'):
        seed_e2e_data.config_fixture('no_such_fixture')


def test_a_label_after_a_hash_names_the_same_content():
    """A writing test owns its fixture value alone (AC-QA-10), so many tests need
    many distinct values for one shape. The label makes the value distinct; the
    content is single-sourced."""
    assert seed_e2e_data.config_fixture('newznab_aligned#a-test') == seed_e2e_data.config_fixture('newznab_aligned')


def test_a_fixture_is_returned_as_a_copy():
    seed_e2e_data.config_fixture('newznab_aligned')['newznab']['host'] = 'mutated'

    assert seed_e2e_data.config_fixture('newznab_aligned')['newznab']['host'] != 'mutated'


class TestApplyingAFixture:

    def test_the_fixture_is_written_to_config_ini_before_the_server_starts(self, tmp_path):
        data_dir = tmp_path / '.e2e-fixture-target'

        seed_e2e_data.apply_config_fixture(str(data_dir), 'newznab_misaligned_key_short')

        parser = configparser.RawConfigParser()
        parser.read(data_dir / 'config.ini', encoding='utf-8')
        assert parser.get('newznab', 'api_key').count(',') == 1
        assert parser.get('newznab', 'host').count(',') == 2

    def test_a_directory_that_is_not_disposable_is_refused_and_left_alone(self, tmp_path):
        data_dir = tmp_path / 'real-library'
        data_dir.mkdir()

        with pytest.raises(ValueError, match='refusing to write a config fixture'):
            seed_e2e_data.apply_config_fixture(str(data_dir), 'newznab_aligned')

        assert os.listdir(data_dir) == []

    def test_other_sections_already_in_the_file_are_kept(self, tmp_path):
        data_dir = tmp_path / '.e2e-fixture-keep'
        data_dir.mkdir()
        (data_dir / 'config.ini').write_text('[core]\nport = 5199\n', encoding='utf-8')

        seed_e2e_data.apply_config_fixture(str(data_dir), 'newznab_aligned')

        parser = configparser.RawConfigParser()
        parser.read(data_dir / 'config.ini', encoding='utf-8')
        assert parser.get('core', 'port') == '5199'
        assert parser.has_section('newznab')

    def test_the_command_line_rejects_an_unknown_name_before_seeding_anything(self, tmp_path, capsys):
        data_dir = tmp_path / '.e2e-cli'

        with pytest.raises(SystemExit) as exit_info:
            seed_e2e_data.main(['--data_dir=%s' % data_dir, '--config-fixture=no_such_fixture'])

        assert exit_info.value.code == 2
        assert not data_dir.exists()
        assert 'unknown config fixture' in capsys.readouterr().err
