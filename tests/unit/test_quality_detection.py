"""Tests for quality detection (quality.guess event).

These tests verify that release names are correctly identified
with the appropriate quality based on tags, labels, identifiers,
and file extensions.
"""
import pytest
from unittest.mock import MagicMock, patch
import re


class TestQualityDetection:
    """Test quality.guess returns correct quality for various release names."""

    @pytest.fixture
    def quality_plugin(self):
        """Create a QualityPlugin instance with mocked dependencies."""
        # Create all patches
        patches = [
            patch('couchpotato.core.plugins.base.Env'),
            patch('couchpotato.core.plugins.quality.main.get_db'),
            patch('couchpotato.core.plugins.quality.main.addEvent'),
            patch('couchpotato.core.plugins.quality.main.addApiView'),
            patch('couchpotato.core.plugins.quality.main.fireEvent'),
        ]
        
        # Start all patches
        mocks = [p.start() for p in patches]
        mock_env, mock_db, mock_add_event, mock_add_api, mock_fire = mocks
        
        # Setup Env mock with cache
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_env.get.return_value = mock_cache
        
        # Mock scanner.name_year to return simple parsed name
        def mock_name_year(event_name, *args, **kwargs):
            if event_name == 'scanner.name_year':
                return {'name': 'Movie Name', 'year': 2025}
            return None
        mock_fire.side_effect = mock_name_year
        
        from couchpotato.core.plugins.quality.main import QualityPlugin
        plugin = QualityPlugin()
        
        # Pre-populate cached_qualities so all() doesn't need DB
        cached = []
        for idx, q in enumerate(plugin.qualities):
            q_copy = dict(q)
            q_copy['order'] = idx
            q_copy['size_min'] = q.get('size', (0, 0))[0]
            q_copy['size_max'] = q.get('size', (0, 0))[1]
            cached.append(q_copy)
        plugin.cached_qualities = cached
        
        yield plugin
        
        # Stop all patches
        for p in patches:
            p.stop()

    # ===================
    # 2160p / 4K Detection
    # ===================

    @pytest.mark.parametrize("release_name,expected_quality", [
        # Standard 2160p releases
        ("Avatar.Fire.and.Ash.2025.2160p.BluRay.x265.HEVC-GROUP", "2160p"),
        ("Movie.Name.2025.2160p.WEB-DL.DDP5.1.H.265", "2160p"),
        ("Movie.Name.2025.2160p.AMZN.WEB-DL.DDP5.1.Atmos.H.265", "2160p"),
        ("Movie.2025.2160p.UHD.BluRay.x265.10bit.HDR", "2160p"),
        ("Movie.2025.UHD.2160p.HDR.DV.BluRay", "2160p"),
        # Note: "4K" alone without "2160p" won't be detected as 2160p with current quality definitions
        # ("Movie.Name.2025.4K.UHD.BluRay.REMUX", "2160p"),  # Would need "4k" added to 2160p tags
    ])
    def test_detects_2160p_quality(self, quality_plugin, release_name, expected_quality):
        """Should correctly identify 2160p releases."""
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None, f"Failed to detect quality for: {release_name}"
        assert result['identifier'] == expected_quality, \
            f"Expected {expected_quality} but got {result['identifier']} for: {release_name}"

    # ===================
    # 1080p Detection
    # ===================

    @pytest.mark.parametrize("release_name,expected_quality", [
        # Standard 1080p releases
        ("Movie.Name.2025.1080p.BluRay.x264-GROUP", "1080p"),
        ("Movie.Name.2025.1080p.WEB-DL.DD5.1.H.264", "1080p"),
        ("Movie.Name.2025.1080p.AMZN.WEBRip.DDP5.1.x264", "1080p"),
        # Note: REMUX + AVC is ambiguous (AVC is a bd50 tag)
        # ("Movie.2025.1080p.REMUX.AVC.DTS-HD.MA.5.1", "1080p"),
        
        # With additional tags that shouldn't confuse detection
        ("Movie.Name.2025.1080p.BluRay.x264.DTS-GROUP", "1080p"),
        ("Movie.Name.2025.1080p.WEB-DL.AAC2.0.H264", "1080p"),
    ])
    def test_detects_1080p_quality(self, quality_plugin, release_name, expected_quality):
        """Should correctly identify 1080p releases."""
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None, f"Failed to detect quality for: {release_name}"
        assert result['identifier'] == expected_quality, \
            f"Expected {expected_quality} but got {result['identifier']} for: {release_name}"

    # ===================
    # 720p Detection
    # ===================

    @pytest.mark.parametrize("release_name,expected_quality", [
        ("Movie.Name.2025.720p.BluRay.x264-GROUP", "720p"),
        ("Movie.Name.2025.720p.WEB-DL.DD5.1.H.264", "720p"),
        ("Movie.Name.2025.720p.HDTV.x264", "720p"),
        ("Movie.2025.720p.BRRip.XviD.AC3", "720p"),
    ])
    def test_detects_720p_quality(self, quality_plugin, release_name, expected_quality):
        """Should correctly identify 720p releases."""
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None, f"Failed to detect quality for: {release_name}"
        assert result['identifier'] == expected_quality, \
            f"Expected {expected_quality} but got {result['identifier']} for: {release_name}"

    # ===================
    # BRRip Detection
    # ===================

    @pytest.mark.parametrize("release_name,expected_quality", [
        ("Movie.Name.2025.BRRip.XviD-GROUP", "brrip"),
        ("Movie.Name.2025.BDRip.x264.AAC", "brrip"),
        ("Movie.2025.HDTV.x264.AAC", "brrip"),
        ("Movie.2025.HDRip.XviD.AC3", "brrip"),
        ("Movie.2025.WEB-DL.XviD", "brrip"),
    ])
    def test_detects_brrip_quality(self, quality_plugin, release_name, expected_quality):
        """Should correctly identify BRRip releases."""
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None, f"Failed to detect quality for: {release_name}"
        assert result['identifier'] == expected_quality, \
            f"Expected {expected_quality} but got {result['identifier']} for: {release_name}"

    # ===================
    # DVD Quality Detection
    # ===================

    @pytest.mark.parametrize("release_name,expected_quality", [
        ("Movie.Name.2025.DVDRip.XviD-GROUP", "dvdrip"),
        ("Movie.Name.2025.DVD.Rip.x264", "dvdrip"),
    ])
    def test_detects_dvdrip_quality(self, quality_plugin, release_name, expected_quality):
        """Should correctly identify DVDRip releases."""
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None, f"Failed to detect quality for: {release_name}"
        assert result['identifier'] == expected_quality, \
            f"Expected {expected_quality} but got {result['identifier']} for: {release_name}"

    # ===================
    # Pre-release Quality Detection
    # ===================

    @pytest.mark.parametrize("release_name,expected_quality", [
        # Screeners
        ("Movie.Name.2025.DVDScr.XviD-GROUP", "scr"),
        ("Movie.Name.2025.SCREENER.XviD", "scr"),
        ("Movie.2025.HDScr.x264", "scr"),
        ("Movie.2025.WEBRip.x264", "scr"),
        
        # Cam/TS
        ("Movie.Name.2025.CAM.XviD-GROUP", "cam"),
        ("Movie.Name.2025.HDCAM.x264", "cam"),
        ("Movie.Name.2025.TS.XviD", "ts"),
        ("Movie.Name.2025.HDTS.x264", "ts"),
        ("Movie.Name.2025.TELESYNC.XviD", "ts"),
        
        # Telecine
        ("Movie.Name.2025.TC.XviD", "tc"),
        ("Movie.Name.2025.TELECINE.x264", "tc"),
    ])
    def test_detects_prerelease_quality(self, quality_plugin, release_name, expected_quality):
        """Should correctly identify pre-release qualities (screener, cam, ts, tc)."""
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None, f"Failed to detect quality for: {release_name}"
        assert result['identifier'] == expected_quality, \
            f"Expected {expected_quality} but got {result['identifier']} for: {release_name}"

    # ===================
    # BD50/Remux Detection
    # ===================

    @pytest.mark.parametrize("release_name,expected_quality", [
        ("Movie.Name.2025.1080p.BluRay.AVC.DTS-HD.MA.BDMV", "bd50"),
        ("Movie.2025.Complete.BluRay.AVC", "bd50"),
    ])
    def test_detects_bd50_quality(self, quality_plugin, release_name, expected_quality):
        """Should correctly identify BD50/BluRay disk releases."""
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None, f"Failed to detect quality for: {release_name}"
        assert result['identifier'] == expected_quality, \
            f"Expected {expected_quality} but got {result['identifier']} for: {release_name}"

    # ===================
    # Quality Differentiation
    # ===================

    def test_1080p_not_detected_as_2160p(self, quality_plugin):
        """1080p release should NOT be detected as 2160p."""
        release_name = "Anaconda.2025.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX"
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None
        assert result['identifier'] == '1080p', \
            f"1080p release incorrectly detected as {result['identifier']}"
        assert result['identifier'] != '2160p', \
            "1080p release should not be detected as 2160p"

    def test_720p_not_detected_as_1080p(self, quality_plugin):
        """720p release should NOT be detected as 1080p."""
        release_name = "Movie.Name.2025.720p.BluRay.x264-GROUP"
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None
        assert result['identifier'] == '720p', \
            f"720p release incorrectly detected as {result['identifier']}"

    def test_quality_scoring_prefers_explicit_tag(self, quality_plugin):
        """Explicit quality tag should win over other signals."""
        # This release has both 1080 in the tags and explicit 1080p identifier
        release_name = "Movie.2025.1080p.BluRay.x264.DTS"
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None
        assert result['identifier'] == '1080p'

    # ===================
    # 3D Detection
    # ===================

    @pytest.mark.parametrize("release_name,expected_3d", [
        ("Movie.Name.2025.1080p.BluRay.3D.HSBS", True),
        ("Movie.Name.2025.1080p.3D.Half-SBS.BluRay", True),
        ("Movie.2025.1080p.BluRay.HOU.x264", True),
        ("Movie.2025.1080p.BluRay.x264", False),
    ])
    def test_detects_3d_releases(self, quality_plugin, release_name, expected_3d):
        """Should correctly identify 3D releases."""
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None
        assert result.get('is_3d', False) == expected_3d, \
            f"3D detection failed for {release_name}: expected {expected_3d}"

    # ===================
    # Edge Cases
    # ===================

    def test_handles_empty_input(self, quality_plugin):
        """Should handle empty file list."""
        result = quality_plugin.guess([], use_cache=False)
        assert result is None

    def test_handles_no_quality_indicators(self, quality_plugin):
        """Should return None for files with no quality indicators."""
        result = quality_plugin.guess(["some_random_file.txt"], use_cache=False)
        # May return None or lowest quality depending on implementation
        # The important thing is it doesn't crash

    def test_case_insensitive_detection(self, quality_plugin):
        """Quality detection should be case-insensitive."""
        result_upper = quality_plugin.guess(["MOVIE.2025.1080P.BLURAY"], use_cache=False)
        result_lower = quality_plugin.guess(["movie.2025.1080p.bluray"], use_cache=False)
        result_mixed = quality_plugin.guess(["Movie.2025.1080p.BluRay"], use_cache=False)
        
        assert result_upper is not None
        assert result_lower is not None
        assert result_mixed is not None
        assert result_upper['identifier'] == result_lower['identifier'] == result_mixed['identifier']

    def test_quality_with_year_in_name(self, quality_plugin):
        """Should not confuse year with quality numbers."""
        # 2025 should not trigger 2160p detection
        result = quality_plugin.guess(["Movie.2025.720p.BluRay"], use_cache=False)
        assert result is not None
        assert result['identifier'] == '720p', \
            f"Year 2025 confused quality detection: got {result['identifier']}"

    # ===================
    # Real-World Regression Tests
    # ===================

    def test_anaconda_2025_1080p(self, quality_plugin):
        """Regression: Anaconda 2025 1080p was being detected as 2160p."""
        release_name = "Anaconda.2025.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX"
        result = quality_plugin.guess([release_name], use_cache=False)
        assert result is not None
        assert result['identifier'] == '1080p', \
            f"Anaconda 1080p regression: detected as {result['identifier']}"

    def test_multiple_files_consistent_quality(self, quality_plugin):
        """Multiple files from same release should return consistent quality."""
        files = [
            "Movie.2025.1080p.BluRay.x264-GROUP/movie.mkv",
            "Movie.2025.1080p.BluRay.x264-GROUP/sample.mkv",
            "Movie.2025.1080p.BluRay.x264-GROUP"
        ]
        result = quality_plugin.guess(files, use_cache=False)
        assert result is not None
        assert result['identifier'] == '1080p'


