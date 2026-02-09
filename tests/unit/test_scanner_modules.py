"""Tests for the split scanner module components."""

import os
import pytest
import tempfile

from couchpotato.core.plugins.scanner.file_detector import FileDetectorMixin
from couchpotato.core.plugins.scanner.media_parser import MediaParserMixin
from couchpotato.core.plugins.scanner.folder_scanner import FolderScannerMixin


# ---------- FileDetectorMixin ----------

class FakeDetector(FileDetectorMixin):
    pass


@pytest.fixture
def detector():
    return FakeDetector()


class TestKeepFile:
    def test_keeps_normal_file(self, detector):
        assert detector.keepFile('/movies/good_movie.mkv') is True

    def test_ignores_extracted_path(self, detector):
        assert detector.keepFile(f'/movies{os.sep}extracted{os.sep}file.mkv') is False

    def test_ignores_ds_store(self, detector):
        assert detector.keepFile('/movies/.ds_store') is False

    def test_ignores_thumbs_db(self, detector):
        assert detector.keepFile('/movies/thumbs.db') is False


class TestIsSampleFile:
    def test_detects_sample(self, detector):
        assert detector.isSampleFile('/movies/sample.mkv')

    def test_detects_sample_in_path(self, detector):
        assert detector.isSampleFile('/movies/movie_sample_file.mkv')

    def test_not_sample(self, detector):
        assert not detector.isSampleFile('/movies/real_movie.mkv')


class TestIsDVDFile:
    def test_video_ts(self, detector):
        assert detector.isDVDFile(f'/movies/video_ts{os.sep}vts_01.vob') is True

    def test_bdmv(self, detector):
        assert detector.isDVDFile('/movies/bdmv/stream.m2ts') is True

    def test_regular_file(self, detector):
        assert detector.isDVDFile('/movies/movie.mkv') is False


class TestFileSizeBetween:
    def test_within_range(self, detector, tmp_path):
        f = tmp_path / "movie.mkv"
        # Create a file > 200MB would be impractical, so test the boundary logic
        f.write_bytes(b'\0' * 1024)  # tiny file
        assert detector.filesizeBetween(str(f), {'min': 0, 'max': 1}) is True

    def test_below_min(self, detector, tmp_path):
        f = tmp_path / "tiny.mkv"
        f.write_bytes(b'\0' * 100)
        assert detector.filesizeBetween(str(f), {'min': 1, 'max': 100}) is False


class TestGetFileSize:
    def test_existing_file(self, detector, tmp_path):
        f = tmp_path / "test.mkv"
        f.write_bytes(b'\0' * 1048576)  # 1MB
        assert detector.getFileSize(str(f)) == pytest.approx(1.0, abs=0.01)

    def test_nonexistent_file(self, detector):
        assert detector.getFileSize('/nonexistent/file') is None


class TestFileFilterMethods:
    def test_get_subtitles(self, detector):
        files = ['/m/movie.mkv', '/m/movie.srt', '/m/movie.sub', '/m/movie.nfo']
        result = detector.getSubtitles(files)
        assert result == {'/m/movie.srt', '/m/movie.sub'}

    def test_get_subtitles_extras(self, detector):
        files = ['/m/movie.mkv', '/m/movie.idx', '/m/movie.srt']
        result = detector.getSubtitlesExtras(files)
        assert result == {'/m/movie.idx'}

    def test_get_nfo(self, detector):
        files = ['/m/movie.mkv', '/m/movie.nfo', '/m/info.txt']
        result = detector.getNfo(files)
        assert result == {'/m/movie.nfo', '/m/info.txt'}

    def test_get_movie_extras(self, detector):
        files = ['/m/movie.mkv', '/m/movie.mds']
        result = detector.getMovieExtras(files)
        assert result == {'/m/movie.mds'}

    def test_get_samples(self, detector):
        files = ['/m/movie.mkv', '/m/sample.mkv', '/m/movie_sample_clip.avi']
        result = detector.getSamples(files)
        assert '/m/sample.mkv' in result
        assert '/m/movie.mkv' not in result


# ---------- MediaParserMixin ----------

class FakeMediaParser(MediaParserMixin):
    # Provide findYear from FolderScannerMixin for getMeta
    def findYear(self, text):
        import re
        matches = re.findall('(?P<year>19[0-9]{2}|20[0-9]{2})', text)
        return matches[-1] if matches else ''


@pytest.fixture
def parser():
    return FakeMediaParser()


class TestGetCodec:
    def test_finds_x264(self, parser):
        assert parser.getCodec('/movies/Movie.x264.mkv', ['x264', 'H264', 'x265']) == 'x264'

    def test_finds_h265(self, parser):
        assert parser.getCodec('/movies/Movie.H265.BluRay.mkv', ['x264', 'H264', 'x265', 'H265']) == 'H265'

    def test_no_codec(self, parser):
        assert parser.getCodec('/movies/Movie.mkv', ['x264', 'H264']) == ''


