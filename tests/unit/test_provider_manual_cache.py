"""BUG-015: Manual refresh/search must bypass the 30-minute provider cache.

Covers the acceptance criteria in specs/BUG-015-manual-search-cache-bypass.md:
1. Manual search (manual=True) requests newznab RSS data with cache_timeout=-1
2. Automatic search (manual=False, the default) still requests with
   cache_timeout=1800
3. Same two assertions for torrentpotato (getJsonData)
4. Signature back-compat: provider.search(media, quality) with no `manual`
   arg still works
5. searcher.single(..., manual=True) threads manual=True down into the
   'searcher.search' fireEvent call, and Searcher.search threads manual into
   the 'provider.search.<proto>.<type>' fireEvent call (manual=False/absent
   by default)

No network calls are made anywhere in this file -- getRSSData/getJsonData/
fireEvent are all patched.
"""
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1 & 2 & 4: newznab
# ---------------------------------------------------------------------------

class TestNewznabManualCache:

    def _make_provider(self):
        from couchpotato.core.media._base.providers.nzb.newznab import Base
        p = Base.__new__(Base)
        return p

    def _host(self):
        return {
            'host': 'http://example.com/',
            'api_key': 'testkey',
            'extra_score': 0,
        }

    def test_manual_search_uses_negative_cache_timeout(self):
        """Acceptance 1: manual=True -> getRSSData called with cache_timeout=-1."""
        p = self._make_provider()
        results = []

        with patch.object(p, 'getRSSData', return_value=[]) as mock_get, \
             patch.object(p, 'buildUrl', return_value='?q=test'):
            p._searchOnHost(self._host(), {}, {}, results, manual=True)

        assert mock_get.called
        assert mock_get.call_args.kwargs.get('cache_timeout') == -1

    def test_automatic_search_uses_1800_cache_timeout(self):
        """Acceptance 2: manual=False (default) -> getRSSData with cache_timeout=1800."""
        p = self._make_provider()
        results = []

        with patch.object(p, 'getRSSData', return_value=[]) as mock_get, \
             patch.object(p, 'buildUrl', return_value='?q=test'):
            p._searchOnHost(self._host(), {}, {}, results)

        assert mock_get.called
        assert mock_get.call_args.kwargs.get('cache_timeout') == 1800

    def test_automatic_search_explicit_manual_false(self):
        """Explicit manual=False behaves the same as the default (1800s cache)."""
        p = self._make_provider()
        results = []

        with patch.object(p, 'getRSSData', return_value=[]) as mock_get, \
             patch.object(p, 'buildUrl', return_value='?q=test'):
            p._searchOnHost(self._host(), {}, {}, results, manual=False)

        assert mock_get.call_args.kwargs.get('cache_timeout') == 1800

    def test_search_threads_manual_into_searchOnHost(self):
        """search(media, quality, manual=True) must thread manual down to _searchOnHost."""
        p = self._make_provider()

        with patch.object(p, 'getHosts', return_value=[self._host()]), \
             patch.object(p, 'isDisabled', return_value=False), \
             patch.object(p, '_searchOnHost') as mock_search_on_host:
            p.search({}, {}, manual=True)

        assert mock_search_on_host.called
        # host, media, quality, results, manual=True (accept positional or kwarg)
        call = mock_search_on_host.call_args
        manual_value = call.kwargs.get('manual', call.args[-1] if len(call.args) >= 5 else None)
        assert manual_value is True

    def test_search_back_compat_no_manual_arg(self):
        """Acceptance 4: search(media, quality) with no manual kwarg still works."""
        p = self._make_provider()

        with patch.object(p, 'getHosts', return_value=[self._host()]), \
             patch.object(p, 'isDisabled', return_value=False), \
             patch.object(p, '_searchOnHost') as mock_search_on_host:
            result = p.search({}, {})  # no manual kwarg at all

        assert mock_search_on_host.called
        call = mock_search_on_host.call_args
        manual_value = call.kwargs.get('manual', call.args[-1] if len(call.args) >= 5 else False)
        assert manual_value is False


