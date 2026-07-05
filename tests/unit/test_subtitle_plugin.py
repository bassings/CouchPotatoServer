"""VENDORED-05: replace vendored subliminal 0.6.2 with modern subliminal 2.x.

Covers couchpotato/core/plugins/subtitle.py (the search-and-download plugin,
rewired to the modern subliminal API + optional OpenSubtitles.com account)
and the signature-drift guard for the subliminal 2.x surface CP depends on.

All subliminal network/filesystem calls are mocked at the plugin boundary
(download_best_subtitles / save_subtitles / scan_video / Video.fromname) so
these tests never touch the network or a real cache file.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs'))

babelfish = pytest.importorskip('babelfish')
subliminal = pytest.importorskip('subliminal')

from babelfish import Language  # noqa: E402

from couchpotato.core.plugins.subtitle import Subtitle  # noqa: E402
import couchpotato.core.plugins.subtitle as subtitle_module  # noqa: E402


def _make_subtitle(conf_values=None):
    """Build a Subtitle instance without running __init__.

    __init__ registers a real event handler and touches subliminal's global
    cache region; skipping it (mirroring the PutIO downloader test pattern in
    test_downloaders.py) keeps these tests hermetic and side-effect free.
    """
    conf_values = conf_values or {}
    plugin = Subtitle.__new__(Subtitle)

    def conf(key, **kw):
        return conf_values.get(key, kw.get('default', ''))

    plugin.conf = conf
    plugin.isDisabled = lambda: False
    return plugin


def _fake_subtitle(alpha2, path):
    sub = MagicMock()
    sub.language = MagicMock()
    sub.language.alpha2 = alpha2
    sub.get_path = MagicMock(return_value=path)
    return sub


def _group(movie_files, subtitle_language=None):
    return {
        'files': {'movie': movie_files, 'subtitle': []},
        'before_rename': [],
        'subtitle_language': subtitle_language or {},
    }


# ===========================================================================
# Signature-drift guard
# ===========================================================================

class TestSubliminalSignatureDriftGuard:
    """Fail loudly if a subliminal upgrade removes/renames the surface this
    plugin depends on, instead of the plugin silently breaking at runtime."""

    def test_download_best_subtitles_exists(self):
        assert callable(subliminal.download_best_subtitles)

    def test_save_subtitles_exists(self):
        assert callable(subliminal.save_subtitles)

    def test_scan_video_exists(self):
        assert callable(subliminal.scan_video)

    def test_region_configure_exists(self):
        assert callable(subliminal.region.configure)
        assert hasattr(subliminal.region, 'is_configured')

    def test_video_fromname_exists(self):
        assert callable(subliminal.Video.fromname)

    def test_search_external_subtitles_exists(self):
        from subliminal.core import search_external_subtitles
        assert callable(search_external_subtitles)


# ===========================================================================
# getLanguageObjects
# ===========================================================================

class TestGetLanguageObjects:
    def test_builds_babelfish_languages_from_codes(self):
        plugin = _make_subtitle({'languages': 'en, nl'})
        assert plugin.getLanguageObjects() == {Language.fromalpha2('en'), Language.fromalpha2('nl')}

    def test_skips_invalid_language_codes(self):
        plugin = _make_subtitle({'languages': 'en, xx'})
        assert plugin.getLanguageObjects() == {Language.fromalpha2('en')}

    def test_empty_config_returns_empty_set(self):
        plugin = _make_subtitle({'languages': ''})
        assert plugin.getLanguageObjects() == set()

    def test_all_invalid_codes_returns_empty_set(self):
        plugin = _make_subtitle({'languages': 'xx, zz'})
        assert plugin.getLanguageObjects() == set()


# ===========================================================================
# getProviderConfigs (OpenSubtitles.com account wiring)
# ===========================================================================

class TestGetProviderConfigs:
    def test_includes_opensubtitlescom_when_both_set(self):
        plugin = _make_subtitle({
            'opensubtitles_com_user': 'bob',
            'opensubtitles_com_password': 'secret',
        })
        assert plugin.getProviderConfigs() == {
            'opensubtitlescom': {'username': 'bob', 'password': 'secret'},
        }

    def test_omits_opensubtitlescom_when_unset(self):
        plugin = _make_subtitle({})
        assert plugin.getProviderConfigs() == {}

    def test_omits_opensubtitlescom_when_only_username_set(self):
        plugin = _make_subtitle({'opensubtitles_com_user': 'bob'})
        assert plugin.getProviderConfigs() == {}

    def test_omits_opensubtitlescom_when_only_password_set(self):
        plugin = _make_subtitle({'opensubtitles_com_password': 'secret'})
        assert plugin.getProviderConfigs() == {}


# ===========================================================================
# scanVideo (scan_video -> Video.fromname degradation)
# ===========================================================================

class TestScanVideo:
    def test_prefers_scan_video(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(subtitle_module.subliminal, 'scan_video', MagicMock(return_value=sentinel))
        plugin = _make_subtitle()
        assert plugin.scanVideo('/movies/movie.mkv') is sentinel

    def test_falls_back_to_fromname_when_scan_video_raises(self, monkeypatch):
        """Simulates e.g. a missing libmediainfo or unreadable path breaking
        scan_video -- must degrade to the name-only guessit scan, not crash."""
        monkeypatch.setattr(
            subtitle_module.subliminal, 'scan_video',
            MagicMock(side_effect=RuntimeError('libmediainfo not found')),
        )
        sentinel = object()
        fromname_mock = MagicMock(return_value=sentinel)
        monkeypatch.setattr(subtitle_module.subliminal.Video, 'fromname', fromname_mock)

        plugin = _make_subtitle()
        result = plugin.scanVideo('/movies/movie.mkv')

        assert result is sentinel
        fromname_mock.assert_called_once_with('movie.mkv')

    def test_returns_none_when_both_scan_paths_fail(self, monkeypatch):
        monkeypatch.setattr(
            subtitle_module.subliminal, 'scan_video',
            MagicMock(side_effect=RuntimeError('boom')),
        )
        monkeypatch.setattr(
            subtitle_module.subliminal.Video, 'fromname',
            MagicMock(side_effect=RuntimeError('boom again')),
        )
        plugin = _make_subtitle()
        assert plugin.scanVideo('/movies/movie.mkv') is None


# ===========================================================================
# searchSingle
# ===========================================================================

class TestSearchSingle:
    def test_disabled_plugin_returns_none(self):
        plugin = _make_subtitle({'languages': 'en'})
        plugin.isDisabled = lambda: True
        assert plugin.searchSingle(_group(['/movies/movie.mkv'])) is None

    def test_no_configured_languages_is_a_noop(self, monkeypatch):
        plugin = _make_subtitle({'languages': ''})
        download_mock = MagicMock()
        monkeypatch.setattr(subtitle_module.subliminal, 'download_best_subtitles', download_mock)

        assert plugin.searchSingle(_group(['/movies/movie.mkv'])) is True
        download_mock.assert_not_called()

    def test_downloads_and_saves_wanted_language(self, monkeypatch):
        plugin = _make_subtitle({'languages': 'en'})
        video = object()
        monkeypatch.setattr(plugin, 'scanVideo', lambda filename: video)

        saved_path = '/movies/movie.en.srt'
        fake_sub = _fake_subtitle('en', saved_path)
        download_mock = MagicMock(return_value={video: [fake_sub]})
        save_mock = MagicMock(return_value=[fake_sub])
        monkeypatch.setattr(subtitle_module.subliminal, 'download_best_subtitles', download_mock)
        monkeypatch.setattr(subtitle_module.subliminal, 'save_subtitles', save_mock)

        group = _group(['/movies/movie.mkv'])
        result = plugin.searchSingle(group)

        assert result is True
        assert group['files']['subtitle'] == [saved_path]
        assert group['before_rename'] == [saved_path]
        assert group['subtitle_language'][saved_path] == ['en']

        call_args, call_kwargs = download_mock.call_args
        assert call_args[0] == {video}
        assert call_args[1] == {Language.fromalpha2('en')}
        assert call_kwargs['providers'] == plugin.providers
        assert call_kwargs['provider_configs'] == {}

        save_mock.assert_called_once_with(video, [fake_sub])

    def test_passes_opensubtitlescom_provider_configs_when_set(self, monkeypatch):
        plugin = _make_subtitle({
            'languages': 'en',
            'opensubtitles_com_user': 'bob',
            'opensubtitles_com_password': 'secret',
        })
        video = object()
        monkeypatch.setattr(plugin, 'scanVideo', lambda filename: video)

        download_mock = MagicMock(return_value={})
        monkeypatch.setattr(subtitle_module.subliminal, 'download_best_subtitles', download_mock)

        plugin.searchSingle(_group(['/movies/movie.mkv']))

        _, call_kwargs = download_mock.call_args
        assert call_kwargs['provider_configs'] == {
            'opensubtitlescom': {'username': 'bob', 'password': 'secret'},
        }

    def test_skips_language_already_available(self, monkeypatch):
        """subtitle_language already lists 'en' for this group (detected by
        the scanner via search_external_subtitles) -- must not re-search."""
        plugin = _make_subtitle({'languages': 'en'})
        monkeypatch.setattr(plugin, 'scanVideo', lambda filename: object())

        download_mock = MagicMock()
        monkeypatch.setattr(subtitle_module.subliminal, 'download_best_subtitles', download_mock)

        group = _group(
            ['/movies/movie.mkv'],
            subtitle_language={'/movies/movie.en.srt': ['en']},
        )
        result = plugin.searchSingle(group)

        assert result is True
        download_mock.assert_not_called()

    def test_alpha2_sidecar_language_satisfies_wanted_language(self, monkeypatch):
        """VENDORED-05 review (end-to-end): a wanted 'pt' must be treated as
        already-present when the scanner recorded a Brazilian-Portuguese
        sidecar. The producer (getSubtitleLanguage) stores the bare alpha2
        'pt' (not 'pt-BR'), and this consumer compares against wanted
        `Language.fromalpha2('pt').alpha2` == 'pt', so no re-download happens.
        """
        plugin = _make_subtitle({'languages': 'pt'})
        monkeypatch.setattr(plugin, 'scanVideo', lambda filename: object())

        download_mock = MagicMock()
        monkeypatch.setattr(subtitle_module.subliminal, 'download_best_subtitles', download_mock)

        # 'pt' is what getSubtitleLanguage stores for a Movie.pt-BR.srt sidecar.
        group = _group(
            ['/movies/movie.mkv'],
            subtitle_language={'/movies/movie.pt-BR.srt': ['pt']},
        )
        result = plugin.searchSingle(group)

        assert result is True
        download_mock.assert_not_called()

    def test_force_ignores_already_available_languages(self, monkeypatch):
        plugin = _make_subtitle({'languages': 'en', 'force': True})
        video = object()
        monkeypatch.setattr(plugin, 'scanVideo', lambda filename: video)

        download_mock = MagicMock(return_value={})
        monkeypatch.setattr(subtitle_module.subliminal, 'download_best_subtitles', download_mock)

        group = _group(
            ['/movies/movie.mkv'],
            subtitle_language={'/movies/movie.en.srt': ['en']},
        )
        plugin.searchSingle(group)

        download_mock.assert_called_once()
        call_args = download_mock.call_args.args
        assert call_args[1] == {Language.fromalpha2('en')}

    def test_download_failure_logs_and_continues(self, monkeypatch, caplog):
        plugin = _make_subtitle({'languages': 'en'})
        monkeypatch.setattr(plugin, 'scanVideo', lambda filename: object())
        monkeypatch.setattr(
            subtitle_module.subliminal, 'download_best_subtitles',
            MagicMock(side_effect=ConnectionError('provider unreachable')),
        )

        group = _group(['/movies/movie.mkv'])
        result = plugin.searchSingle(group)

        assert result is True
        assert group['files']['subtitle'] == []

    def test_save_failure_logs_and_continues(self, monkeypatch):
        plugin = _make_subtitle({'languages': 'en'})
        video = object()
        monkeypatch.setattr(plugin, 'scanVideo', lambda filename: video)

        fake_sub = _fake_subtitle('en', '/movies/movie.en.srt')
        monkeypatch.setattr(
            subtitle_module.subliminal, 'download_best_subtitles',
            MagicMock(return_value={video: [fake_sub]}),
        )
        monkeypatch.setattr(
            subtitle_module.subliminal, 'save_subtitles',
            MagicMock(side_effect=OSError('disk full')),
        )

        group = _group(['/movies/movie.mkv'])
        result = plugin.searchSingle(group)

        assert result is True
        assert group['files']['subtitle'] == []

    def test_no_movie_file_scannable_is_skipped(self, monkeypatch):
        """scanVideo returning None (both scan_video and Video.fromname
        failed) must be skipped rather than crashing the whole search."""
        plugin = _make_subtitle({'languages': 'en'})
        monkeypatch.setattr(plugin, 'scanVideo', lambda filename: None)

        download_mock = MagicMock()
        monkeypatch.setattr(subtitle_module.subliminal, 'download_best_subtitles', download_mock)

        result = plugin.searchSingle(_group(['/movies/movie.mkv']))

        assert result is True
        download_mock.assert_not_called()

    def test_unexpected_exception_is_caught_and_returns_false(self, monkeypatch):
        """A completely unexpected failure (e.g. malformed group dict) must
        be swallowed by the outer try/except, same as the old plugin."""
        plugin = _make_subtitle({'languages': 'en'})

        broken_group = {'files': {'movie': ['/movies/movie.mkv']}}  # missing subtitle_language
        result = plugin.searchSingle(broken_group)

        assert result is False


# ===========================================================================
# configureCache
# ===========================================================================

class TestConfigureCache:
    """subliminal.region.is_configured is a read-only property on the real
    CacheRegion, so these tests swap in a stand-in `region` object entirely
    rather than trying to set the property directly."""

    def _fake_region(self, is_configured):
        region = MagicMock()
        region.is_configured = is_configured
        return region

    def test_configures_dbm_backend_when_not_yet_configured(self, monkeypatch, tmp_path):
        fake_region = self._fake_region(is_configured=False)
        monkeypatch.setattr(subtitle_module.subliminal, 'region', fake_region)
        monkeypatch.setattr(subtitle_module.Env, 'get', lambda key: str(tmp_path))

        plugin = _make_subtitle()
        plugin.configureCache()

        fake_region.configure.assert_called_once()
        assert fake_region.configure.call_args.args[0] == 'dogpile.cache.dbm'

    def test_skips_reconfiguring_when_already_configured(self, monkeypatch):
        fake_region = self._fake_region(is_configured=True)
        monkeypatch.setattr(subtitle_module.subliminal, 'region', fake_region)

        plugin = _make_subtitle()
        plugin.configureCache()

        fake_region.configure.assert_not_called()

    def test_configure_failure_is_caught(self, monkeypatch, tmp_path):
        """A bad cache_dir / dbm error must not crash plugin construction."""
        fake_region = self._fake_region(is_configured=False)
        fake_region.configure.side_effect = OSError('cannot open cache file')
        monkeypatch.setattr(subtitle_module.subliminal, 'region', fake_region)
        monkeypatch.setattr(subtitle_module.Env, 'get', lambda key: str(tmp_path))

        plugin = _make_subtitle()
        plugin.configureCache()  # must not raise
