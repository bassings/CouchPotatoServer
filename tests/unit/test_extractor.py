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
    DEFAULT_UNRAR_TOOL,
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

    def test_does_not_rewrite_existing_files_but_reports_them(self, tmp_path):
        # An already-extracted target is a success, not a no-op: the extract
        # I/O is skipped (open never called, bytes untouched) but the path is
        # still returned so the caller can tag/clean the release.
        existing = tmp_path / 'movie.mkv'
        existing.write_bytes(b'already-here')
        infos = [_make_info('movie.mkv')]
        handle = _make_rar_handle(infos, {'movie.mkv': b'new-bytes'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(tmp_path))

        assert extracted == [str(tmp_path / 'movie.mkv')]
        assert existing.read_bytes() == b'already-here'
        handle.open.assert_not_called()

    def test_no_extractor_tool_raises_rarcannotexec_from_open(self, tmp_path):
        # rarfile raises RarCannotExec from open() (which shells out to the
        # external tool), NOT from infolist() -- header parsing is pure-Python
        # and never touches a tool. Model the real seam, and confirm no partial
        # output file is left behind when the tool is missing.
        infos = [_make_info('movie.mkv')]
        handle = MagicMock()
        handle.infolist.return_value = infos
        handle.open.side_effect = rarfile.RarCannotExec('Cannot find working tool')

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            with pytest.raises(rarfile.RarCannotExec):
                _Extractor().extractArchive('archive.rar', str(tmp_path))

        assert list(tmp_path.iterdir()) == []
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

    def test_clearing_custom_tool_path_restores_default_auto_detect(self, tmp_path):
        # rarfile.UNRAR_TOOL is a module-global; once a custom path is set it
        # must be reset to the default when the setting is cleared, otherwise
        # auto-detection stays pinned to the stale path forever.
        handle = _make_rar_handle([], {})
        with patch(
            'couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle
        ), patch('couchpotato.core.plugins.renamer.extractor.rarfile.tool_setup'):
            ext = _Extractor()
            ext.extractArchive('a.rar', str(tmp_path), custom_tool_path='/usr/local/bin/unrar')
            assert rarfile.UNRAR_TOOL == '/usr/local/bin/unrar'

            # Setting cleared: next call passes no custom path.
            ext.extractArchive('b.rar', str(tmp_path))
            assert rarfile.UNRAR_TOOL == DEFAULT_UNRAR_TOOL


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


class TestExtractFilesAlreadyExtractedIdempotency:
    """An archive whose target files are ALL already on disk (e.g. a crash
    between writing them and persisting the 'extracted' tag) must still be
    tagged and cleaned up -- not skipped and retried forever."""

    def _handle_with_one_file(self):
        infos = [_make_info('movie.mkv')]
        # contents are never read because the target already exists
        return _make_rar_handle(infos, {'movie.mkv': b'unused'})

    def test_already_extracted_archive_is_tagged_not_stuck(self, tmp_path):
        folder = tmp_path / 'downloads'
        folder.mkdir()
        archive = folder / 'Movie.One.2020.rar'
        archive.write_bytes(b'not-a-real-rar')
        # Target file already present from a previous (crashed) extraction run.
        already = folder / 'movie.mkv'
        already.write_bytes(b'already-extracted')

        handle = self._handle_with_one_file()
        fake = _FakeRenamer(from_folder=str(folder))

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            _folder, _media_folder, _files, extr_files = fake.extractFiles(
                folder=str(folder),
                media_folder=str(folder),
                files=[str(archive)],
            )

        # Release IS tagged 'extracted' (cleanup=False path), the existing file
        # is reported, and it was NOT re-written (open never called).
        assert [t['tag'] for t in fake.tagged] == ['extracted']
        assert str(already) in extr_files
        handle.open.assert_not_called()
        assert already.read_bytes() == b'already-extracted'

    def test_already_extracted_archive_is_cleaned_up(self, tmp_path):
        folder = tmp_path / 'downloads'
        folder.mkdir()
        archive = folder / 'Movie.One.2020.rar'
        archive.write_bytes(b'not-a-real-rar')
        already = folder / 'movie.mkv'
        already.write_bytes(b'already-extracted')

        handle = self._handle_with_one_file()
        fake = _FakeRenamer(from_folder=str(folder))

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            fake.extractFiles(
                folder=str(folder),
                media_folder=str(folder),
                files=[str(archive)],
                cleanup=True,
            )

        # cleanup loop ran: the source archive was removed. (With cleanup=True
        # the release is not tagged -- cleanup supersedes tagging.)
        assert not archive.exists()
        handle.open.assert_not_called()


class TestScanScopedWarning:
    """The 'no extractor tool' warning must be emitted at most once per whole
    scan, not once per movie group. Renamer.scan() may call extractFiles once
    per group (via _processGroup), so the warn-once flag must be reset in
    scan() and shared across those calls."""

    def _build_renamer(self):
        """Construct a real Renamer bypassing Plugin.__new__ (which registers
        events), then stub only the collaborators that touch external state."""
        from couchpotato.core.plugins.renamer.main import Renamer

        renamer = object.__new__(Renamer)
        renamer.renaming_started = False
        return renamer

    def test_two_groups_in_one_scan_log_a_single_warning(self, tmp_path, caplog):
        from couchpotato.core.plugins.renamer import main as renamer_main

        from_folder = tmp_path / 'from'
        to_folder = tmp_path / 'to'
        from_folder.mkdir()
        to_folder.mkdir()

        # Two distinct movie folders, each containing a single .rar archive.
        groups = {}
        for name in ('MovieOne', 'MovieTwo'):
            group_dir = from_folder / name
            group_dir.mkdir()
            (group_dir / f'{name}.rar').write_bytes(b'not-a-real-rar')
            groups[name] = {
                'media': {'info': {'title': name}},
                'dirname': str(group_dir),
            }

        conf_values = {
            'from': str(from_folder),
            'to': str(to_folder),
            'unrar': True,
            'unrar_path': None,
            'unrar_modify_date': False,
        }

        renamer = self._build_renamer()
        renamer.conf = lambda attr, value=None, default=None, section=None: conf_values.get(attr, default)
        renamer.shuttingDown = lambda value=None: False
        renamer.hastagRelease = lambda release_download, tag='': False
        renamer.checkFilesChanged = lambda files, unchanged_for=60: (False, None)
        renamer.tagRelease = lambda *a, **k: None
        renamer.makeDir = lambda path: os.makedirs(path, exist_ok=True)
        # Inject the missing-tool condition at the extractArchive seam so both
        # groups hit RarCannotExec inside a single scan().
        extract_calls = []

        def _raise_no_tool(rar_path, extr_path, custom_tool_path=None):
            extract_calls.append(rar_path)
            raise rarfile.RarCannotExec('no tool')

        renamer.extractArchive = _raise_no_tool

        with patch.object(renamer_main, 'fireEvent', return_value=groups), \
             caplog.at_level(logging.WARNING, logger='couchpotato.core.plugins.renamer.extractor'):
            renamer.scan()

        # Both groups were processed (two extractFiles -> two extractArchive
        # calls), but only ONE warning was logged for the whole scan.
        assert len(extract_calls) == 2
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING
                    and NO_EXTRACTOR_TOOL_MESSAGE in r.getMessage()]
        assert len(warnings) == 1

    def test_flag_reset_between_scans(self, tmp_path, caplog):
        """A fresh scan re-arms the warning (the flag is per-scan, not
        per-process): two separate scans each warn once."""
        from couchpotato.core.plugins.renamer import main as renamer_main

        from_folder = tmp_path / 'from'
        to_folder = tmp_path / 'to'
        from_folder.mkdir()
        to_folder.mkdir()
        group_dir = from_folder / 'MovieOne'
        group_dir.mkdir()
        (group_dir / 'MovieOne.rar').write_bytes(b'not-a-real-rar')
        groups = {'MovieOne': {'media': {'info': {'title': 'MovieOne'}}, 'dirname': str(group_dir)}}

        conf_values = {
            'from': str(from_folder), 'to': str(to_folder), 'unrar': True,
            'unrar_path': None, 'unrar_modify_date': False,
        }

        renamer = self._build_renamer()
        renamer.conf = lambda attr, value=None, default=None, section=None: conf_values.get(attr, default)
        renamer.shuttingDown = lambda value=None: False
        renamer.hastagRelease = lambda release_download, tag='': False
        renamer.checkFilesChanged = lambda files, unchanged_for=60: (False, None)
        renamer.tagRelease = lambda *a, **k: None
        renamer.makeDir = lambda path: os.makedirs(path, exist_ok=True)
        renamer.extractArchive = MagicMock(side_effect=rarfile.RarCannotExec('no tool'))

        with patch.object(renamer_main, 'fireEvent', return_value=groups), \
             caplog.at_level(logging.WARNING, logger='couchpotato.core.plugins.renamer.extractor'):
            renamer.scan()
            renamer.scan()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING
                    and NO_EXTRACTOR_TOOL_MESSAGE in r.getMessage()]
        assert len(warnings) == 2


class TestNoExtractorToolMessage:
    """The warning message must name the missing tool and give per-OS install hints."""

    def test_mentions_all_supported_tools(self):
        # Must match the tool list documented in the module docstring and the
        # `unrar` setting description in api.py (which include bsdtar).
        for tool in ('unrar', 'unar', '7z', '7zz', 'bsdtar'):
            assert tool in NO_EXTRACTOR_TOOL_MESSAGE

    def test_mentions_per_os_install_instructions(self):
        assert 'Windows' in NO_EXTRACTOR_TOOL_MESSAGE
        assert 'macOS' in NO_EXTRACTOR_TOOL_MESSAGE
        assert 'brew install unar' in NO_EXTRACTOR_TOOL_MESSAGE
        assert 'Linux' in NO_EXTRACTOR_TOOL_MESSAGE
        assert 'apk add 7zip' in NO_EXTRACTOR_TOOL_MESSAGE