# ---------------------------------------------------------------------------
# 3 & 4: torrentpotato
# ---------------------------------------------------------------------------

class TestTorrentPotatoManualCache:

    def _make_provider(self):
        from couchpotato.core.media._base.providers.torrent.torrentpotato import Base
        p = Base.__new__(Base)
        return p

    def _host(self):
        return {'host': 'http://example.com/', 'extra_score': 0}

    def test_manual_search_uses_negative_cache_timeout(self):
        """Acceptance 3: manual=True -> getJsonData called with cache_timeout=-1."""
        p = self._make_provider()
        results = []

        with patch.object(p, 'getJsonData', return_value={}) as mock_get, \
             patch.object(p, 'buildUrl', return_value='http://example.com/?q=test'):
            p._searchOnHost(self._host(), {}, {}, results, manual=True)

        assert mock_get.called
        assert mock_get.call_args.kwargs.get('cache_timeout') == -1

    def test_automatic_search_uses_1800_cache_timeout(self):
        """Acceptance 3: manual=False (default) -> getJsonData with cache_timeout=1800."""
        p = self._make_provider()
        results = []

        with patch.object(p, 'getJsonData', return_value={}) as mock_get, \
             patch.object(p, 'buildUrl', return_value='http://example.com/?q=test'):
            p._searchOnHost(self._host(), {}, {}, results)

        assert mock_get.called
        assert mock_get.call_args.kwargs.get('cache_timeout') == 1800

    def test_search_threads_manual_into_searchOnHost(self):
        p = self._make_provider()

        with patch.object(p, 'getHosts', return_value=[self._host()]), \
             patch.object(p, 'isDisabled', return_value=False), \
             patch.object(p, '_searchOnHost') as mock_search_on_host:
            p.search({}, {}, manual=True)

        assert mock_search_on_host.called
        call = mock_search_on_host.call_args
        manual_value = call.kwargs.get('manual', call.args[-1] if len(call.args) >= 5 else None)
        assert manual_value is True

    def test_search_back_compat_no_manual_arg(self):
        """Acceptance 4: search(media, quality) with no manual kwarg still works."""
        p = self._make_provider()

        with patch.object(p, 'getHosts', return_value=[self._host()]), \
             patch.object(p, 'isDisabled', return_value=False), \
             patch.object(p, '_searchOnHost') as mock_search_on_host:
            result = p.search({}, {})

        assert mock_search_on_host.called
        call = mock_search_on_host.call_args
        manual_value = call.kwargs.get('manual', call.args[-1] if len(call.args) >= 5 else False)
        assert manual_value is False


# ---------------------------------------------------------------------------
# 4: YarrProvider base -- back-compat for all ~20 inheriting providers
# ---------------------------------------------------------------------------

class TestYarrProviderSearchBackCompat:

    def _make_dummy(self):
        from couchpotato.core.media._base.providers.base import YarrProvider

        class DummyProvider(YarrProvider):
            protocol = 'nzb'
            type = 'movie'

            def _searchOnTitle(self, title, media, quality, results):
                pass

        p = DummyProvider.__new__(DummyProvider)
        p.urls = {}
        return p

    def test_search_accepts_manual_kwarg(self):
        """YarrProvider.search must accept manual=True without raising (default no-op)."""
        p = self._make_dummy()

        with patch.object(p, 'isDisabled', return_value=False), \
             patch('couchpotato.core.media._base.providers.base.fireEvent', return_value='Some Title'):
            result = p.search({'info': {}}, {}, manual=True)

        assert isinstance(result, list)

    def test_search_back_compat_no_manual_arg(self):
        """Acceptance 4: existing 2-positional-arg call sites keep working."""
        p = self._make_dummy()

        with patch.object(p, 'isDisabled', return_value=False), \
             patch('couchpotato.core.media._base.providers.base.fireEvent', return_value='Some Title'):
            result = p.search({'info': {}}, {})

        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 5: threading through _base/searcher/main.py Searcher.search
# ---------------------------------------------------------------------------

