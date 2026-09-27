"""A partial full-library scan is not evidence that a movie was deleted."""

import threading

from couchpotato.core.plugins.scanner.file_detector import FileDetectorMixin
from couchpotato.core.plugins.scanner.folder_scanner import FolderScannerMixin


class LibraryScanner(FileDetectorMixin, FolderScannerMixin):
    def shuttingDown(self):
        return False

    def filesizeBetween(self, file_path, file_size=None):
        return file_path.endswith('.mkv')

    def getFileSize(self, file_path):
        return 250

    def getMetaData(self, group, folder='', release_download=None):
        return {}

    def getCPImdb(self, file_path):
        return 'tt1111111' if 'Known' in file_path else None

    def getReleaseNameYear(self, identifier, file_name=None):
        return {'name': 'Other', 'year': '2002'}


def _run_full_scan(tmp_path, monkeypatch, *, files=('Known.2001.mkv', 'Other.2002.mkv'),
                   walk_error=False, dispatch_error=False, no_media_group=False,
                   full=True, stat_error=False, vanish_before_scan=False):
    import couchpotato.core.plugins.manage as manage_module
    import couchpotato.core.plugins.scanner.folder_scanner as scanner_module

    library = tmp_path / 'library'
    library.mkdir()
    for name in files:
        (library / name).write_bytes(b'movie')

    scanner = LibraryScanner()
    if stat_error:
        size_calls = []

        def get_file_size(path):
            if 'Other' not in path:
                return 250
            size_calls.append(path)
            return None if stat_error is True or len(size_calls) > 1 else 250

        monkeypatch.setattr(scanner, 'getFileSize', get_file_size)
        monkeypatch.setattr(scanner, 'filesizeBetween',
                            FileDetectorMixin.filesizeBetween.__get__(scanner, LibraryScanner))
    monkeypatch.setattr(scanner_module, 'getImdb', lambda path, check_inside=False: None)
    monkeypatch.setattr(scanner_module, 'get_db',
                        lambda: (_ for _ in ()).throw(RuntimeError('no db')))
    if walk_error:
        def partial_walk(folder, followlinks=False, onerror=None):
            yield str(library), [], ['Known.2001.mkv']
            error = OSError('walk stopped after first movie')
            if walk_error == 'callback':
                onerror(error)
            else:
                raise error

        monkeypatch.setattr(scanner_module.os, 'walk', partial_walk)
    if no_media_group:
        original_get_media_files = scanner.getMediaFiles

        def get_media_files(group_files):
            if any('Other' in path for path in group_files):
                return set()
            return original_get_media_files(group_files)

        monkeypatch.setattr(scanner, 'getMediaFiles', get_media_files)
    deleted = []
    added = []
    timestamps = []
    movies = [
        {'_id': 'known', 'status': 'done', 'identifiers': {'imdb': 'tt1111111'}, 'releases': []},
        {'_id': 'unresolved', 'status': 'done', 'identifiers': {'imdb': 'tt2222222'}, 'releases': []},
    ]

    def fire(event, *args, **kwargs):
        if event == 'scanner.scan':
            kwargs.pop('single', None)
            if vanish_before_scan:
                library.rename(tmp_path / 'disconnected-library')
            if dispatch_error:
                if dispatch_error != 'before':
                    kwargs['on_found'](
                        {'media': {'_id': 'known'}, 'identifier': 'tt1111111'}, 2, 1)
                # The real event dispatcher returns [] after swallowing an
                # exception, even when a callback already ran.
                return []
            return scanner.scan(**kwargs)
        if event == 'quality.guess':
            return None
        if event == 'movie.search':
            return [{'title': 'Other', 'year': 2002}]
        if event == 'movie.info':
            return {'imdb': kwargs['identifier']}
        if event == 'media.list':
            return len(movies), movies
        if event == 'media.delete':
            deleted.append(kwargs['media_id'])
        if event == 'release.add':
            added.append(kwargs['group']['identifier'])
        return None

    monkeypatch.setattr(manage_module, 'fireEvent', fire)
    monkeypatch.setattr(scanner_module, 'fireEvent', fire)
    monkeypatch.setattr(manage_module.Manage, 'conf',
                        lambda self, key, **kw: True if key == 'cleanup' else None)
    monkeypatch.setattr(manage_module.Manage, 'directories', lambda self: [str(library)])
    monkeypatch.setattr(manage_module.Manage, 'isDisabled', lambda self: False)
    monkeypatch.setattr(manage_module.Manage, 'shuttingDown', lambda self: False)
    def env_prop(key, value=None, **kwargs):
        if value is not None:
            timestamps.append((key, value))
        return 0

    monkeypatch.setattr(manage_module.Env, 'prop', env_prop)
    monkeypatch.setattr(manage_module.time, 'sleep', lambda seconds: None)
    plugin = manage_module.Manage.__new__(manage_module.Manage)
    plugin._progress_lock = threading.Lock()
    plugin.in_progress = False

    plugin.updateLibrary(full=full)

    return deleted, added, timestamps


