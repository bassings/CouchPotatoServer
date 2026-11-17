"""SEC-004 P6, AC-QA-17: no first-party page writes a combine column one at a time.

From this slice `settings.save` refuses those columns, so a first-party writer
that was missed would be a hard failure for a user, not a quiet one. The wizard
is the one page that names sections in code (it saves by literal and by looking a
section id up from a list), so this reads its template and checks every section
it can write against the groups the providers really register.
"""
import re
from pathlib import Path

import pytest

from tests.helpers.combine_groups import group_settings

WIZARD = Path(__file__).resolve().parents[2] / 'couchpotato' / 'ui' / 'templates' / 'wizard.html'
LITERAL_SAVE = re.compile(r"saveSetting\(\s*'([a-z_]+)'\s*,\s*'([a-z_]+)'")
LISTED_SECTION = re.compile(r"\bid:\s*'([a-z_]+)'")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as live:
        yield live


def test_the_wizard_saves_no_combine_column_by_literal(settings):
    saves = LITERAL_SAVE.findall(WIZARD.read_text(encoding='utf-8'))

    assert saves, 'the wizard no longer saves by literal; this check reads nothing'
    assert [pair for pair in saves if settings.is_combine_option(*pair)] == []


def test_no_section_id_the_wizard_loops_over_owns_a_combine_group(settings):
    """`saveSetting(tracker.id, field.name, ...)` and the client pickers take a section from a list."""
    listed = set(LISTED_SECTION.findall(WIZARD.read_text(encoding='utf-8')))

    assert listed, 'the wizard no longer lists sections by id; this check reads nothing'
    assert listed & set(settings.combine_groups()) == set()


def test_the_wizard_still_writes_newznab_only_as_a_group():
    html = WIZARD.read_text(encoding='utf-8')

    assert 'settings.save_group' in html