class TestSearcherMainThreadsManual:

    def _make_searcher(self):
        from couchpotato.core.media._base.searcher.main import Searcher
        s = Searcher.__new__(Searcher)
        return s

    def test_manual_true_threaded_into_provider_search_event(self):
        s = self._make_searcher()
        calls = []

        def fake_fire_event(name, *args, **kwargs):
            calls.append((name, args, kwargs))
            return []

        with patch('couchpotato.core.media._base.searcher.main.fireEvent', side_effect=fake_fire_event), \
             patch.object(s, 'conf', return_value='both'):
            s.search(['nzb'], {'type': 'movie'}, {}, manual=True)

        provider_calls = [c for c in calls if c[0] == 'provider.search.nzb.movie']
        assert len(provider_calls) == 1
        assert provider_calls[0][2].get('manual') is True

    def test_manual_absent_defaults_to_false(self):
        s = self._make_searcher()
        calls = []

        def fake_fire_event(name, *args, **kwargs):
            calls.append((name, args, kwargs))
            return []

        with patch('couchpotato.core.media._base.searcher.main.fireEvent', side_effect=fake_fire_event), \
             patch.object(s, 'conf', return_value='both'):
            s.search(['nzb'], {'type': 'movie'}, {})  # no manual kwarg

        provider_calls = [c for c in calls if c[0] == 'provider.search.nzb.movie']
        assert len(provider_calls) == 1
        assert provider_calls[0][2].get('manual') is False


# ---------------------------------------------------------------------------
# 5: threading through movie/searcher.py MovieSearcher.single
# ---------------------------------------------------------------------------

class TestMovieSearcherSingleThreadsManual:

    def _movie(self):
        return {
            '_id': 'movie1',
            'profile_id': 'profile1',
            'status': 'active',
            'info': {'year': 2000, 'titles': ['Test Movie']},
            'releases': [],
        }

    def _profile(self):
        return {
            'qualities': ['720p'],
            'finish': [True],
            'wait_for': [0],
            '3d': False,
            'minimum_score': 1,
        }

    def _run_single(self, manual_kwargs):
        """Drive MovieSearcher.single() with everything mocked except the
        manual-threading behaviour under test, returning the recorded
        fireEvent calls."""
        from couchpotato.core.media.movie.searcher import MovieSearcher

        searcher = MovieSearcher.__new__(MovieSearcher)
        movie = self._movie()
        profile = self._profile()

        calls = []

        def fake_fire_event(name, *args, **kwargs):
            calls.append((name, args, kwargs))
            if name == 'media.restatus':
                return 'active'
            if name == 'quality.pre_releases':
                return []
            if name == 'movie.update_release_dates':
                return {}
            if name == 'quality.single':
                return {'identifier': kwargs.get('identifier', '720p'), 'label': '720p'}
            if name == 'searcher.search':
                return []
            if name == 'media.get':
                return movie
            if name == 'release.create_from_search':
                return []
            if name == 'release.try_download_result':
                return False
            return None

        mock_db = MagicMock()
        mock_db.get.return_value = profile

        with patch('couchpotato.core.media.movie.searcher.fireEvent', side_effect=fake_fire_event), \
             patch('couchpotato.core.media.movie.searcher.get_db', return_value=mock_db), \
             patch.object(searcher, 'conf', return_value=True):
            searcher.single(movie, search_protocols=['nzb'], **manual_kwargs)

        return calls

    def test_manual_true_threaded_into_searcher_search_event(self):
        calls = self._run_single({'manual': True})

        search_calls = [c for c in calls if c[0] == 'searcher.search']
        assert len(search_calls) == 1
        assert search_calls[0][2].get('manual') is True

    def test_manual_absent_defaults_to_false(self):
        calls = self._run_single({})

        search_calls = [c for c in calls if c[0] == 'searcher.search']
        assert len(search_calls) == 1
        assert search_calls[0][2].get('manual') is False

    def test_manual_false_explicit(self):
        calls = self._run_single({'manual': False})

        search_calls = [c for c in calls if c[0] == 'searcher.search']
        assert len(search_calls) == 1
        assert search_calls[0][2].get('manual') is False
