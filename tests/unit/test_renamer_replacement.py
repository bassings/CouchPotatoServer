"""The renamer must be able to land an upgrade, and must never discard one.

Two defects in `Renamer._processGroup`'s move loop
(couchpotato/core/plugins/renamer/main.py):

1. `if os.path.exists(dst): continue` — a replacement copy is NEVER moved into
   the library while the old file is there. Combined with the default naming
   template (`<namethe> (<year>)` / `<thename><cd>.<ext>`, which carries no
   quality/group/source token, so every copy of a movie renames to the SAME
   path) this means an upgrade essentially never lands on a default install.

2. `cleanup` then deletes the source folder. So the file the user just
   downloaded is skipped AND destroyed -- data loss, on the happy path of every
   upgrade.

`remove_lower_quality_copies` ("Delete Others -- Remove lower/equal quality
copies of a release after downloading", default True) is declared in
renamer/api.py and read nowhere in the codebase. This implements it.
"""
import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from couchpotato.core.plugins.renamer.main import Renamer


class _Recorder:
    """A Renamer with the filesystem and config stubbed."""

    def __init__(self, tmp_path, conf):
        self.plugin = Renamer.__new__(Renamer)
        self.moved = []
        self.deleted_folders = []
        self.removed_files = []
        self._conf = conf
        self.tmp_path = tmp_path

    def install(self, monkeypatch):
        monkeypatch.setattr(type(self.plugin), 'conf',
                            lambda _self, key, default=None, **kw: self._conf.get(key, default),
                            raising=False)
        def _move(_self, src, dst, **kw):
            # A real move, so the tests can assert on the resulting FILE
            # rather than on which arguments happened to be passed. The
            # implementation is free to stage through a temp name.
            self.moved.append((src, dst))
            shutil.move(src, dst)

        monkeypatch.setattr(type(self.plugin), 'moveFile', _move, raising=False)
        monkeypatch.setattr(type(self.plugin), 'deleteFolder',
                            lambda _self, folder, **kw: self.deleted_folders.append(folder),
                            raising=False)


def _make(tmp_path, name, content):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return str(p)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    """An existing library file, and a freshly downloaded replacement that
    renames to exactly the same destination -- the default-naming case."""
    dst = _make(tmp_path, 'library/Some Movie (2020)/Some Movie.mkv', 'OLD COPY')
    src = _make(tmp_path, 'downloads/Some.Movie.2020.1080p-GRP/movie.mkv', 'NEW BETTER COPY')
    return {'src': src, 'dst': dst, 'source_folder': os.path.dirname(src)}


def _run(rec, monkeypatch, scene):
    rec.install(monkeypatch)
    plugin = rec.plugin
    rename_files = {scene['src']: scene['dst']}
    group = {'parentdir': scene['source_folder']}

    # Drive just the move + cleanup section via the real code path.
    plugin._moveRenamedFiles(rename_files, group)
    return rec


class TestAnUpgradeCanLand:

    def test_the_existing_file_is_replaced_when_delete_others_is_on(self, scene, monkeypatch, tmp_path):
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})
        _run(rec, monkeypatch, scene)

        assert Path(scene['dst']).read_text() == 'NEW BETTER COPY', (
            'the replacement was never moved in, so the upgrade cannot land '
            'and the download is about to be deleted by cleanup'
        )
        assert not os.path.exists(scene['src']), 'the source was left behind'

    def test_the_download_is_not_destroyed_when_the_move_is_skipped(self, scene, monkeypatch, tmp_path):
        """Delete Others OFF: the existing file is kept, so the incoming file
        must NOT be silently thrown away with the source folder."""
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': False, 'cleanup': True})
        _run(rec, monkeypatch, scene)

        assert Path(scene['dst']).read_text() == 'OLD COPY', (
            'replaced the library file despite Delete Others being off'
        )
        assert rec.deleted_folders == [], (
            'deleted the source folder containing a download that was never '
            'moved in -- the file the user just downloaded is gone'
        )