def test_unresolved_second_movie_cannot_authorise_cleanup_of_its_record(tmp_path, monkeypatch, caplog):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch)

    assert 'tt1111111' in added
    assert 'unresolved' not in deleted
    assert timestamps == []
    warnings = [record.message for record in caplog.records
                if 'Skipping library cleanup:' in record.message]
    assert warnings
    assert all(str(tmp_path) not in message for message in warnings)


def test_partial_walk_after_first_movie_cannot_authorise_cleanup(tmp_path, monkeypatch, caplog):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch, walk_error=True)

    assert 'tt1111111' in added
    assert 'unresolved' not in deleted
    assert timestamps == []
    gathering_errors = [record.message for record in caplog.records
                        if 'Failed getting files' in record.message
                        or 'Failed gathering files' in record.message]
    assert gathering_errors
    assert all(str(tmp_path) not in message for message in gathering_errors)


def test_walk_onerror_after_first_movie_cannot_authorise_cleanup(tmp_path, monkeypatch):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch, walk_error='callback')

    assert 'tt1111111' in added
    assert 'unresolved' not in deleted
    assert timestamps == []


def test_dispatcher_failure_after_first_callback_cannot_authorise_cleanup(tmp_path, monkeypatch):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch, dispatch_error=True)

    assert 'tt1111111' in added
    assert 'unresolved' not in deleted
    assert timestamps == []


def test_failed_incremental_scan_does_not_advance_last_successful_scan(tmp_path, monkeypatch):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch,
                                                 dispatch_error='before', full=False)

    assert added == []
    assert deleted == []
    assert timestamps == []


def test_directory_vanishing_after_manage_check_does_not_advance_scan(tmp_path, monkeypatch):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch,
                                                 vanish_before_scan=True, full=False)

    assert added == []
    assert deleted == []
    assert timestamps == []


def test_group_without_a_movie_file_cannot_authorise_cleanup(tmp_path, monkeypatch):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch, no_media_group=True)

    assert 'tt1111111' in added
    assert 'unresolved' not in deleted
    assert timestamps == []


def test_unreadable_movie_size_cannot_authorise_cleanup(tmp_path, monkeypatch):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch, stat_error=True)

    assert 'tt1111111' in added
    assert 'unresolved' not in deleted
    assert timestamps == []


def test_size_failure_after_first_success_cannot_authorise_cleanup(tmp_path, monkeypatch):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch, stat_error='second')

    assert 'tt1111111' in added
    assert 'unresolved' not in deleted
    assert timestamps == []


def test_complete_scan_still_removes_a_genuinely_missing_done_movie(tmp_path, monkeypatch):
    deleted, added, timestamps = _run_full_scan(tmp_path, monkeypatch, files=('Known.2001.mkv',))

    assert 'tt1111111' in added
    assert 'unresolved' in deleted
    assert timestamps
