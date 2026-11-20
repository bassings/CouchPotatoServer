"""`settings.save` refuses every spelling of an option's access-flag name.

An option's access flag (`ro`, `hidden`, `rw`) lives in config.ini beside it as
`<option>_internal_meta`. The config parser lower-cases option names, so
`API_KEY_INTERNAL_META` is stored over the real `api_key_internal_meta`. The old
recognition was a case-sensitive suffix test, so that name was treated as an
ordinary option: the flag was overwritten and the read-only `core.api_key` could
then be overwritten by a second save.

These tests drive the real `Settings.saveView` over a temporary config file,
with `core` registered from the live declaration (`_core.config`), not a copy.
"""
import configparser
import hashlib

import pytest

from couchpotato.core._base import _core
from couchpotato.core.settings import Settings

pytestmark = pytest.mark.unit

SUFFIX = '_internal_meta'
PLACEHOLDER = 'placeholder-value-one'
FLAG_REFUSAL = 'An option flag cannot be changed through settings.save. Nothing was saved.'
HIDDEN_SECTION = 'zz_flags'
HIDDEN_OPTION = 'zz_option'
EACH_SPELLING = pytest.mark.parametrize('spelling', [0, 1, 2, 3, 4], ids=[
    'lower', 'upper', 'mixed', 'leading_space', 'trailing_space'])


@pytest.fixture(autouse=True)
def _isolate_settings_class_state():
    """`Settings.types` and `Settings.options` are class attributes."""
    types_before = dict(Settings.types)
    options_before = dict(Settings.options)
    yield
    Settings.types.clear()
    Settings.types.update(types_before)
    Settings.options.clear()
    Settings.options.update(options_before)


def _spellings(base):
    """The flag name of `base` as a caller might spell it."""
    flag = base.strip() + SUFFIX
    return [flag, flag.upper(), flag.title(), ' ' + flag, flag + ' ']


def _core_options():
    """Every core option as `loader.loadSettings` hands it to `registerDefaults`."""
    return {option['name']: option
            for entry in _core.config if entry['name'] == 'core'
            for group in entry['groups'] for option in group['options']}


def _load(path):
    settings = Settings()
    settings.setFile(str(path))
    settings.registerDefaults('core', _core_options(), save=False)
    settings.registerDefaults(HIDDEN_SECTION, {
        HIDDEN_OPTION: {'default': 'placeholder-hidden', 'ui-meta': 'hidden'}}, save=False)
    settings.save()
    return settings


@pytest.fixture
def settings(tmp_path):
    return _load(tmp_path / 'config.ini')


