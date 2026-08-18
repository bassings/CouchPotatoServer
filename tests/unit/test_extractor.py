"""Tests for the rarfile-based ExtractorMixin (VENDORED-07).

Covers the replacement of the vendored (Python 2-only) unrar2 library with
the maintained `rarfile` package, plus the graceful-degradation contract:
when no external extractor tool (unrar/unar/7z/7zz/bsdtar) is available,
RAR extraction must be skipped -- logging exactly one warning per scan --
rather than failing or tagging the release.
"""
import logging
import os
import stat
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


class _RaisingReader:
    """File-like object that yields one chunk then raises, to model a
    mid-stream read failure (CRC error, disk hiccup) partway through a file."""

    def __init__(self, first_chunk, exc):
        self._first_chunk = first_chunk
        self._exc = exc
        self._sent = False

    def read(self, size=-1):
        if not self._sent:
            self._sent = True
            return self._first_chunk
        raise self._exc


class _RaisingOpenResult:
    """Context manager whose reader raises partway through .read()."""

    def __init__(self, first_chunk, exc):
        self._reader = _RaisingReader(first_chunk, exc)

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

    def test_duplicate_basenames_are_reported_once(self, tmp_path):
        # Two entries flattening to the same basename (top-level + Sample/) map
        # to one destination path; extracted must hold it once, not twice, so the
        # "distinct target files present" contract holds for any future caller.
        infos = [_make_info('movie.mkv'), _make_info('Sample/movie.mkv')]
        handle = _make_rar_handle(infos, {'movie.mkv': b'a', 'Sample/movie.mkv': b'b'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(tmp_path))

        assert extracted == [str(tmp_path / 'movie.mkv')]

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


class TestExtractArchiveAtomicWrite:
    """A mid-stream read/write failure must NOT leave a partial file at the
    real destination -- otherwise the next scan would accept the truncated
    file as 'already extracted' and move corrupt data into the library."""

    def test_interrupted_write_leaves_no_partial_file(self, tmp_path):
        info = _make_info('movie.mkv')
        handle = MagicMock()
        handle.infolist.return_value = [info]
        # First read yields data; the second raises mid-stream.
        handle.open.side_effect = lambda i: _RaisingOpenResult(
            b'partial-bytes', OSError('disk full')
        )

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            with pytest.raises(OSError):
                _Extractor().extractArchive('archive.rar', str(tmp_path))

        # No file at the real destination, and no leftover temp/part file.
        assert not (tmp_path / 'movie.mkv').exists()
        assert list(tmp_path.iterdir()) == []

    def test_sweeps_stray_part_file_from_a_prior_hard_kill(self, tmp_path):
        # A hard kill (SIGKILL/OOM/power-loss) can orphan a .cp-extract-*.part
        # temp file that the normal error path never got to unlink. A stray one
        # blocks empty-folder cleanup forever, so extractArchive must sweep it
        # on the next run -- while still extracting the real file successfully.
        stray = tmp_path / '.cp-extract-deadbeef.part'
        stray.write_bytes(b'orphaned-partial')

        info = _make_info('movie.mkv')
        handle = _make_rar_handle([info], {'movie.mkv': b'good-bytes'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(tmp_path))

        # Stray gone, real extraction succeeded, no leftover temp files.
        assert not stray.exists()
        assert (tmp_path / 'movie.mkv').read_bytes() == b'good-bytes'
        assert extracted == [str(tmp_path / 'movie.mkv')]
        assert list(tmp_path.glob('.cp-extract-*.part')) == []

    def test_extracted_file_gets_configured_permission_not_0600(self, tmp_path):
        # Regression: tempfile.mkstemp creates 0600 and os.replace preserves it,
        # so without an explicit chmod the extracted media file would be
        # owner-only -- unreadable by Plex/Kodi/other users (and broken under
        # the Docker PUID/PGID drop). It must get the configured file permission.
        info = _make_info('movie.mkv')
        handle = _make_rar_handle([info], {'movie.mkv': b'good-bytes'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle), \
             patch('couchpotato.core.plugins.renamer.extractor.Env.getPermission', return_value=0o644) as mock_perm:
            _Extractor().extractArchive('archive.rar', str(tmp_path))

        extracted = tmp_path / 'movie.mkv'
        assert extracted.exists()
        assert stat.S_IMODE(os.stat(extracted).st_mode) == 0o644
        mock_perm.assert_called_with('file')

    def test_next_scan_does_not_treat_interrupted_write_as_extracted(self, tmp_path):
        # Model the full "transient hiccup then retry" sequence end-to-end:
        # scan 1 fails mid-write; scan 2 (tool now healthy) must actually
        # extract the file and NOT tag off a leftover partial.
        folder = tmp_path / 'downloads'
        folder.mkdir()
        archive = folder / 'Movie.One.2020.rar'
        archive.write_bytes(b'not-a-real-rar')

        info = _make_info('movie.mkv')

        # Scan 1: read raises partway -> extractArchive raises -> extractFiles
        # logs+continues. No partial must be left behind.
        handle_fail = MagicMock()
        handle_fail.infolist.return_value = [info]
        handle_fail.open.side_effect = lambda i: _RaisingOpenResult(
            b'partial', OSError('mid-stream failure')
        )

        fake = _FakeRenamer(from_folder=str(folder))

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle_fail):
            _f, _m, _files, extr_files = fake.extractFiles(
                folder=str(folder), media_folder=str(folder), files=[str(archive)],
            )

        # First scan extracted nothing and did NOT tag the release.
        assert extr_files == []
        assert fake.tagged == []
        # Crucially: no partial file left at the destination to fool scan 2.
        assert not (folder / 'movie.mkv').exists()

        # Scan 2: the read now succeeds -> real extraction + tagging.
        handle_ok = _make_rar_handle([info], {'movie.mkv': b'good-bytes'})
        fake2 = _FakeRenamer(from_folder=str(folder))
        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle_ok):
            _f, _m, _files, extr_files2 = fake2.extractFiles(
                folder=str(folder), media_folder=str(folder), files=[str(archive)],
            )

        assert (folder / 'movie.mkv').read_bytes() == b'good-bytes'
        assert str(folder / 'movie.mkv') in extr_files2
        assert [t['tag'] for t in fake2.tagged] == ['extracted']


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


class TestExtractArchivePathTraversal:
    """T36: a hostile archive entry name must never resolve outside extr_path.

    os.path.basename defeats a forward-slash '../' traversal, but on POSIX a
    backslash is not a path separator, so a name like '..\\..\\evil.txt'
    survives basename intact -- and sp()'s Windows-path handling then
    anchors the joined path at filesystem root, walking it straight out of
    extr_path. A bare '..' (no separator at all) is a second, independent
    escape: basename only splits on the LAST '/', so a name with no '/' in
    it at all -- including '..' itself -- is returned completely unchanged.
    """

    def test_dotdot_slash_entry_is_already_contained_by_basename_alone(self, tmp_path):
        # Control case: proves a '../'-style fixture is NOT a valid guard for
        # this defect -- it already passes against the unmodified code, so it
        # would be an incidentally-passing test that guards nothing.
        extr_path = tmp_path / 'downloads' / 'extract_here'
        extr_path.mkdir(parents=True)
        infos = [_make_info('../../../evil.txt')]
        handle = _make_rar_handle(infos, {'../../../evil.txt': b'evil-bytes'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        assert extracted == [str(extr_path / 'evil.txt')]
        assert (extr_path / 'evil.txt').read_bytes() == b'evil-bytes'
        # Nothing escaped above extr_path.
        assert list((tmp_path / 'downloads').iterdir()) == [extr_path]

    def test_backslash_entry_does_not_escape_extraction_directory(self, tmp_path):
        # The load-bearing case: a backslash-separated traversal is NOT a
        # POSIX separator, so it survives os.path.basename intact, and sp()
        # then anchors the result at filesystem root. Two levels up from
        # extr_path (downloads/extract_here) lands exactly at tmp_path,
        # which is writable and unambiguous to assert against.
        extr_path = tmp_path / 'downloads' / 'extract_here'
        extr_path.mkdir(parents=True)
        entry_name = '..\\..\\CP_PWNED_BACKSLASH.txt'
        infos = [_make_info(entry_name)]
        handle = _make_rar_handle(infos, {entry_name: b'pwned-bytes'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        # Must NOT have escaped to tmp_path -- the pre-fix bug lands here.
        assert not (tmp_path / 'CP_PWNED_BACKSLASH.txt').exists()
        # Must have been sanitized and written INSIDE extr_path instead.
        expected = extr_path / 'CP_PWNED_BACKSLASH.txt'
        assert extracted == [str(expected)]
        assert expected.read_bytes() == b'pwned-bytes'

    def test_bare_dotdot_entry_is_refused_by_the_containment_check(self, tmp_path):
        # A second, independent escape: a bare '..' has no separator at all,
        # so os.path.basename returns it completely unchanged -- backslash
        # sanitization does nothing here. Only an assertion on the resolved
        # path catches this. Must be refused, not raise, and not extracted.
        extr_path = tmp_path / 'downloads' / 'extract_here'
        extr_path.mkdir(parents=True)
        infos = [_make_info('..')]
        handle = _make_rar_handle(infos, {'..': b'should-never-be-written'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        assert extracted == []
        # Nothing new appeared in extract_here's parent (the would-be escape target).
        assert list((tmp_path / 'downloads').iterdir()) == [extr_path]

    def test_absolute_path_entry_is_contained(self, tmp_path):
        extr_path = tmp_path / 'extract_here'
        extr_path.mkdir()
        infos = [_make_info('/etc/passwd')]
        handle = _make_rar_handle(infos, {'/etc/passwd': b'not-actually-passwd'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        assert extracted == [str(extr_path / 'passwd')]
        assert (extr_path / 'passwd').read_bytes() == b'not-actually-passwd'

    def test_a_winrar_backslash_subfolder_entry_extracts_instead_of_aborting(self, tmp_path):
        r"""The change's largest real-world effect, and until this test the only
        coverage of it was incidental.

        rarfile normalises separators for RAR3 (`h.filename.replace("\\", "/")`)
        but NOT for RAR5, which is what WinRAR has produced by default since
        2013. So a RAR5 `Sample\movie-sample.mkv` reached extractArchive with
        the backslash intact, sp() rewrote it into a `Sample/` directory that
        does not exist, and os.replace raised FileNotFoundError -- aborting the
        WHOLE archive, not just that entry. Most scene releases carry a
        `Sample\` or `Subs\` folder, so this was the common case, not an edge.

        Named for the benign behaviour rather than the escape, so that anyone
        later pruning "redundant security tests" does not delete the only guard
        on the regression this change actually fixes."""
        extr_path = tmp_path / 'extract_here'
        extr_path.mkdir()
        entry = 'Sample\\movie-sample.mkv'
        infos = [_make_info(entry)]
        handle = _make_rar_handle(infos, {entry: b'sample-bytes'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        expected = extr_path / 'movie-sample.mkv'
        assert extracted == [str(expected)]
        assert expected.read_bytes() == b'sample-bytes'

    @pytest.mark.parametrize('entry_name', ['', '/', '\\', '.', 'Sample/', 'Sample\\'])
    def test_an_entry_sanitising_to_nothing_is_refused_not_crashed(self, tmp_path, entry_name):
        """Every one of these reduces to a basename of '' or '.', which joins
        back to extr_path ITSELF. `isSubFolder` accepts equality ("the same as
        or inside"), so the containment check alone waves them through into
        `os.replace(tmp, <a directory>)` -> IsADirectoryError, which escapes
        extractArchive and abandons the whole archive.

        On an unattended server that is a permanent per-release wedge: the
        release is never tagged extracted, so every scheduled scan retries it,
        fails identically, and writes another full traceback. The refusal path
        this class exists to provide must catch these too."""
        extr_path = tmp_path / 'downloads' / 'extract_here'
        extr_path.mkdir(parents=True)
        infos = [_make_info(entry_name), _make_info('movie.mkv')]
        handle = _make_rar_handle(
            infos, {entry_name: b'never', 'movie.mkv': b'real-movie-bytes'}
        )

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        # Refused cleanly, and the REST of the archive still extracted.
        assert extracted == [str(extr_path / 'movie.mkv')]
        assert (extr_path / 'movie.mkv').read_bytes() == b'real-movie-bytes'

    def test_containment_catches_a_name_the_sanitizer_let_through(self, tmp_path):
        """The containment check is defence in depth, and with the name check
        in front of it there is no ENTRY NAME that reaches it -- after
        `_safeEntryBasename` the result can never contain a separator, so only
        '', '.' and '..' can escape, and all three are caught by name.

        That makes it a guard nobody can watch fail through the public API,
        which is exactly the shape this project treats as not-done. Measured:
        deleting the containment check entirely left all 34 tests green.

        So drive it at the seam it actually protects. Break the sanitizer
        deliberately and prove containment still refuses the entry -- that is
        the scenario it exists for: `_safeEntryBasename` being changed,
        bypassed, or defeated by a name shape nobody has thought of yet."""
        extr_path = tmp_path / 'downloads' / 'extract_here'
        extr_path.mkdir(parents=True)
        infos = [_make_info('anything.txt'), _make_info('movie.mkv')]
        handle = _make_rar_handle(
            infos, {'anything.txt': b'escaped', 'movie.mkv': b'real-movie-bytes'}
        )

        # A sanitizer that fails open, returning a traversing name unchanged.
        def broken_sanitizer(filename):
            return '../ESCAPED.txt' if filename == 'anything.txt' else filename

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle), \
             patch.object(_Extractor, '_safeEntryBasename', staticmethod(broken_sanitizer)):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        assert not (tmp_path / 'downloads' / 'ESCAPED.txt').exists(), (
            'containment did not catch a name the sanitizer let through'
        )
        # And the refusal stayed per-entry: the rest of the archive extracted.
        assert extracted == [str(extr_path / 'movie.mkv')]

    def test_benign_nested_entry_still_extracts_normally(self, tmp_path):
        extr_path = tmp_path / 'extract_here'
        extr_path.mkdir()
        infos = [_make_info('Movie.Name.2020/Sample/movie-sample.mkv')]
        handle = _make_rar_handle(
            infos, {'Movie.Name.2020/Sample/movie-sample.mkv': b'sample-bytes'}
        )

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        expected = extr_path / 'movie-sample.mkv'
        assert extracted == [str(expected)]
        assert expected.read_bytes() == b'sample-bytes'

    def test_refused_entry_is_logged_and_does_not_abort_the_rest_of_the_archive(
        self, tmp_path, caplog
    ):
        extr_path = tmp_path / 'downloads' / 'extract_here'
        extr_path.mkdir(parents=True)
        # Refusal FIRST, deliberately. With the refusal last, `continue` and
        # `break` are behaviourally identical and this test cannot tell them
        # apart -- which is exactly the property its name claims. Measured
        # before this reorder: mutating the refusal's `continue` to `break`
        # left all 27 tests GREEN while one hostile entry sank the archive.
        infos = [_make_info('..'), _make_info('movie.mkv')]
        handle = _make_rar_handle(
            infos, {'..': b'should-never-be-written', 'movie.mkv': b'real-movie-bytes'}
        )

        with patch(
            'couchpotato.core.plugins.renamer.extractor.rarfile.RarFile', return_value=handle
        ), caplog.at_level(
            logging.ERROR, logger='couchpotato.core.plugins.renamer.extractor'
        ):
            extracted = _Extractor().extractArchive('archive.rar', str(extr_path))

        # The legitimate entry still extracted -- one bad entry must not
        # sink the whole archive.
        assert extracted == [str(extr_path / 'movie.mkv')]
        assert (extr_path / 'movie.mkv').read_bytes() == b'real-movie-bytes'

        # The refusal is visible, not a silent skip.
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert '..' in errors[0].getMessage()


class TestRarfileApiSignatureGuard:
    """Every other test mocks rarfile, baking in assumptions about its API.
    This guard pins the REAL installed rarfile surface CP's extractor
    depends on, so a future dependency bump that drifts the API fails here
    (loudly) instead of silently passing every mocked test.

    NOTE: a full smoke test against a real .rar fixture would additionally
    catch behavioral drift, but that needs an external extractor tool
    (unrar/unar/7z/bsdtar) present in CI. Tracked as a possible follow-up;
    this signature guard is the cheap, environment-independent coverage."""

    def test_rarfile_exposes_the_api_the_extractor_relies_on(self):
        rf = pytest.importorskip('rarfile')

        # RarFile methods the extractor calls.
        assert hasattr(rf.RarFile, 'open')
        assert hasattr(rf.RarFile, 'infolist')
        assert hasattr(rf.RarFile, 'close')

        # RarInfo.isdir must be a callable method (extractor calls info.isdir()).
        assert callable(getattr(rf.RarInfo, 'isdir'))

        # Exception types the extractor catches / the caller distinguishes.
        for exc_name in ('RarCannotExec', 'BadRarFile', 'Error'):
            assert hasattr(rf, exc_name)
            assert issubclass(getattr(rf, exc_name), Exception)
        assert issubclass(rf.RarCannotExec, rf.Error)
        assert issubclass(rf.BadRarFile, rf.Error)

        # Tool-selection surface the extractor mutates.
        assert isinstance(rf.UNRAR_TOOL, str)
        assert callable(rf.tool_setup)


class TestRefusalLoggingIsBoundedAndPrivate:
    """A refused entry is attacker-controlled input reaching a production ERROR
    log, which makes it three problems at once, all measured rather than
    theorised.

    AMPLIFICATION: `rarfile.infolist()` parses headers only, so a hostile
    archive can carry thousands of poisoned names for almost nothing, and the
    unbounded form emitted one ERROR each.

    EXPOSURE: each line carried `rar_path` and the resolved destination.
    `PrivacyFilter` redacts `/home/<user>` and `/Users/<user>` only, so
    `/volume1/...`, `/mnt/media/...` and every other NAS layout went to disk in
    full. The paths were never needed -- the operator knows the extraction
    directory, and the entry name is what identifies the bad archive.

    FORGERY: an entry name may contain newlines, so interpolating it raw lets a
    crafted archive write whole fake log records.
    """

    def _run_with_entries(self, tmp_path, names, caplog):
        extr_path = tmp_path / 'extract_here'
        extr_path.mkdir()
        infos = [_make_info(n) for n in names]
        handle = _make_rar_handle(infos, {n: b'x' for n in names})
        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile',
                   return_value=handle), \
             caplog.at_level(logging.ERROR,
                             logger='couchpotato.core.plugins.renamer.extractor'):
            _Extractor().extractArchive('/private/nas/archive.rar', str(extr_path))
        return [r.getMessage() for r in caplog.records]

    def test_a_thousand_poisoned_entries_do_not_produce_a_thousand_errors(self, tmp_path, caplog):
        messages = self._run_with_entries(tmp_path, ['..'] * 1000, caplog)

        refusals = [m for m in messages if 'Refusing to extract' in m]
        assert len(refusals) <= 5, (
            'unbounded refusal logging: %d ERROR lines from one archive' % len(refusals)
        )
        # And the TOTAL is reported, so the cap does not hide how bad the
        # archive was. An earlier version promised "a count follows at the
        # end" and never emitted one -- worse than silence, because it tells
        # the reader to wait for something that never arrives.
        summary = [m for m in messages if 'in total' in m]
        assert summary, (
            'the flood was capped with no total, so an operator cannot tell '
            'five poisoned entries from a thousand'
        )
        assert '1000' in summary[0], (
            'the summary must carry the real count, not just say there were '
            'more: %r' % summary[0]
        )

    def test_the_refusal_does_not_write_private_paths_to_the_log(self, tmp_path, caplog):
        messages = self._run_with_entries(tmp_path, ['..'], caplog)

        joined = '\n'.join(messages)
        assert 'Refusing to extract' in joined
        assert '/private/nas/archive.rar' not in joined, (
            'the archive path reached the log; PrivacyFilter does not redact '
            'NAS-style paths, only /home/<user> and /Users/<user>'
        )
        assert str(tmp_path) not in joined, 'the resolved destination reached the log'

    def test_a_newline_in_an_entry_name_cannot_forge_a_log_record(self, tmp_path, caplog):
        """The forging vector is the EXTRACT line, not the refusal line.

        This test originally aimed at the refusal path and failed with "the
        hostile entry was not refused at all" -- which was the test being
        wrong, and useful for it. After sanitisation only `''`, `'.'` and
        `'..'` are ever refused, and none of those can carry a newline, so the
        refusal line is unreachable for forgery. `%r` stays there as
        belt-and-braces.

        The reachable one is the entry that gets EXTRACTED: its name is logged,
        it is fully attacker-controlled, and `%s` put the raw newline into the
        log. Measured before the fix:

            Extracting movie.mkv
            2026-08-19 00:00:00 INFO  Nothing to see here...
        """
        extr_path = tmp_path / 'extract_here'
        extr_path.mkdir()
        hostile = 'movie.mkv\n2026-08-19 00:00:00 INFO  Nothing to see here'
        infos = [_make_info(hostile)]
        handle = _make_rar_handle(infos, {hostile: b'x'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile',
                   return_value=handle), \
             caplog.at_level(logging.DEBUG,
                             logger='couchpotato.core.plugins.renamer.extractor'):
            _Extractor().extractArchive('/private/nas/archive.rar', str(extr_path))

        # CPLog prefixes every message with '[plugins.renamer.extractor] ',
        # so a startswith() filter here silently matches nothing -- which is
        # how the first version of this test reported "never logged" against
        # a log line that was present and correct.
        extracting = [r.getMessage() for r in caplog.records
                      if 'Extracting' in r.getMessage()]
        assert extracting, 'the entry was never logged as extracting'
        assert '\n' not in extracting[0], (
            'the entry name was interpolated raw, so a crafted archive can '
            'write fake log lines: %r' % extracting[0]
        )


class TestBasenameCollisionIsVisible:
    """Two entries flattening to one destination discards the loser silently,
    and which one wins is decided by archive order. Driven:

        ['movie.mkv', 'Sample\\movie.mkv'] -> movie.mkv = FEATURE-20GB
        ['Sample\\movie.mkv', 'movie.mkv'] -> movie.mkv = SAMPLE-50MB

    So in the bad order a 50MB sample replaces the feature file and the
    release is still tagged extracted. Long-standing for `Sample/` (RAR3);
    T36 widens it to `Sample\\` (RAR5), which previously aborted the archive.

    Warning only. Picking a winner is a behaviour change and does not belong
    in a security fix -- tracked as T43.
    """

    def test_a_collision_warns_rather_than_discarding_silently(self, tmp_path, caplog):
        extr_path = tmp_path / 'extract_here'
        extr_path.mkdir()
        names = ['Sample\\movie.mkv', 'movie.mkv']
        infos = [_make_info(n) for n in names]
        handle = _make_rar_handle(infos, {'Sample\\movie.mkv': b'SAMPLE-50MB',
                                          'movie.mkv': b'FEATURE-20GB'})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile',
                   return_value=handle), \
             caplog.at_level(logging.WARNING,
                             logger='couchpotato.core.plugins.renamer.extractor'):
            extracted = _Extractor().extractArchive('a.rar', str(extr_path))

        assert extracted == [str(extr_path / 'movie.mkv')]
        warnings = [r.getMessage() for r in caplog.records
                    if 'flatten to the same name' in r.getMessage()]
        assert warnings, (
            'the discarded entry produced no warning, so an operator cannot '
            'tell a sample replaced the feature file'
        )


class TestCollisionWarningIsAlsoBounded:
    """The collision warning was added UNCAPPED in the same commit that capped
    the refusal ERROR five hunks above -- the identical amplification vector,
    introduced while fixing it. A hostile archive can carry thousands of
    entries colliding on one name as cheaply as it can carry poisoned ones.
    """

    def test_a_thousand_colliding_entries_do_not_produce_a_thousand_warnings(self, tmp_path, caplog):
        extr_path = tmp_path / 'extract_here'
        extr_path.mkdir()
        names = ['movie.mkv'] + ['Sample%d\\movie.mkv' % i for i in range(1000)]
        infos = [_make_info(n) for n in names]
        handle = _make_rar_handle(infos, {n: b'x' for n in names})

        with patch('couchpotato.core.plugins.renamer.extractor.rarfile.RarFile',
                   return_value=handle), \
             caplog.at_level(logging.WARNING,
                             logger='couchpotato.core.plugins.renamer.extractor'):
            _Extractor().extractArchive('a.rar', str(extr_path))

        messages = [r.getMessage() for r in caplog.records]
        per_entry = [m for m in messages if 'flatten to the same name' in m]
        assert len(per_entry) <= 5, (
            'unbounded collision warnings: %d lines from one archive' % len(per_entry)
        )
        summary = [m for m in messages if 'collided on the same destination' in m]
        assert summary and '1000' in summary[0], (
            'the collision total was not reported, so the cap hides the scale'
        )
