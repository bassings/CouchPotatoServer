"""A skipped move must never destroy the file the user just downloaded.

`Renamer._moveRenamedFiles` skips a file whose destination already exists --
that is long-standing upstream behaviour and is left alone. The bug was what
came next: `cleanup` deleted the source folder regardless, so a skipped file
was skipped AND destroyed.

That is not an edge case. The default naming template is
`<namethe> (<year>)` / `<thename><cd>.<ext>` (renamer/api.py), which carries no
quality, group or source token -- so every copy of a movie renames to the same
path, and every upgrade hits the skip branch. The user's download was silently
deleted on the happy path of every upgrade.

Scope note: an earlier version of this work also implemented REPLACEMENT (the
declared-but-never-read `remove_lower_quality_copies` setting). It was removed
after two attempts, both of which endangered the user's irreplaceable library --
see `_moveRenamedFiles`'s docstring and
specs/FEAT-009-durable-set-aside-and-upgrade-replacement.md. These tests cover
the safety fix only, which adds no destructive capability.
"""
import os
import shutil
from pathlib import Path

import pytest

from couchpotato.core.plugins.renamer.main import Renamer


def _make(tmp_path, name, content):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return str(p)


class _Recorder:
    """A Renamer with config and folder-deletion stubbed, but a REAL move."""

    def __init__(self, tmp_path, conf):
        self.plugin = Renamer.__new__(Renamer)
        self.moved = []
        self.deleted_folders = []
        self._conf = conf
        self.tmp_path = tmp_path

    def install(self, monkeypatch):
        monkeypatch.setattr(type(self.plugin), 'conf',
                            lambda _self, key, default=None, **kw: self._conf.get(key, default),
                            raising=False)
        monkeypatch.setattr(type(self.plugin), 'deleteFolder',
                            lambda _self, folder, **kw: self.deleted_folders.append(folder),
                            raising=False)

        def _move(_self, src, dst, **kw):
            # A real move, so assertions can be made on the resulting FILE
            # rather than on which arguments were passed.
            #
            # It must also REFUSE an existing destination, exactly as the real
            # MoverMixin.moveFile does (mover.py: raise 'Destination "%s"
            # already exists'). A plain shutil.move overwrites, which would make
            # this stub more permissive than production -- a stub gentler than
            # the code it replaces has already hidden two real defects on this
            # branch.
            self.moved.append((src, dst))
            if os.path.exists(dst) and os.path.isfile(dst):
                raise Exception('Destination "%s" already exists' % dst)
            shutil.move(src, dst)

        monkeypatch.setattr(type(self.plugin), 'moveFile', _move, raising=False)


@pytest.fixture
def scene(tmp_path):
    """An existing library file, and a freshly downloaded file that renames to
    exactly the same destination -- the default-naming case."""
    dst = _make(tmp_path, 'library/Some Movie (2020)/Some Movie.mkv', 'THE COPY ALREADY IN THE LIBRARY')
    src = _make(tmp_path, 'downloads/Some.Movie.2020.1080p-GRP/movie.mkv', 'THE FILE JUST DOWNLOADED')
    return {'src': src, 'dst': dst, 'source_folder': os.path.dirname(src)}


def _run(rec, monkeypatch, scene):
    rec.install(monkeypatch)
    rec.plugin._moveRenamedFiles({scene['src']: scene['dst']},
                                 {'parentdir': scene['source_folder']})


class TestASkippedMoveDoesNotDestroyTheDownload:

    def test_the_download_survives_when_the_destination_exists(self, scene, monkeypatch, tmp_path):
        rec = _Recorder(tmp_path, {'cleanup': True})
        _run(rec, monkeypatch, scene)

        assert Path(scene['dst']).read_text() == 'THE COPY ALREADY IN THE LIBRARY', (
            'the library copy must be left alone'
        )
        assert os.path.exists(scene['src']), (
            'the file the user just downloaded was deleted after being skipped'
        )
        assert rec.deleted_folders == [], (
            'deleted the source folder holding a download that never moved in'
        )

    def test_a_missing_source_does_not_trigger_cleanup(self, scene, monkeypatch, tmp_path):
        os.remove(scene['src'])
        rec = _Recorder(tmp_path, {'cleanup': True})
        _run(rec, monkeypatch, scene)

        assert rec.deleted_folders == [], 'cleaned up after moving nothing'

    def test_a_failed_move_does_not_trigger_cleanup(self, scene, monkeypatch, tmp_path):
        os.remove(scene['dst'])
        rec = _Recorder(tmp_path, {'cleanup': True})
        rec.install(monkeypatch)
        monkeypatch.setattr(type(rec.plugin), 'moveFile',
                            lambda _self, src, dst, **kw: (_ for _ in ()).throw(OSError('disk full')),
                            raising=False)

        rec.plugin._moveRenamedFiles({scene['src']: scene['dst']},
                                     {'parentdir': scene['source_folder']})

        assert os.path.exists(scene['src']), 'the download was lost after a failed move'
        assert rec.deleted_folders == []


class TestAPartiallyMovedGroupIsNotCleanedUp:
    """The case that actually exercises the skip guard.

    Caught by mutation: deleting `if skipped: return` left every single-file
    test green, because they all skip the ONLY file, so `moved_any` is false and
    cleanup is suppressed for an unrelated reason. A release is normally a GROUP
    (movie plus subtitles, nfo, artwork) -- if one file lands and another does
    not, the source folder still holds something the user needs.
    """

    def test_cleanup_is_skipped_when_only_some_files_moved(self, tmp_path, monkeypatch):
        movie_src = _make(tmp_path, 'downloads/Some.Movie-GRP/movie.mkv', 'NEW')
        sub_src = _make(tmp_path, 'downloads/Some.Movie-GRP/movie.srt', 'SUBS')
        movie_dst = str(tmp_path / 'library/Some Movie (2020)/Some Movie.mkv')
        sub_dst = _make(tmp_path, 'library/Some Movie (2020)/Some Movie.srt', 'OLD SUBS')

        rec = _Recorder(tmp_path, {'cleanup': True})
        rec.install(monkeypatch)
        rec.plugin._moveRenamedFiles({movie_src: movie_dst, sub_src: sub_dst},
                                     {'parentdir': os.path.dirname(movie_src)})

        assert Path(movie_dst).read_text() == 'NEW', 'the movie file should have moved'
        assert Path(sub_dst).read_text() == 'OLD SUBS', 'the existing subtitle is kept'
        assert os.path.exists(sub_src), 'the incoming subtitle was destroyed'
        assert rec.deleted_folders == [], (
            'deleted a source folder that still held a file which never moved'
        )


class TestCleanupStillRunsWhenItShould:
    """The other direction -- the guard must not disable cleanup in general."""

    def test_a_clean_move_still_cleans_up(self, scene, monkeypatch, tmp_path):
        os.remove(scene['dst'])
        rec = _Recorder(tmp_path, {'cleanup': True})
        _run(rec, monkeypatch, scene)

        assert Path(scene['dst']).read_text() == 'THE FILE JUST DOWNLOADED'
        assert rec.deleted_folders == [scene['source_folder']]
