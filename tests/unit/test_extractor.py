"""Tests for the rarfile-based ExtractorMixin (VENDORED-07).

Covers the replacement of the vendored (Python 2-only) unrar2 library with
the maintained `rarfile` package, plus the graceful-degradation contract:
when no external extractor tool (unrar/unar/7z/7zz/bsdtar) is available,
RAR extraction must be skipped -- logging exactly one warning per scan --
rather than failing or tagging the release.
"""
import logging
import os
from unittest.mock import MagicMock, patch

import pytest
import rarfile

from couchpotato.core.plugins.renamer.extractor import (
    NO_EXTRACTOR_TOOL_MESSAGE,
    ExtractorMixin,
)


class _Extractor(ExtractorMixin):
    """Bare object exposing only the mixin's extraction methods."""


def _make_info(filename, is_dir=False):
    info = MagicMock()
    info.filename = filename
    info.isdir.return_value = is_dir
    return info


def _make_rar_handle(infos, contents):
    """Build a fake rarfile.RarFile. `contents` maps filename -> bytes."""
    handle = MagicMock()
    handle.infolist.return_value = infos
    handle.open.side_effect = lambda info: _FakeOpenResult(contents[info.filename])
    return handle


class _BytesReader:
    """Minimal file-like object supporting chunked .read() like RarExtFile."""

    def __init__(self, data):
        self._data = data
        self._sent = False

    def read(self, size=-1):
        if self._sent:
            return b''
        self._sent = True
        return self._data


class _FakeOpenResult:
    """Context manager standing in for rarfile.RarFile.open()'s return value."""

    def __init__(self, data):
        self._reader = _BytesReader(data)

    def __enter__(self):
        return self._reader

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _restore_unrar_tool():
    """extractArchive can mutate the module-global rarfile.UNRAR_TOOL; restore it."""
    original = rarfile.UNRAR_TOOL
    yield
    rarfile.UNRAR_TOOL = original


