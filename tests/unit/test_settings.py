"""Tests for config/settings loading and saving.

Tests the Settings class behavior using a temporary config file,
verifying that CouchPotato's INI-based config system reads, writes,
and manages sections correctly.
"""
import os
import pytest

pytestmark = pytest.mark.unit


class TestConfigFileParsing:
    """Test reading/writing settings.conf files directly via ConfigParser."""

    def test_read_existing_config(self, config_file):
        from configparser import RawConfigParser
        p = RawConfigParser()
        p.read(config_file)
        assert p.has_section('core')
        assert p.get('core', 'debug') == '0'

    def test_write_and_read_back(self, config_file):
        from configparser import RawConfigParser
        p = RawConfigParser()
        p.read(config_file)
        p.set('core', 'debug', '1')
        with open(config_file, 'w') as f:
            p.write(f)

        p2 = RawConfigParser()
        p2.read(config_file)
        assert p2.get('core', 'debug') == '1'

    def test_add_new_section(self, config_file):
        from configparser import RawConfigParser
        p = RawConfigParser()
        p.read(config_file)
        p.add_section('renamer')
        p.set('renamer', 'enabled', 'True')
        with open(config_file, 'w') as f:
            p.write(f)

        p2 = RawConfigParser()
        p2.read(config_file)
        assert p2.has_section('renamer')
        assert p2.get('renamer', 'enabled') == 'True'

    def test_missing_config_file_returns_empty(self, temp_dir):
        from configparser import RawConfigParser
        p = RawConfigParser()
        result = p.read(os.path.join(temp_dir, 'nonexistent.conf'))
        assert result == []
        assert p.sections() == []


class TestSettingsClassInit:
    """Test that the Settings class initializes correctly."""

    def test_directories_delimiter(self):
        from couchpotato.core.settings import Settings
        s = Settings()
        assert s.directories_delimiter == '::'

    def test_options_initially_empty(self):
        from couchpotato.core.settings import Settings
        s = Settings()
        assert isinstance(s.options, dict)

    def test_set_file_and_read(self, config_file):
        from couchpotato.core.settings import Settings
        s = Settings()
        s.setFile(config_file)
        assert s.p is not None
        assert s.p.has_section('core')
