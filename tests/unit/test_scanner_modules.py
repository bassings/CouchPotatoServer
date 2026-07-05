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


class TestGetSubtitleLanguage:
    """VENDORED-05: getSubtitleLanguage now uses subliminal's
    search_external_subtitles (sidecar-file matching by filename suffix)
    instead of the vendored subliminal's Video.from_path().scan(). No mocking
    needed here since search_external_subtitles is pure filesystem matching.
    """

    def _group(self, movie_path):
        return {
            'files': {'movie': [movie_path], 'subtitle_extra': []},
            'is_dvd': False,
        }

    def test_detects_external_subtitle_language(self, parser, tmp_path):
        movie = tmp_path / 'Movie.Name.2020.1080p.mkv'
        movie.write_bytes(b'\0')
        sub = tmp_path / 'Movie.Name.2020.1080p.en.srt'
        sub.write_bytes(b'\0')

        result = parser.getSubtitleLanguage(self._group(str(movie)))

        assert str(sub) in result
        assert result[str(sub)] == ['en']

    def test_detects_multiple_sidecar_languages(self, parser, tmp_path):
        movie = tmp_path / 'Movie.Name.2020.1080p.mkv'
        movie.write_bytes(b'\0')
        (tmp_path / 'Movie.Name.2020.1080p.en.srt').write_bytes(b'\0')
        (tmp_path / 'Movie.Name.2020.1080p.fr.srt').write_bytes(b'\0')

        result = parser.getSubtitleLanguage(self._group(str(movie)))

        languages = sorted(sum(result.values(), []))
        assert languages == ['en', 'fr']

    def test_no_sidecar_subtitles_returns_empty(self, parser, tmp_path):
        movie = tmp_path / 'Movie.Name.2020.1080p.mkv'
        movie.write_bytes(b'\0')

        result = parser.getSubtitleLanguage(self._group(str(movie)))

        assert result == {}

    def test_dvd_group_skips_external_scan(self, parser, tmp_path):
        movie = tmp_path / 'Movie.Name.2020.1080p.mkv'
        movie.write_bytes(b'\0')
        (tmp_path / 'Movie.Name.2020.1080p.en.srt').write_bytes(b'\0')

        group = self._group(str(movie))
        group['is_dvd'] = True

        result = parser.getSubtitleLanguage(group)

        assert result == {}

    def test_missing_search_external_subtitles_degrades_gracefully(self, parser, tmp_path, monkeypatch):
        """If subliminal isn't importable, search_external_subtitles is None
        (see the module-level try/except import) -- scanning must not crash,
        just find nothing."""
        import couchpotato.core.plugins.scanner.media_parser as mp
        monkeypatch.setattr(mp, 'search_external_subtitles', None)

        movie = tmp_path / 'Movie.Name.2020.1080p.mkv'
        movie.write_bytes(b'\0')
        (tmp_path / 'Movie.Name.2020.1080p.en.srt').write_bytes(b'\0')

        result = parser.getSubtitleLanguage(self._group(str(movie)))

        assert result == {}


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


class FakeScannerWithShutdown(FolderScannerMixin):
    """FolderScannerMixin needs `shuttingDown()` from Plugin; stub it here so
    `_gatherFiles`/`scan` can be exercised without instantiating the full
    Scanner plugin (which needs Env/loader wiring)."""

    def shuttingDown(self):
        return False