class TestExtractArchive:
    """Unit tests for ExtractorMixin.extractArchive against a mocked rarfile.RarFile."""

    def test_extracts_files_flattened_to_basename(self, tmp_path):
        infos = [_make_info('Movie.Name.2020/movie.mkv')]
        handle = _make_rar_handle(infos, {'Movie.Name.2020/movie.mkv': b'movie-bytes'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(tmp_path))

        expected_path = str(tmp_path / 'movie.mkv')
        assert extracted == [expected_path]
        assert (tmp_path / 'movie.mkv').read_bytes() == b'movie-bytes'
        handle.close.assert_called_once()

    def test_skips_directory_entries(self, tmp_path):
        infos = [_make_info('subdir/', is_dir=True)]
        handle = _make_rar_handle(infos, {})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(tmp_path))

        assert extracted == []
        handle.open.assert_not_called()

    def test_skips_files_that_already_exist(self, tmp_path):
        existing = tmp_path / 'movie.mkv'
        existing.write_bytes(b'already-here')
        infos = [_make_info('movie.mkv')]
        handle = _make_rar_handle(infos, {'movie.mkv': b'new-bytes'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(tmp_path))

        assert extracted == []
        assert existing.read_bytes() == b'already-here'
        handle.open.assert_not_called()

    def test_no_extractor_tool_raises_rarcannotexec(self, tmp_path):
        handle = MagicMock()
        handle.infolist.side_effect = rarfile.RarCannotExec('Cannot find working tool')

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            with pytest.raises(rarfile.RarCannotExec):
                _Extractor().extractArchive('archive.rar', str(tmp_path))

        handle.close.assert_called_once()

    def test_bad_rar_file_propagates_as_rarfile_error(self, tmp_path):
        with patch(
            'couchpotato.core.plugins.renamer.extractor.rarfile.RarFile',
            side_effect=rarfile.BadRarFile('corrupt archive'),
        ):
            with pytest.raises(rarfile.Error):
                _Extractor().extractArchive('archive.rar', str(tmp_path))

    def test_custom_tool_path_sets_unrar_tool_and_forces_redetect(self, tmp_path):
        handle = _make_rar_handle([], {})
        with patch(
            'couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle
        ), patch('couchpotato.core.plugins.renamer.extractor.rarfile.tool_setup') as mock_tool_setup:
            _Extractor().extractArchive(
                'archive.rar', str(tmp_path), custom_tool_path='/usr/local/bin/unrar'
            )

        assert rarfile.UNRAR_TOOL == '/usr/local/bin/unrar'
        mock_tool_setup.assert_called_once_with(force=True)


class _FakeRenamer(ExtractorMixin):
    """Minimal stand-in for the Renamer plugin, providing just enough of
    the surrounding Plugin/mixin surface for extractFiles to run without
    a full app/database/event-loop."""

    def __init__(self, from_folder, conf_values=None):
        self.from_folder = from_folder
        self._conf_values = conf_values or {}
        self.tagged = []

    def conf(self, name, default=None):
        if name == 'from':
            return self.from_folder
        return self._conf_values.get(name, default)

    def hastagRelease(self, release_download, tag=''):
        return False

    def checkFilesChanged(self, files, unchanged_for=60):
        return False, None

    def tagRelease(self, tag, group=None, release_download=None):
        self.tagged.append({'tag': tag, 'release_download': release_download})

    def makeDir(self, path):
        os.makedirs(path, exist_ok=True)

    def moveFile(self, old, dest, use_default=False):
        raise AssertionError('moveFile should not be called in this test')

    def deleteEmptyFolder(self, folder, show_error=True, only_clean=None):
        raise AssertionError('deleteEmptyFolder should not be called in this test')


class TestExtractFilesGracefulDegradation:
    """Integration-level tests of ExtractorMixin.extractFiles' skip-not-fail
    behavior when no extractor tool is available."""

    def test_logs_one_warning_and_skips_releases_without_tagging(self, tmp_path, caplog):
        folder = tmp_path / 'downloads'
        folder.mkdir()
        archive_one = folder / 'Movie.One.2020.rar'
        archive_two = folder / 'Movie.Two.2020.rar'
        archive_one.write_bytes(b'not-a-real-rar')
        archive_two.write_bytes(b'not-a-real-rar')

        fake = _FakeRenamer(from_folder=str(folder))
        fake.extractArchive = MagicMock(side_effect=rarfile.RarCannotExec('no tool'))

        with caplog.at_level(logging.WARNING, logger='couchpotato.core.plugins.renamer.extractor'):
            result_folder, media_folder, files, extr_files = fake.extractFiles(
                folder=str(folder),
                media_folder=str(folder),
                files=[str(archive_one), str(archive_two)],
            )

        # Neither archive was extracted, and the release must not be tagged
        # (skipped, not failed) -- it will simply be retried on a later scan.
        assert extr_files == []
        assert fake.tagged == []
        assert sorted(files) == sorted([str(archive_one), str(archive_two)])

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert NO_EXTRACTOR_TOOL_MESSAGE in warnings[0].getMessage()
        assert fake.extractArchive.call_count == 2

    def test_bad_archive_is_skipped_not_raised(self, tmp_path, caplog):
        folder = tmp_path / 'downloads'
        folder.mkdir()
        archive = folder / 'Movie.One.2020.rar'
        archive.write_bytes(b'not-a-real-rar')

        fake = _FakeRenamer(from_folder=str(folder))
        fake.extractArchive = MagicMock(side_effect=rarfile.BadRarFile('corrupt'))

        with caplog.at_level(logging.ERROR, logger='couchpotato.core.plugins.renamer.extractor'):
            result_folder, media_folder, files, extr_files = fake.extractFiles(
                folder=str(folder),
                media_folder=str(folder),
                files=[str(archive)],
            )

        assert extr_files == []
        assert fake.tagged == []
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1


class TestNoExtractorToolMessage:
    """The warning message must name the missing tool and give per-OS install hints."""

    def test_mentions_all_supported_tools(self):
        for tool in ('unrar', 'unar', '7z', '7zz'):
            assert tool in NO_EXTRACTOR_TOOL_MESSAGE

    def test_mentions_per_os_install_instructions(self):
        assert 'Windows' in NO_EXTRACTOR_TOOL_MESSAGE
        assert 'macOS' in NO_EXTRACTOR_TOOL_MESSAGE
        assert 'brew install unar' in NO_EXTRACTOR_TOOL_MESSAGE
        assert 'Linux' in NO_EXTRACTOR_TOOL_MESSAGE
        assert 'apk add 7zip' in NO_EXTRACTOR_TOOL_MESSAGE
