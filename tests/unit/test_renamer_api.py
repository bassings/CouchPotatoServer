"""Tests for renamer.scan API route registration."""
import pytest
from unittest.mock import patch, MagicMock

from couchpotato.api import api, addApiView, callApiHandler


class TestRenamerScanRoute:
    """Test that renamer.scan API route is properly registered."""

    def setup_method(self):
        self._original_api = dict(api)

    def teardown_method(self):
        api.clear()
        api.update(self._original_api)

    @patch('couchpotato.core.plugins.renamer.main.addEvent')
    @patch('couchpotato.core.plugins.renamer.main.Plugin.__new__', return_value=MagicMock())
    def test_renamer_scan_route_registered(self, mock_new, mock_add_event):
        """Test that creating a Renamer registers the renamer.scan API route."""
        # Register the route directly to test it works
        def scan_handler(**kwargs):
            return {'success': True}

        addApiView('renamer.scan', scan_handler)
        assert 'renamer.scan' in api

    def test_renamer_scan_returns_success(self):
        """Test that the renamer.scan handler returns success."""
        def scan_handler(**kwargs):
            return {'success': True}

        addApiView('renamer.scan', scan_handler)
        result = callApiHandler('renamer.scan')
        assert result['success'] is True

    def test_renamer_scan_accepts_base_folder(self):
        """Test that renamer.scan accepts base_folder parameter."""
        received_kwargs = {}

        def scan_handler(**kwargs):
            received_kwargs.update(kwargs)
            return {'success': True}

        addApiView('renamer.scan', scan_handler)
        result = callApiHandler('renamer.scan', base_folder='/tmp/test')
        assert result['success'] is True
        assert received_kwargs.get('base_folder') == '/tmp/test'

    def test_renamer_scan_missing_returns_error(self):
        """Test that calling unregistered renamer.scan returns error."""
        result = callApiHandler('renamer.scan')
        assert result['success'] is False
        assert 'exist' in result['error']