class TestGatherFilesSymlinkContainment:
    """REG-003 item 2: a symlink inside the scanned folder that resolves to a
    location outside it must never be handed back as a scannable file --
    otherwise the renamer will move/delete the real target."""

    def test_symlink_to_external_file_is_excluded(self, tmp_path):
        scanner = FakeScannerWithShutdown()
        scan_dir = tmp_path / 'scan'
        scan_dir.mkdir()
        outside_file = tmp_path / 'secret.mkv'
        outside_file.write_bytes(b'\0' * 1024)
        link = scan_dir / 'link.mkv'
        link.symlink_to(outside_file)

        files = scanner._gatherFiles(str(scan_dir))

        assert str(link) not in files

    def test_symlink_to_external_directory_is_excluded(self, tmp_path):
        scanner = FakeScannerWithShutdown()
        scan_dir = tmp_path / 'scan'
        scan_dir.mkdir()
        outside_dir = tmp_path / 'outside'
        outside_dir.mkdir()
        (outside_dir / 'movie.mkv').write_bytes(b'\0' * 1024)
        linked_dir = scan_dir / 'linked'
        linked_dir.symlink_to(outside_dir)

        files = scanner._gatherFiles(str(scan_dir))

        assert not any('movie.mkv' in f for f in files)

    def test_regular_file_inside_scan_folder_is_included(self, tmp_path):
        scanner = FakeScannerWithShutdown()
        scan_dir = tmp_path / 'scan'
        scan_dir.mkdir()
        regular = scan_dir / 'movie.mkv'
        regular.write_bytes(b'\0' * 1024)

        files = scanner._gatherFiles(str(scan_dir))

        assert str(regular) in files

    def test_partial_results_returned_on_midwalk_error(self, monkeypatch):
        """REG-003 review nit (a): if os.walk raises partway through, files
        gathered before the error must still be returned (best-effort),
        matching the pre-refactor behaviour -- not discarded."""
        import couchpotato.core.plugins.scanner.folder_scanner as fs

        scanner = FakeScannerWithShutdown()

        def exploding_walk(folder, followlinks=False):
            yield ('/movies', [], ['first.mkv'])
            raise OSError('permission denied deep in the tree')

        # Keep files contained: everything under the yielded root resolves
        # inside it, so containment doesn't filter them out.
        monkeypatch.setattr(fs.os, 'walk', exploding_walk)
        monkeypatch.setattr(scanner, '_isWithinFolder', lambda file_path, real_folder: True)

        files = scanner._gatherFiles('/movies')

        assert any('first.mkv' in f for f in files), (
            'partial results gathered before the error were discarded'
        )

    def test_escaping_symlinked_dir_is_not_descended_into(self, tmp_path, monkeypatch):
        """PR #151 review (MEDIUM): a symlinked subdirectory that escapes the
        scan folder must be pruned BEFORE os.walk recurses into it -- not just
        filtered per-file after the fact. Otherwise the escape target (an NFS
        mount, /proc, another library) gets fully walked at scan time (perf /
        DoS). Assert os.walk never *descends* into it -- the stronger claim
        that per-file filtering alone does NOT provide (per-file filtering
        would still enumerate the escape target's contents first)."""
        import couchpotato.core.plugins.scanner.folder_scanner as fs

        scanner = FakeScannerWithShutdown()
        scan_dir = tmp_path / 'scan'
        scan_dir.mkdir()
        outside_dir = tmp_path / 'outside'
        outside_dir.mkdir()
        (outside_dir / 'ONLY_IN_ESCAPE_TARGET.mkv').write_bytes(b'\0' * 1024)
        linked_dir = scan_dir / 'linked'
        linked_dir.symlink_to(outside_dir)

        # Spy: record every directory os.walk actually visits (yields as root).
        real_walk = os.walk
        visited_roots = []

        def spying_walk(top, *args, **kwargs):
            for root, dirs, walk_files in real_walk(top, *args, **kwargs):
                visited_roots.append(root)
                yield root, dirs, walk_files

        monkeypatch.setattr(fs.os, 'walk', spying_walk)

        files = scanner._gatherFiles(str(scan_dir))

        # The escaping symlinked dir must never be descended into...
        assert not any(os.path.realpath(r) == os.path.realpath(str(outside_dir))
                       for r in visited_roots), (
            'os.walk descended into the escaping symlinked dir before '
            'containment pruning: %r' % (visited_roots,)
        )
        # ...and its contents are of course not returned either.
        assert not any('ONLY_IN_ESCAPE_TARGET' in f for f in files)

    def test_self_looping_symlink_terminates(self, tmp_path):
        """PR #151 review (MEDIUM): followlinks=True has no loop detection.
        A dir symlink looping back to the scan root must not hang / recurse
        without bound. Confirm _gatherFiles terminates and still returns the
        real media file."""
        scanner = FakeScannerWithShutdown()
        scan_dir = tmp_path / 'scan'
        scan_dir.mkdir()
        (scan_dir / 'movie.mkv').write_bytes(b'\0' * 1024)
        loop = scan_dir / 'loop'
        loop.symlink_to(scan_dir)

        # Must terminate (SYMLOOP_MAX bounds the OS symlink resolution).
        files = scanner._gatherFiles(str(scan_dir))

        assert any('movie.mkv' in f for f in files)


class TestGetReleaseNameYear:
    def test_basic(self, scanner):
        result = scanner.getReleaseNameYear('The.Movie.2023.720p.BluRay')
        assert result.get('year') == 2023
        assert 'movie' in result.get('name', '').lower()

    def test_no_year(self, scanner):
        result = scanner.getReleaseNameYear('SomeMovie')
        # Should still return something
        assert isinstance(result, dict)