class TestCleanupIsSafe:

    def test_cleanup_still_runs_when_everything_moved(self, scene, monkeypatch, tmp_path):
        """The other direction: cleanup must not be disabled in general."""
        os.remove(scene['dst'])          # nothing in the way
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})
        _run(rec, monkeypatch, scene)

        assert Path(scene['dst']).read_text() == 'NEW BETTER COPY'
        assert rec.deleted_folders == [scene['source_folder']]

    def test_a_missing_source_does_not_trigger_cleanup(self, scene, monkeypatch, tmp_path):
        os.remove(scene['src'])
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})
        _run(rec, monkeypatch, scene)

        assert rec.deleted_folders == [], 'cleaned up after moving nothing'


class TestAFailedReplacementLeavesTheUserWithACopy:
    """The destructive direction, which the spec calls out as the risk of this
    change: it writes to the user's library. If the incoming file cannot be
    put in place, the existing one must still be there afterwards -- an
    implementation that deletes first and moves second would leave the user
    with neither copy."""

    def test_the_existing_file_survives_a_failed_move(self, scene, monkeypatch, tmp_path):
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})
        rec.install(monkeypatch)

        def _explode(_self, src, dst, **kw):
            raise OSError('disk full')

        monkeypatch.setattr(type(rec.plugin), 'moveFile', _explode, raising=False)

        rec.plugin._moveRenamedFiles({scene['src']: scene['dst']},
                                     {'parentdir': scene['source_folder']})

        assert Path(scene['dst']).read_text() == 'OLD COPY', (
            'the library copy was destroyed by a replacement that never landed'
        )
        assert os.path.exists(scene['src']), 'the download was lost too'
        assert rec.deleted_folders == [], 'cleaned up after a failure'

    def test_no_staging_file_is_left_behind_on_success(self, scene, monkeypatch, tmp_path):
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})
        _run(rec, monkeypatch, scene)

        leftovers = [p for p in os.listdir(os.path.dirname(scene['dst']))
                     if p.endswith('.cp_incoming')]
        assert leftovers == [], 'left a staging file in the library: %r' % leftovers


class TestAPartiallyMovedGroupIsNotCleanedUp:
    """The case that actually exercises the skip guard.

    Caught by mutation: deleting `if skipped: return` left every other test in
    this file green, because they all skip EVERY file, so `moved_any` is false
    and cleanup is skipped for an unrelated reason. A release is normally a
    GROUP (the movie plus subtitles, nfo, artwork) -- if one file lands and
    another does not, the source folder still holds something the user needs
    and must not be deleted.
    """

    def test_cleanup_is_skipped_when_only_some_files_moved(self, tmp_path, monkeypatch):
        movie_src = _make(tmp_path, 'downloads/Some.Movie.2020-GRP/movie.mkv', 'NEW')
        sub_src = _make(tmp_path, 'downloads/Some.Movie.2020-GRP/movie.srt', 'SUBS')
        movie_dst = str(tmp_path / 'library/Some Movie (2020)/Some Movie.mkv')
        sub_dst = _make(tmp_path, 'library/Some Movie (2020)/Some Movie.srt', 'OLD SUBS')

        # Delete Others OFF, so the subtitle (whose destination exists) is
        # skipped while the movie file moves cleanly.
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': False, 'cleanup': True})
        rec.install(monkeypatch)

        rec.plugin._moveRenamedFiles(
            {movie_src: movie_dst, sub_src: sub_dst},
            {'parentdir': os.path.dirname(movie_src)})

        assert Path(movie_dst).read_text() == 'NEW', 'the movie file should have moved'
        assert Path(sub_dst).read_text() == 'OLD SUBS', 'the existing subtitle should be kept'
        assert os.path.exists(sub_src), 'the incoming subtitle was destroyed'
        assert rec.deleted_folders == [], (
            'deleted a source folder that still held a file which was never '
            'moved in -- that file is now gone'
        )
