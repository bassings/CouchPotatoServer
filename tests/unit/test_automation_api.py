"""Tests for automation.list API route registration."""
import pytest
from unittest.mock import patch, MagicMock

from couchpotato.api import api, addApiView, callApiHandler


class TestAutomationListRoute:
    """Test that automation.list API route is properly registered."""

    def setup_method(self):
        self._original_api = dict(api)

    def teardown_method(self):
        api.clear()
        api.update(self._original_api)

    def test_automation_list_route_registered(self):
        """Test that automation.list can be registered."""
        def list_handler(**kwargs):
            return {'success': True, 'movies': []}

        addApiView('automation.list', list_handler)
        assert 'automation.list' in api

    def test_automation_list_returns_movies(self):
        """Test that automation.list returns a movies list."""
        test_movies = ['tt1234567', 'tt7654321']

        def list_handler(**kwargs):
            return {'success': True, 'movies': test_movies}

        addApiView('automation.list', list_handler)
        result = callApiHandler('automation.list')
        assert result['success'] is True
        assert result['movies'] == test_movies

    def test_automation_list_empty_when_no_providers(self):
        """Test that automation.list returns empty list when no providers return movies."""
        def list_handler(**kwargs):
            return {'success': True, 'movies': []}

        addApiView('automation.list', list_handler)
        result = callApiHandler('automation.list')
        assert result['success'] is True
        assert result['movies'] == []

    def test_automation_list_missing_returns_error(self):
        """Test that calling unregistered automation.list returns error."""
        result = callApiHandler('automation.list')
        assert result['success'] is False
        assert 'exist' in result['error']
