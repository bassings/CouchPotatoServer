"""Regression tests for fail-closed automation enable-list handling."""

from unittest.mock import Mock


def test_enable_flag_helper_uses_python_naming_convention():
    from couchpotato.core.media.movie.providers.automation.base import is_list_item_enabled

    assert is_list_item_enabled(['1'], 0) is True


def test_imdb_missing_enable_flag_skips_extra_watchlist():
    from couchpotato.core.media.movie.providers.automation.imdb import IMDBWatchlist

    provider = object.__new__(IMDBWatchlist)
    provider.conf = lambda key: {
        'automation_urls_use': '1',
        'automation_urls': 'enabled-watchlist,missing-flag-watchlist',
    }[key]
    provider.getFromURL = Mock(return_value=[])

    assert provider.getIMDBids() == []
    provider.getFromURL.assert_called_once_with('enabled-watchlist&start=0')


def test_letterboxd_missing_enable_flag_skips_extra_watchlist():
    from couchpotato.core.media.movie.providers.automation.letterboxd import Letterboxd

    provider = object.__new__(Letterboxd)
    provider.conf = lambda key: {
        'automation_urls_use': '1',
        'automation_urls': 'enabled-user,missing-flag-user',
    }[key]
    provider.getHTMLData = Mock(return_value='<html><body></body></html>')

    assert provider.getWatchlist() == []
    provider.getHTMLData.assert_called_once_with(provider.url % ('enabled-user', 1))