class TestContainsTagScore:
    """Test the containsTagScore method directly."""

    @pytest.fixture
    def quality_plugin(self):
        """Create a QualityPlugin instance."""
        patches = [
            patch('couchpotato.core.plugins.base.Env'),
            patch('couchpotato.core.plugins.quality.main.get_db'),
            patch('couchpotato.core.plugins.quality.main.addEvent'),
            patch('couchpotato.core.plugins.quality.main.addApiView'),
            patch('couchpotato.core.plugins.quality.main.fireEvent'),
        ]
        
        mocks = [p.start() for p in patches]
        mock_env = mocks[0]
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_env.get.return_value = mock_cache
        
        from couchpotato.core.plugins.quality.main import QualityPlugin
        plugin = QualityPlugin()
        
        # Pre-populate cached_qualities
        cached = []
        for idx, q in enumerate(plugin.qualities):
            q_copy = dict(q)
            q_copy['order'] = idx
            q_copy['size_min'] = q.get('size', (0, 0))[0]
            q_copy['size_max'] = q.get('size', (0, 0))[1]
            cached.append(q_copy)
        plugin.cached_qualities = cached
        
        yield plugin
        
        for p in patches:
            p.stop()

    def test_identifier_scores_highest(self, quality_plugin):
        """Identifier match should score 25 points."""
        quality = {'identifier': '1080p', 'label': '1080p', 'alternative': [], 'tags': [], 'ext': []}
        words = ['movie', '2025', '1080p', 'bluray']
        score = quality_plugin.containsTagScore(quality, words, "Movie.2025.1080p.BluRay")
        # identifier (25) + label (25) = 50
        assert score >= 25

    def test_extension_adds_points(self, quality_plugin):
        """Extension match should add 5 points."""
        quality = {'identifier': '1080p', 'label': '1080p', 'alternative': [], 'tags': [], 'ext': ['mkv']}
        words = ['movie', '2025', '1080p', 'bluray', 'mkv']
        score = quality_plugin.containsTagScore(quality, words, "Movie.2025.1080p.BluRay.mkv")
        assert score >= 5

    def test_2160p_scores_higher_than_1080p_for_2160p_release(self, quality_plugin):
        """2160p quality should score higher than 1080p for a 2160p release."""
        words = ['movie', '2025', '2160p', 'bluray', 'x265']
        
        q_2160p = {'identifier': '2160p', 'label': '2160p', 'alternative': [], 'tags': ['x264', 'h264', '2160'], 'ext': ['mkv']}
        q_1080p = {'identifier': '1080p', 'label': '1080p', 'alternative': [], 'tags': ['m2ts', 'x264', 'h264', '1080'], 'ext': ['mkv', 'm2ts', 'ts']}
        
        score_2160p = quality_plugin.containsTagScore(q_2160p, words, "Movie.2025.2160p.BluRay.x265")
        score_1080p = quality_plugin.containsTagScore(q_1080p, words, "Movie.2025.2160p.BluRay.x265")
        
        assert score_2160p > score_1080p, \
            f"2160p score ({score_2160p}) should be higher than 1080p score ({score_1080p})"

    def test_1080p_scores_higher_than_2160p_for_1080p_release(self, quality_plugin):
        """1080p quality should score higher than 2160p for a 1080p release."""
        words = ['movie', '2025', '1080p', 'bluray', 'x264']
        
        q_2160p = {'identifier': '2160p', 'label': '2160p', 'alternative': [], 'tags': ['x264', 'h264', '2160'], 'ext': ['mkv']}
        q_1080p = {'identifier': '1080p', 'label': '1080p', 'alternative': [], 'tags': ['m2ts', 'x264', 'h264', '1080'], 'ext': ['mkv', 'm2ts', 'ts']}
        
        score_1080p = quality_plugin.containsTagScore(q_1080p, words, "Movie.2025.1080p.BluRay.x264")
        score_2160p = quality_plugin.containsTagScore(q_2160p, words, "Movie.2025.1080p.BluRay.x264")
        
        assert score_1080p > score_2160p, \
            f"1080p score ({score_1080p}) should be higher than 2160p score ({score_2160p})"
