"""SEC-005 P1, AC-SEC-16: a binding planted before this release is emptied once, at first start.

Releases without the binding option accept ``torrentpotato.jackett_key_binding``
as an ordinary option name, and ``registerDefaults`` keeps an existing value, so
a planted value would survive the upgrade and be trusted as a binding nobody
entered a key for. These tests drive the real ``registerDefaults`` over real
``config.ini`` files with the real torrentpotato declaration. The generic rule is
proved on an unrelated plugin in ``tests/unit/test_settings_hidden_value_cleared_without_flag.py``.

Hosts are ``.invalid`` and every key is a ``placeholder-`` string.
"""
import configparser
import logging

import pytest

from couchpotato.core.settings import Settings
from tests.helpers.combine_groups import LogCapture, group_settings, register_providers
from tests.helpers.jackett_binding import (
    BINDING_FLAG_OPTION,
    BINDING_OPTION,
    KEY_OPTION,
    PLACEHOLDER_KEY,
    SECTION,
    URL_OPTION,
    jackett_world,
    on_disk,
)
from tests.integration.test_jackett_binding_writer import save

pytestmark = pytest.mark.integration

ADDRESS = 'http://jackett-a.local:9117'
PLANTED = 'http://planted.invalid:9117'
OLD_FILE = {SECTION: {URL_OPTION: ADDRESS, KEY_OPTION: PLACEHOLDER_KEY, BINDING_OPTION: PLANTED}}
SAME_AS_ADDRESS = {SECTION: {URL_OPTION: ADDRESS, KEY_OPTION: PLACEHOLDER_KEY, BINDING_OPTION: ADDRESS}}


def start_again(settings):
    """A second start on the same file, as the loader does it: load, register, one save."""
    again = Settings()
    again.setFile(settings.file)
    register_providers(again)
    again.save()
    return again


def cleared_lines(logs):
    return [r for r in logs.records if r.name.startswith('couchpotato') and 'Cleared' in r.getMessage()]


@pytest.mark.parametrize('stored', [OLD_FILE, SAME_AS_ADDRESS], ids=['a planted address', 'the saved address'])
def test_a_file_from_before_the_release_loads_with_an_empty_binding(tmp_path, monkeypatch, stored):
    """(a) in memory, and in the file after the save that follows the start."""
    with group_settings(tmp_path, monkeypatch, stored=stored) as settings:
        assert settings.p.get(SECTION, BINDING_OPTION) == ''
        assert on_disk(settings, BINDING_OPTION) == ''
        assert on_disk(settings, KEY_OPTION) == PLACEHOLDER_KEY
        assert on_disk(settings, URL_OPTION) == ADDRESS


def test_a_planted_binding_is_emptied_again_when_a_pre_release_backup_is_restored(tmp_path, monkeypatch):
    """(c) the restored file has no flag, so the same start clears it."""
    with jackett_world(tmp_path, monkeypatch) as (settings, client, _):
        save(client, URL_OPTION, ADDRESS)
        save(client, KEY_OPTION, PLACEHOLDER_KEY)
        backup = configparser.RawConfigParser()
        backup.read(settings.file, encoding='utf-8')
        backup.remove_option(SECTION, BINDING_FLAG_OPTION)
        backup.set(SECTION, BINDING_OPTION, PLANTED)
        with open(settings.file, 'w', encoding='utf-8') as handle:
            backup.write(handle)

        again = start_again(settings)

        assert again.p.get(SECTION, BINDING_OPTION) == ''
        assert on_disk(again, BINDING_OPTION) == ''


def test_a_file_written_by_this_release_keeps_its_binding_through_two_starts(tmp_path, monkeypatch):
    """(b) the flag is in the file after the first start's save, so nothing is cleared."""
    with jackett_world(tmp_path, monkeypatch) as (settings, client, _):
        save(client, URL_OPTION, ADDRESS)
        save(client, KEY_OPTION, PLACEHOLDER_KEY)
        assert on_disk(settings, BINDING_OPTION) == ADDRESS

        with LogCapture() as logs:
            first = start_again(settings)
            second = start_again(first)

        assert on_disk(second, BINDING_OPTION) == ADDRESS
        assert second.p.get(SECTION, BINDING_OPTION) == ADDRESS
        assert cleared_lines(logs) == []


def test_the_flag_reaches_the_file_with_the_first_save_of_a_fresh_start(tmp_path, monkeypatch):
    with group_settings(tmp_path, monkeypatch) as settings:
        assert on_disk(settings, BINDING_FLAG_OPTION) == 'hidden'
        assert on_disk(settings, BINDING_OPTION) == ''


def test_rolling_back_and_forward_keeps_a_bound_key_bound(tmp_path, monkeypatch):
    """(d) an older release rewrites the file but leaves the flag line, so the binding survives."""
    with jackett_world(tmp_path, monkeypatch) as (settings, client, _):
        save(client, URL_OPTION, ADDRESS)
        save(client, KEY_OPTION, PLACEHOLDER_KEY)
        older = configparser.RawConfigParser()
        older.read(settings.file, encoding='utf-8')
        older.set(SECTION, 'extra_score', '7')
        with open(settings.file, 'w', encoding='utf-8') as handle:
            older.write(handle)

        again = start_again(settings)

        assert again.p.get(SECTION, BINDING_OPTION) == ADDRESS
        assert on_disk(again, BINDING_OPTION) == ADDRESS


def test_the_clear_is_logged_once_without_the_value_and_a_clean_start_logs_nothing(tmp_path, monkeypatch):
    """(e)"""
    with LogCapture() as logs:
        with group_settings(tmp_path, monkeypatch, stored=OLD_FILE) as settings:
            start_again(settings)

    lines = cleared_lines(logs)
    assert len(lines) == 1
    assert lines[0].levelno == logging.INFO
    assert BINDING_OPTION in lines[0].getMessage()
    assert SECTION in lines[0].getMessage()
    for secret in (PLANTED, 'planted.invalid', ADDRESS, PLACEHOLDER_KEY):
        assert secret not in logs.text()

    (tmp_path / 'again').mkdir()
    with LogCapture() as quiet:
        with group_settings(tmp_path / 'again', monkeypatch) as fresh:
            start_again(fresh)

    assert cleared_lines(quiet) == []
