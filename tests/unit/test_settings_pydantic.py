"""Tests for Pydantic-backed type coercion in Settings.

Verifies that the Settings class correctly uses Pydantic TypeAdapters
for automatic type coercion, replacing the old manual getBool/getInt/etc.
"""
import os
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def settings_with_types(config_file):
    """Create a Settings instance with typed options."""
    from couchpotato.core.settings import Settings
    from couchpotato.core.event import events
    events.clear()

    s = Settings()
    s.setFile(config_file)

    # Add a section with various types
    s.addSection('test')
    s.p.set('test', 'enabled', 'True')
    s.p.set('test', 'count', '42')
    s.p.set('test', 'ratio', '3.14')
    s.p.set('test', 'name', 'hello world')
    s.p.set('test', 'dirs', '/tmp/a::/tmp/b')
    s.p.set('test', 'secret', 'mypassword')
    s.p.set('test', 'disabled', 'False')
    s.p.set('test', 'zero', '0')
    s.p.set('test', 'one', '1')

    s.setType('test', 'enabled', 'bool')
    s.setType('test', 'count', 'int')
    s.setType('test', 'ratio', 'float')
    s.setType('test', 'name', 'unicode')
    s.setType('test', 'dirs', 'directories')
    s.setType('test', 'secret', 'password')
    s.setType('test', 'disabled', 'bool')
    s.setType('test', 'zero', 'bool')
    s.setType('test', 'one', 'bool')

    events.clear()
    return s


class TestPydanticCoercion:
    def test_bool_true(self, settings_with_types):
        assert settings_with_types.get('enabled', 'test') is True

    def test_bool_false(self, settings_with_types):
        assert settings_with_types.get('disabled', 'test') is False

    def test_bool_from_zero(self, settings_with_types):
        assert settings_with_types.get('zero', 'test') is False

    def test_bool_from_one(self, settings_with_types):
        assert settings_with_types.get('one', 'test') is True

    def test_int_coercion(self, settings_with_types):
        result = settings_with_types.get('count', 'test')
        assert result == 42
        assert isinstance(result, int)

    def test_float_coercion(self, settings_with_types):
        result = settings_with_types.get('ratio', 'test')
        assert abs(result - 3.14) < 0.001
        assert isinstance(result, float)

    def test_unicode_returns_string(self, settings_with_types):
        result = settings_with_types.get('name', 'test')
        assert isinstance(result, str)

    def test_directories_returns_list(self, settings_with_types):
        result = settings_with_types.get('dirs', 'test')
        assert isinstance(result, list)
        assert len(result) == 2
        assert '/tmp/a' in result

    def test_password_returns_raw(self, settings_with_types):
        assert settings_with_types.get('secret', 'test') == 'mypassword'

    def test_default_on_missing(self, settings_with_types):
        result = settings_with_types.get('nonexistent', 'test', default='fallback')
        assert result == 'fallback'


class TestLegacyGetters:
    """Ensure backward-compatible typed getters still work."""

    def test_getBool(self, settings_with_types):
        assert settings_with_types.getBool('test', 'enabled') is True
        assert settings_with_types.getBool('test', 'disabled') is False

    def test_getInt(self, settings_with_types):
        assert settings_with_types.getInt('test', 'count') == 42

    def test_getFloat(self, settings_with_types):
        assert abs(settings_with_types.getFloat('test', 'ratio') - 3.14) < 0.001

    def test_getDirectories(self, settings_with_types):
        result = settings_with_types.getDirectories('test', 'dirs')
        assert len(result) == 2

    def test_getEnabler(self, settings_with_types):
        assert settings_with_types.getEnabler('test', 'enabled') is True


class TestMetaOptions:
    def test_meta_option_not_readable(self, settings_with_types):
        s = settings_with_types
        s.p.set('test', 'apikey_internal_meta', 'hidden')
        assert s.isOptionMeta('test', 'apikey_internal_meta') is True

    def test_readonly_option(self, settings_with_types):
        s = settings_with_types
        s.p.set('test', 'locked_internal_meta', 'ro')
        assert s.isOptionWritable('test', 'locked') is False
        assert s.isOptionReadable('test', 'locked') is True

    def test_rw_option(self, settings_with_types):
        s = settings_with_types
        s.p.set('test', 'open_internal_meta', 'rw')
        assert s.isOptionWritable('test', 'open') is True
        assert s.isOptionReadable('test', 'open') is True

    def test_hidden_section(self, settings_with_types):
        s = settings_with_types
        s.p.set('test', 'section_hidden_internal_meta', 'true')
        assert s.isSectionReadable('test') is False
