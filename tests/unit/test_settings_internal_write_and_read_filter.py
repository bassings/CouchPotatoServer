"""SEC-005 P1: two provider-neutral pieces of ``Settings``.

``getValues`` omits every option whose access flag says it is not readable
(AC-ARCH-3), for any section; and ``set_internal`` is the one way the server
writes such an option, in memory only (AC-ARCH-4). Both drive a real
``Settings`` over a temporary file with options registered through the real
``registerDefaults``; neither names Jackett or the torrentpotato section.
"""
import hashlib
from pathlib import Path

import pytest

from couchpotato.core.settings import Settings
from couchpotato.environment import Env

pytestmark = pytest.mark.unit

SECTION = 'unrelated_plugin'
HIDDEN_VALUE = 'hidden-value'
HIDDEN = 'secret_note'
READ_ONLY = 'locked'
HIDDEN_FLAG = 'hidden'
FLAG_NAME = 'secret_note_internal_meta'


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, 'options', {})
    monkeypatch.setattr(Settings, 'types', {})
    instance = Settings()
    instance.setFile(str(tmp_path / 'config.ini'))
    instance.registerDefaults(SECTION, {
        'shown': {'default': 'visible-value'},
        HIDDEN: {'default': HIDDEN_VALUE, 'ui-meta': HIDDEN_FLAG},
        READ_ONLY: {'default': 'ro-value', 'ui-meta': 'ro'},
        'open': {'default': 'rw-value', 'ui-meta': 'rw'},
    })
    monkeypatch.setattr(Env, '_settings', instance)
    monkeypatch.setattr(Env, '_softchroot', _NoChroot(), raising=False)
    return instance


class _NoChroot:
    def abs2chroot(self, value):
        return value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TestTheReadOmitsWhatIsNotReadable:

    def test_a_hidden_option_in_any_section_is_not_returned(self, settings):
        values = settings.getValues()

        assert HIDDEN not in values[SECTION]

    def test_the_hidden_value_does_not_appear_anywhere_in_the_read(self, settings):
        assert HIDDEN_VALUE not in repr(settings.getValues())

    def test_readable_options_are_returned_as_before(self, settings):
        values = settings.getValues()[SECTION]

        assert values['shown'] == 'visible-value'
        assert values[READ_ONLY] == 'ro-value'
        assert values['open'] == 'rw-value'

    def test_the_view_reports_the_same(self, settings):
        assert HIDDEN not in settings.view()['values'][SECTION]


class TestSetInternal:

    def test_it_writes_a_hidden_option_in_memory_and_not_to_the_file(self, settings):
        settings.save()
        before = digest(settings.file)

        settings.set_internal(SECTION, HIDDEN, 'server-wrote-this')

        assert settings.p.get(SECTION, HIDDEN) == 'server-wrote-this'
        assert digest(settings.file) == before

    def test_set_refuses_the_same_option(self, settings):
        """The bypass is for the server only: the ordinary writer still refuses it."""
        settings.set(SECTION, HIDDEN, 'user-wrote-this')

        assert settings.p.get(SECTION, HIDDEN) == HIDDEN_VALUE

    def test_it_writes_a_read_only_option_too(self, settings):
        settings.set_internal(SECTION, READ_ONLY, 'changed')

        assert settings.p.get(SECTION, READ_ONLY) == 'changed'

    @pytest.mark.parametrize('name', [FLAG_NAME, 'SECRET_NOTE_INTERNAL_META',
                                      ' secret_note_internal_meta'])
    def test_it_still_refuses_an_access_flag(self, settings, name):
        settings.set_internal(SECTION, name, 'rw')

        assert settings.p.get(SECTION, FLAG_NAME) == HIDDEN_FLAG

    def test_it_never_saves_the_file_itself(self, settings, monkeypatch):
        calls = []
        monkeypatch.setattr(settings, 'save', lambda: calls.append(1))

        settings.set_internal(SECTION, HIDDEN, 'x')

        assert calls == []

    def test_it_creates_a_missing_section_instead_of_raising(self, settings):
        settings.set_internal('a_new_section', 'anything', 'x')

        assert settings.p.get('a_new_section', 'anything') == 'x'

    def test_it_reports_whether_the_write_happened(self, settings):
        assert settings.set_internal(SECTION, HIDDEN, 'x') is True
        assert settings.set_internal(SECTION, FLAG_NAME, 'rw') is False