class TestGetResolution:
    def test_1080p(self, parser):
        result = parser.getResolution('/movies/Movie.1080p.mkv')
        assert result['resolution_width'] == 1920

    def test_720p(self, parser):
        result = parser.getResolution('/movies/Movie.720p.mkv')
        assert result['resolution_width'] == 1280

    def test_2160p(self, parser):
        result = parser.getResolution('/movies/Movie.2160p.mkv')
        assert result['resolution_width'] == 3840

    def test_default(self, parser):
        result = parser.getResolution('/movies/Movie.mkv')
        assert result['resolution_width'] == 0


class TestGetGroup:
    def test_finds_group(self, parser):
        assert parser.getGroup('/movies/Movie.1080p-SPARKS.mkv') == 'SPARKS'

    def test_no_group(self, parser):
        assert parser.getGroup('/movies/Movie.mkv') == ''


class TestGetSourceMedia:
    def test_bluray(self, parser):
        assert parser.getSourceMedia('/movies/Movie.BluRay.mkv') == 'Blu-ray'

    def test_hdtv(self, parser):
        assert parser.getSourceMedia('/movies/Movie.HDTV.mkv') == 'HDTV'

    def test_dvd(self, parser):
        assert parser.getSourceMedia('/movies/Movie.DVDRip.mkv') == 'DVD'

    def test_unknown(self, parser):
        assert parser.getSourceMedia('/movies/Movie.mkv') is None


class TestGet3dType:
    def test_hsbs(self, parser):
        assert parser.get3dType('Movie.HSBS.1080p.mkv') == 'Half SBS'

    def test_sbs(self, parser):
        assert parser.get3dType('Movie.SBS.mkv') == 'SBS'

    def test_no_3d(self, parser):
        assert parser.get3dType('Movie.1080p.mkv') == ''


class TestGetMeta:
    def test_no_enzyme_returns_empty(self, parser, monkeypatch):
        import couchpotato.core.plugins.scanner.media_parser as mp
        monkeypatch.setattr(mp, 'enzyme', None)
        assert parser.getMeta('/fake/file.mkv') == {}


# ---------- FolderScannerMixin ----------

class FakeScanner(FolderScannerMixin):
    pass


@pytest.fixture
def scanner():
    return FakeScanner()


class TestFindYear:
    def test_year_in_parens(self, scanner):
        assert scanner.findYear('Movie (2023)') == '2023'

    def test_year_in_brackets(self, scanner):
        assert scanner.findYear('Movie [2019]') == '2019'

    def test_year_plain(self, scanner):
        assert scanner.findYear('Movie 2021 720p') == '2021'

    def test_no_year(self, scanner):
        assert scanner.findYear('Movie') == ''

    def test_prefers_bracketed(self, scanner):
        assert scanner.findYear('2010 Movie (2023)') == '2023'


class TestRemoveMultipart:
    def test_removes_cd1(self, scanner):
        assert 'cd1' not in scanner.removeMultipart('movie cd1')

    def test_removes_part2(self, scanner):
        assert 'part' not in scanner.removeMultipart('movie.part2')

    def test_removes_disk1(self, scanner):
        assert 'disk' not in scanner.removeMultipart('movie.disk1')


class TestGetPartNumber:
    def test_cd1(self, scanner):
        assert scanner.getPartNumber('movie cd1') == '1'

    def test_no_part(self, scanner):
        assert scanner.getPartNumber('movie') == 1


class TestCreateStringIdentifier:
    def test_basic(self, scanner):
        ident = scanner.createStringIdentifier('/movies/The Movie (2023)/the.movie.2023.720p.mkv', '/movies/')
        assert '2023' in ident
        assert 'movie' in ident

    def test_strips_quality_tags(self, scanner):
        ident = scanner.createStringIdentifier('/movies/Movie.720p.BluRay.x264.mkv', '/movies/')
        assert '720p' not in ident
        assert 'bluray' not in ident


class TestRemoveCPTag:
    def test_removes_tag(self, scanner):
        result = scanner.removeCPTag('Movie.cp(tt1234567, abc123).mkv')
        assert 'cp(' not in result
        assert 'tt1234567' not in result

    def test_no_tag(self, scanner):
        assert scanner.removeCPTag('Movie.mkv') == 'Movie.mkv'


class TestGetCPImdb:
    def test_finds_imdb(self, scanner):
        assert scanner.getCPImdb('movie.cp(tt1234567, abc).mkv') == 'tt1234567'

    def test_no_imdb(self, scanner):
        assert scanner.getCPImdb('movie.mkv') is False


class TestGetReleaseNameYear:
    def test_basic(self, scanner):
        result = scanner.getReleaseNameYear('The.Movie.2023.720p.BluRay')
        assert result.get('year') == 2023
        assert 'movie' in result.get('name', '').lower()

    def test_no_year(self, scanner):
        result = scanner.getReleaseNameYear('SomeMovie')
        # Should still return something
        assert isinstance(result, dict)
