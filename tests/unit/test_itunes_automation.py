"""Regression tests for bounded iTunes automation feed configuration."""

from unittest.mock import Mock


ITUNES_FEED = """\
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:im="http://itunes.apple.com/rss">
  <entry>
    <im:name>Example Film</im:name>
    <im:releaseDate>2025-01-01T00:00:00-07:00</im:releaseDate>
  </entry>
</feed>
"""


def test_missing_enable_flag_skips_extra_itunes_url_without_losing_enabled_feed():
    from couchpotato.core.media.movie.providers.automation.itunes import ITunes

    provider = object.__new__(ITunes)
    provider.conf = lambda key: {
        'automation_urls_use': '1',
        'automation_urls': 'enabled-feed,missing-flag-feed',
    }[key]
    provider.getCache = Mock(return_value=ITUNES_FEED)
    provider.search = Mock(return_value={'imdb': 'tt1234567'})
    provider.isMinimalMovie = Mock(return_value=True)

    assert provider.getIMDBids() == ['tt1234567']
    provider.getCache.assert_called_once()
    assert provider.getCache.call_args.args[1] == 'enabled-feed'
