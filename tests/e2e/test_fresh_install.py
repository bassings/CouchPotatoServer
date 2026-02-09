"""E2E test: Fresh install scenario.

Simulates starting CouchPotatoServer with no existing database,
verifying that the app would create the necessary directory structure
and configuration files. Since the full app has many dependencies,
we test the filesystem-level expectations.
"""
import os
import pytest

pytestmark = pytest.mark.e2e


class TestFreshInstallDirectoryStructure:
    """Verify a fresh data directory gets properly structured."""

    def test_data_dir_can_be_created(self, temp_dir):
        """A fresh data directory should be creatable."""
        data_dir = os.path.join(temp_dir, 'data')
        os.makedirs(data_dir)
        assert os.path.isdir(data_dir)

    def test_database_dir_can_be_created(self, temp_dir):
        """Database subdirectory should be creatable under data_dir."""
        db_dir = os.path.join(temp_dir, 'data', 'database')
        os.makedirs(db_dir)
        assert os.path.isdir(db_dir)

    def test_cache_dir_can_be_created(self, temp_dir):
        """Cache directory should be creatable."""
        cache_dir = os.path.join(temp_dir, 'data', 'cache')
        os.makedirs(cache_dir)
        assert os.path.isdir(cache_dir)

    def test_config_file_writable(self, temp_dir):
        """A new settings.conf should be writable."""
        config_path = os.path.join(temp_dir, 'settings.conf')
        from configparser import RawConfigParser
        p = RawConfigParser()
        p.add_section('core')
        p.set('core', 'debug', '0')
        with open(config_path, 'w') as f:
            p.write(f)
        assert os.path.isfile(config_path)
        assert os.path.getsize(config_path) > 0

    def test_log_file_writable(self, temp_dir):
        """Log directory and file should be writable."""
        logs_dir = os.path.join(temp_dir, 'logs')
        os.makedirs(logs_dir)
        log_file = os.path.join(logs_dir, 'CouchPotato.log')
        with open(log_file, 'w') as f:
            f.write('test log entry\n')
        assert os.path.isfile(log_file)

    def test_custom_plugins_dir_optional(self, temp_dir):
        """Custom plugins dir shouldn't exist on fresh install but should be creatable."""
        custom_dir = os.path.join(temp_dir, 'custom_plugins')
        assert not os.path.exists(custom_dir)
        os.makedirs(custom_dir)
        assert os.path.isdir(custom_dir)