def _sha(settings):
    with open(settings.file, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _on_disk(settings, section, option):
    parser = configparser.RawConfigParser()
    parser.read(settings.file, encoding='utf-8')
    return parser.get(section, option, fallback=None)


def _save(settings, section, name, value=PLACEHOLDER):
    return settings.saveView(section=section, name=name, value=value)


PROTECTED = [('core', 'api_key', 'ro'), (HIDDEN_SECTION, HIDDEN_OPTION, 'hidden')]


@pytest.mark.parametrize('section, base, flag', PROTECTED)
class TestEverySpellingOfAFlagNameIsRefused:

    @EACH_SPELLING
    def test_the_save_is_refused_with_the_flag_text(self, settings, section, base, flag, spelling):
        name = _spellings(base)[spelling]

        result = _save(settings, section, name, value='rw')

        assert result == {'success': False, 'error': FLAG_REFUSAL}

    @EACH_SPELLING
    def test_the_flag_is_unchanged_in_memory_and_on_disk(
            self, settings, section, base, flag, spelling):
        before = _sha(settings)

        _save(settings, section, _spellings(base)[spelling], value='rw')

        assert settings.p.get(section, base + SUFFIX) == flag
        assert _on_disk(settings, section, base + SUFFIX) == flag
        assert _sha(settings) == before

    @EACH_SPELLING
    def test_the_protected_option_is_still_refused_afterwards(
            self, settings, section, base, flag, spelling):
        original = settings.p.get(section, base)
        _save(settings, section, _spellings(base)[spelling], value='rw')

        result = _save(settings, section, base, value='placeholder-overwrite')

        assert result == {'success': False}
        assert settings.p.get(section, base) == original

    @EACH_SPELLING
    def test_a_fresh_load_of_the_same_file_still_refuses_it(
            self, settings, tmp_path, section, base, flag, spelling):
        _save(settings, section, _spellings(base)[spelling], value='rw')

        reloaded = _load(tmp_path / 'config.ini')

        assert reloaded.p.get(section, base + SUFFIX) == flag
        assert _save(reloaded, section, base, value='placeholder-overwrite') == {'success': False}


class TestTheRecognitionItself:

    @pytest.mark.parametrize('name', _spellings('anything'))
    def test_every_spelling_is_a_flag_name(self, settings, name):
        assert settings.isOptionMeta('core', name) is True

    @pytest.mark.parametrize('name', ['api_key', 'meta', 'internal_meta_x', '_internal', ''])
    def test_an_ordinary_name_is_not(self, settings, name):
        assert settings.isOptionMeta('core', name) is False

    @pytest.mark.parametrize('name', [None, 7, ['x' + SUFFIX]])
    def test_a_name_that_is_not_text_is_not_a_flag_name(self, settings, name):
        assert settings.isOptionMeta('core', name) is False

    def test_the_recognition_folds_names_exactly_as_the_parser_does(self, settings):
        """`isOptionMeta` names `str.lower`; if the parser's fold ever changes, so must it."""
        samples = ['API_KEY_INTERNAL_META', 'Mixed_Case', 'api_Key', 'İ_meta']

        assert [settings.p.optionxform(name) for name in samples] == [
            name.lower() for name in samples]

    def test_a_character_the_parser_folds_to_ascii_is_still_the_flag_name(self, settings):
        """KELVIN SIGN lower-cases to `k`, so the parser stores this as `api_key_internal_meta`."""
        name = 'api_Key' + SUFFIX
        before = _sha(settings)

        result = _save(settings, 'core', name, value='rw')

        assert result == {'success': False, 'error': FLAG_REFUSAL}
        assert _sha(settings) == before
        assert settings.p.get('core', 'api_key' + SUFFIX) == 'ro'

    def test_the_flag_of_an_unregistered_option_is_refused_in_any_section(self, settings):
        before = _sha(settings)

        result = _save(settings, 'zz_unregistered', 'never_registered' + SUFFIX.upper(), 'rw')

        assert result == {'success': False, 'error': FLAG_REFUSAL}
        assert _sha(settings) == before
        assert settings.p.has_section('zz_unregistered') is False


class TestTheServersOwnFlagWritesAreUnaffected:

    def test_registration_still_writes_the_declared_flags(self, settings):
        assert settings.p.get('core', 'api_key' + SUFFIX) == 'ro'
        assert settings.p.get(HIDDEN_SECTION, HIDDEN_OPTION + SUFFIX) == 'hidden'

    def test_a_config_file_that_already_holds_flags_loads_unchanged(self, tmp_path):
        first = _load(tmp_path / 'config.ini')
        written = _sha(first)

        second = _load(tmp_path / 'config.ini')

        assert second.p.get('core', 'api_key' + SUFFIX) == 'ro'
        assert _sha(second) == written


class TestTheReadPath:

    def test_no_flag_entry_appears_in_the_values(self, settings):
        values = settings.getValues()

        names = [name for options in values.values() for name in options]
        assert [name for name in names if name.endswith(SUFFIX)] == []

    def test_a_flag_stored_under_a_stray_spelling_is_still_hidden_from_the_values(self, tmp_path):
        path = tmp_path / 'config.ini'
        path.write_text('[core]\nAPI_KEY_INTERNAL_META = ro\napi_key = placeholder-key-one\n',
                        encoding='utf-8')

        values = _load(path).getValues()

        assert [name for name in values['core'] if name.endswith(SUFFIX)] == []
        assert 'ro' not in values['core'].values()

    def test_get_does_not_return_a_flag_under_any_spelling(self, settings):
        returned = [settings.get(name, 'core') for name in _spellings('api_key')]

        assert returned == [None] * len(returned)
