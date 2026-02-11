"""Tests for provider test functionality."""
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestYarrProviderTest:
    """Tests for the YarrProvider._test and test methods."""

    def test_test_wrapper_returns_success_bool(self):
        """_test wrapper should convert bool to dict."""
        from couchpotato.core.media._base.providers.base import YarrProvider

        provider = object.__new__(YarrProvider)
        provider.test = Mock(return_value=True)
        provider.getName = Mock(return_value='TestProvider')

        result = provider._test()

        assert result == {'success': True}

    def test_test_wrapper_returns_success_tuple(self):
        """_test wrapper should handle tuple returns."""
        from couchpotato.core.media._base.providers.base import YarrProvider

        provider = object.__new__(YarrProvider)
        provider.test = Mock(return_value=(True, 'Test passed'))
        provider.getName = Mock(return_value='TestProvider')

        result = provider._test()

        assert result == {'success': True, 'msg': 'Test passed'}

    def test_test_wrapper_returns_failure_tuple(self):
        """_test wrapper should handle failure tuples."""
        from couchpotato.core.media._base.providers.base import YarrProvider

        provider = object.__new__(YarrProvider)
        provider.test = Mock(return_value=(False, 'Connection refused'))
        provider.getName = Mock(return_value='TestProvider')

        result = provider._test()

        assert result == {'success': False, 'msg': 'Connection refused'}

    def test_test_wrapper_handles_dict_return(self):
        """_test wrapper should pass through dict returns."""
        from couchpotato.core.media._base.providers.base import YarrProvider

        provider = object.__new__(YarrProvider)
        provider.test = Mock(return_value={'success': True, 'extra': 'data'})
        provider.getName = Mock(return_value='TestProvider')

        result = provider._test()

        assert result == {'success': True, 'extra': 'data'}

    def test_test_wrapper_handles_exception(self):
        """_test wrapper should catch exceptions."""
        from couchpotato.core.media._base.providers.base import YarrProvider

        provider = object.__new__(YarrProvider)
        provider.test = Mock(side_effect=Exception('Network error'))
        provider.getName = Mock(return_value='TestProvider')

        result = provider._test()

        assert result['success'] is False
        assert 'Network error' in result['msg']

    def test_default_test_returns_true_when_no_login(self):
        """Default test method should return True if no login required."""
        from couchpotato.core.media._base.providers.base import YarrProvider

        provider = object.__new__(YarrProvider)
        provider.urls = {}  # No login URL

        result = provider.test()

        assert result is True

    def test_default_test_calls_login_when_required(self):
        """Default test method should call login if login URL exists."""
        from couchpotato.core.media._base.providers.base import YarrProvider

        provider = object.__new__(YarrProvider)
        provider.urls = {'login': 'http://example.com/login'}
        provider.login = Mock(return_value=True)

        result = provider.test()

        provider.login.assert_called_once()
        assert result is True


class TestNewznabProviderTest:
    """Tests for Newznab provider test functionality."""

    def test_test_no_hosts_enabled(self):
        """Test should fail if no hosts are enabled."""
        from couchpotato.core.media._base.providers.nzb.newznab import Base

        provider = object.__new__(Base)
        provider.getHosts = Mock(return_value=[
            {'use': '0', 'host': 'http://example.com', 'api_key': 'key1'}
        ])
        provider.isEnabled = Mock(return_value=False)

        result = provider.test()

        assert result[0] is False
        assert 'No hosts enabled' in result[1]

    def test_test_checks_all_enabled_hosts(self):
        """Test should check all enabled hosts."""
        from couchpotato.core.media._base.providers.nzb.newznab import Base

        provider = object.__new__(Base)
        provider.getHosts = Mock(return_value=[
            {'use': '1', 'host': 'http://nzb1.example.com', 'api_key': 'key1'},
            {'use': '1', 'host': 'http://nzb2.example.com', 'api_key': 'key2'},
        ])
        provider.isEnabled = Mock(return_value=True)
        provider.getUrl = Mock(side_effect=lambda h: h + '/api?')
        provider.urlopen = Mock(return_value='<caps></caps>')

        result = provider.test()

        assert result[0] is True
        assert provider.urlopen.call_count == 2


class TestTorrentPotatoProviderTest:
    """Tests for TorrentPotato provider test functionality."""

    def test_test_no_hosts_enabled(self):
        """Test should fail if no hosts are enabled."""
        from couchpotato.core.media._base.providers.torrent.torrentpotato import Base

        provider = object.__new__(Base)
        provider.getHosts = Mock(return_value=[
            {'use': '0', 'host': 'http://example.com', 'pass_key': 'key1', 'name': 'user'}
        ])
        provider.isEnabled = Mock(return_value=False)

        result = provider.test()

        assert result[0] is False
        assert 'No hosts enabled' in result[1]

    def test_test_parses_json_response(self):
        """Test should handle valid JSON responses."""
        from couchpotato.core.media._base.providers.torrent.torrentpotato import Base

        provider = object.__new__(Base)
        provider.getHosts = Mock(return_value=[
            {'use': '1', 'host': 'http://torrent.example.com', 'pass_key': 'key1', 'name': 'user'}
        ])
        provider.isEnabled = Mock(return_value=True)
        provider.urlopen = Mock(return_value='{"results": []}')

        result = provider.test()

        assert result[0] is True
        assert 'torrent.example.com' in result[1]

    def test_test_handles_error_response(self):
        """Test should handle error responses."""
        from couchpotato.core.media._base.providers.torrent.torrentpotato import Base

        provider = object.__new__(Base)
        provider.getHosts = Mock(return_value=[
            {'use': '1', 'host': 'http://torrent.example.com', 'pass_key': 'key1', 'name': 'user'}
        ])
        provider.isEnabled = Mock(return_value=True)
        provider.urlopen = Mock(return_value='{"error": "Invalid passkey"}')

        result = provider.test()

        assert result[0] is False
        assert 'Invalid passkey' in result[1]
