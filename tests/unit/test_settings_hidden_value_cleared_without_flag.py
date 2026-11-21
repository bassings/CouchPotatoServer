"""SEC-005 P1, AC-SEC-16: a value a hidden option held before its flag existed is emptied once.

A hidden option is written only by the server. A config.ini from before the
option was declared can hold a value for it that a caller planted, and nothing
that wrote it was the server. The first ``registerDefaults`` that declares the
hidden flag finds no flag in the loaded file and empties that value, in memory
only; a file that already has the flag (written by a release that knew the
option) is left exactly as it is. The rule is generic: these tests use an
unrelated plugin and real files.
"""
import hashlib
import logging
from pathlib import Path

import pytest

from couchpotato.core.settings import Settings
from tests.helpers.combine_groups import LogCapture

pytestmark = pytest.mark.unit

SECTION = 'unrelated_plugin'
OPTION = 'server_only_note'
FLAG = OPTION + '_internal_meta'
PLANTED = 'planted-by-somebody'
DECLARED = {OPTION: {'default': '', 'ui-meta': 'hidden'}, 'plain': {'default': 'x'}}
HIDDEN = 'hidden'


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(Settings, 'options', {})
    monkeypatch.setattr(Settings, 'types', {})


def line(name, value):
    return '%s = %s' % (name, value)


def write(tmp_path, lines):
    path = tmp_path / 'config.ini'
    path.write_text('[%s]\n%s\n' % (SECTION, '\n'.join(lines)), encoding='utf-8')
    return path


def load(path, passes=1):
    settings = Settings()
    settings.setFile(str(path))
    for _ in range(passes):
        settings.registerDefaults(SECTION, DECLARED, save=False)
    return settings


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def held(settings):
    return settings.p.get(SECTION, OPTION)


@pytest.mark.parametrize('name', [OPTION, OPTION.upper()], ids=['as declared', 'upper case'])
def test_a_value_with_no_flag_in_the_file_is_emptied_in_memory(isolated, tmp_path, name):
    # Both spellings are one case: the parser folds an option name when it reads
    # the file, so an older release's upper-case save reaches this code as the
    # lower-case name. The row only pins that the fold happens before the check.
    path = write(tmp_path, [line(name, PLANTED)])

    settings = load(path)

    assert held(settings) == ''


def test_the_clear_is_memory_only_and_the_next_save_persists_it(isolated, tmp_path):
    path = write(tmp_path, [line(OPTION, PLANTED)])
    before = digest(path)

    settings = load(path)

    assert digest(path) == before
    settings.save()
    assert PLANTED not in path.read_text(encoding='utf-8')
    assert line(FLAG, HIDDEN) in path.read_text(encoding='utf-8')


def test_a_value_is_kept_when_the_flag_is_already_in_the_file(isolated, tmp_path):
    path = write(tmp_path, [line(OPTION, PLANTED), line(FLAG, HIDDEN)])

    assert held(load(path)) == PLANTED


def test_a_value_is_kept_when_the_flag_in_the_file_has_another_value(isolated, tmp_path):
    """Only the flag's presence decides; the flag itself is then put right."""
    path = write(tmp_path, [line(OPTION, PLANTED), line(FLAG, 'rw')])

    settings = load(path)

    assert held(settings) == PLANTED
    assert settings.p.get(SECTION, FLAG) == HIDDEN


def test_a_second_pass_in_the_same_process_does_not_clear_a_value_set_since(isolated, tmp_path):
    path = write(tmp_path, [])
    settings = load(path)
    settings.set_internal(SECTION, OPTION, 'server-wrote-this')

    settings.registerDefaults(SECTION, DECLARED, save=False)

    assert held(settings) == 'server-wrote-this'


def test_a_fresh_install_gets_an_empty_value_and_the_flag(isolated, tmp_path):
    settings = load(tmp_path / 'config.ini')

    assert held(settings) == ''
    assert settings.p.get(SECTION, FLAG) == HIDDEN


def test_a_declared_default_on_a_fresh_install_is_not_a_planted_value(isolated, tmp_path):
    settings = Settings()
    settings.setFile(str(tmp_path / 'config.ini'))

    settings.registerDefaults(SECTION, {OPTION: {'default': 'declared-default', 'ui-meta': 'hidden'}}, save=False)

    assert held(settings) == 'declared-default'


def test_other_options_of_the_section_are_untouched(isolated, tmp_path):
    path = write(tmp_path, [line(OPTION, PLANTED), 'plain = kept-value'])

    assert load(path).p.get(SECTION, 'plain') == 'kept-value'


def test_an_option_that_is_not_hidden_is_never_cleared(isolated, tmp_path):
    path = write(tmp_path, ['plain = kept-value'])
    settings = Settings()
    settings.setFile(str(path))

    settings.registerDefaults(SECTION, {'plain': {'default': 'x', 'ui-meta': 'ro'}}, save=False)

    assert settings.p.get(SECTION, 'plain') == 'kept-value'


def test_the_clear_is_logged_once_naming_the_option_and_never_the_value(isolated, tmp_path):
    path = write(tmp_path, [line(OPTION, PLANTED)])

    with LogCapture() as logs:
        load(path, passes=2)

    cleared = [r for r in logs.records if r.name.startswith('couchpotato') and 'Cleared' in r.getMessage()]
    assert len(cleared) == 1
    assert cleared[0].levelno == logging.INFO
    assert SECTION in cleared[0].getMessage()
    assert OPTION in cleared[0].getMessage()
    assert PLANTED not in logs.text()


@pytest.mark.parametrize('lines', [[], [line(OPTION, '')], [line(OPTION, PLANTED), line(FLAG, HIDDEN)]],
                         ids=['nothing stored', 'already empty', 'flag present'])
def test_a_start_with_nothing_to_clear_logs_nothing(isolated, tmp_path, lines):
    path = write(tmp_path, lines)

    with LogCapture() as logs:
        load(path)

    assert [r for r in logs.records if 'Cleared' in r.getMessage()] == []


def test_a_failing_clear_is_warned_once_not_retried_and_never_blocks_the_start(isolated, tmp_path, monkeypatch):
    """The pinned consequence: the flag is still declared, the planted value stays, and no
    later start retries (the flag is in the file by then). An undeclared flag would be worse."""
    path = write(tmp_path, [line(OPTION, PLANTED)])
    settings = Settings()
    settings.setFile(str(path))
    real_set = settings.p.set

    def failing_set(section, option, value):
        if option == OPTION and value == '':
            raise RuntimeError('the clear failed')
        return real_set(section, option, value)

    monkeypatch.setattr(settings.p, 'set', failing_set)

    with LogCapture() as logs:
        settings.registerDefaults(SECTION, DECLARED, save=False)

    warnings = [r for r in logs.records if r.name.startswith('couchpotato') and r.levelno == logging.WARNING]
    assert [r.getMessage().split('] ', 1)[-1] for r in warnings] == [
        'Could not clear "%s.%s" (RuntimeError)' % (SECTION, OPTION)]
    assert settings.p.get(SECTION, FLAG) == HIDDEN
    assert settings.p.get(SECTION, 'plain') == 'x'
    assert held(settings) == PLANTED
    settings.save()
    assert load(path).p.get(SECTION, OPTION) == PLANTED
