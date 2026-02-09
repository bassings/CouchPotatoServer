"""Tests for the CouchPotato plugin loader.

Verifies that the Loader class can discover plugin directories
and build its module registry from the filesystem.
"""
import os
import sys
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLoaderDiscovery:
    """Test the Loader's ability to find plugins on disk."""

    def test_loader_initializes_empty(self):
        from couchpotato.core.loader import Loader
        loader = Loader()
        assert loader.plugins == {}
        assert loader.providers == {}
        assert loader.modules == {}

    def test_plugin_directories_exist(self):
        for subdir in ['plugins', 'notifications', 'downloaders']:
            d = os.path.join(REPO_ROOT, 'couchpotato', 'core', subdir)
            assert os.path.isdir(d), f"Plugin directory missing: {d}"

    def test_plugins_directory_has_modules(self):
        plugins_dir = os.path.join(REPO_ROOT, 'couchpotato', 'core', 'plugins')
        py_files = [f for f in os.listdir(plugins_dir) if f.endswith('.py') and f != '__init__.py']
        assert len(py_files) > 0

    def test_notifications_directory_has_modules(self):
        notif_dir = os.path.join(REPO_ROOT, 'couchpotato', 'core', 'notifications')
        assert os.path.isdir(notif_dir)
        contents = os.listdir(notif_dir)
        assert len(contents) > 1

    def test_downloaders_directory_has_modules(self):
        dl_dir = os.path.join(REPO_ROOT, 'couchpotato', 'core', 'downloaders')
        py_files = [f for f in os.listdir(dl_dir) if f.endswith('.py') and f != '__init__.py']
        assert len(py_files) > 0

    def test_preload_populates_paths(self):
        from couchpotato.core.loader import Loader
        from unittest.mock import patch, MagicMock

        loader = Loader()
        with patch('couchpotato.environment.Env') as mock_env:
            mock_env.get.return_value = '/tmp/cp_test_data'
            loader.preload(root=REPO_ROOT)

        assert len(loader.paths) > 0
        assert 'core' in loader.paths
        assert 'plugin' in loader.paths
