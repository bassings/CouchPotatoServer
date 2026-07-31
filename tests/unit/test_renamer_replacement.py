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
            # A real move, so the tests can assert on the resulting FILE rather
            # than on which arguments happened to be passed -- the
            # implementation is free to stage through a temp name.
            #
            # It must also REFUSE an existing destination, exactly as the real
            # MoverMixin.moveFile does (mover.py: raise 'Destination "%s"
            # already exists'). A plain shutil.move overwrites, which made this
            # stub more permissive than production and hid the stale-staging
            # deadlock: the mutation removing that guard survived the whole
            # suite.
            self.moved.append((src, dst))
            if os.path.exists(dst) and os.path.isfile(dst):
                raise Exception('Destination "%s" already exists' % dst)
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
    # A genuine upgrade: 1080p replacing 720p. The group must carry the media
    # doc and the incoming quality, because replacement is now gated on an
    # actual comparison -- without them the code correctly FAILS SAFE and keeps
    # the file on disk.
    media = {'_id': 'movie-1', 'releases': [
        {'_id': 'rel-old', 'status': 'done', 'quality': '720p', 'is_3d': False,
         'files': {'movie': [dst]}},
    ]}
    return {'src': src, 'dst': dst, 'media': media,
            'source_folder': os.path.dirname(src)}


def _run(rec, monkeypatch, scene):
    rec.install(monkeypatch)
    monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent',
                        lambda name, *a, **k: 'higher' if name == 'quality.ishigher' else None)
    plugin = rec.plugin
    rename_files = {scene['src']: scene['dst']}
    group = {'parentdir': scene['source_folder'], 'media': scene['media'],
             'meta_data': {'quality': {'identifier': '1080p', 'is_3d': 0}}}

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


# --- Quality gating -----------------------------------------------------
#
# Replacing without comparing quality destroys data the user cannot get back.
# The setting is "Remove LOWER/EQUAL quality copies of a release after
# downloading" (renamer/api.py) -- the comparison is the point of it, and the
# first implementation ignored it entirely.
#
# The FEAT-008 restore flow reaches this directly: restore marks the held
# release 'ignored', so single()'s has_better_quality gate is 0 on EVERY rung;
# the searcher walks the profile best-first, and if the top rung finds nothing
# a lower rung downloads. With the default naming template that lands on the
# same path as the copy already there.

def _quality_scene(tmp_path, library_quality, library_content):
    dst = _make(tmp_path, 'library/Some Movie (2020)/Some Movie.mkv', library_content)
    src = _make(tmp_path, 'downloads/Some.Movie.2020-GRP/movie.mkv', 'INCOMING')
    media = {'_id': 'movie-1', 'profile_id': 'p1', 'releases': [
        {'_id': 'rel-old', 'status': 'done', 'quality': library_quality,
         'is_3d': False, 'files': {'movie': [dst]}},
    ]}
    return {'src': src, 'dst': dst, 'media': media,
            'source_folder': os.path.dirname(src)}


def _run_with_quality(rec, monkeypatch, scene, incoming_quality, ranking):
    """`ranking` maps (incoming, existing) -> what quality.ishigher returns."""
    rec.install(monkeypatch)

    def _fire(name, *a, **k):
        if name == 'quality.ishigher':
            return ranking.get((a[0]['identifier'], a[1]['identifier']), 'lower')
        return None

    monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent', _fire)
    group = {'parentdir': scene['source_folder'], 'media': scene['media'],
             'meta_data': {'quality': {'identifier': incoming_quality, 'is_3d': 0}}}
    rec.plugin._moveRenamedFiles({scene['src']: scene['dst']}, group)


class TestALowerQualityDownloadNeverDestroysABetterCopy:

    def test_a_720p_download_does_not_overwrite_a_2160p_library_copy(self, tmp_path, monkeypatch):
        scene = _quality_scene(tmp_path, '2160p', '2160p REMUX 60GB')
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})

        _run_with_quality(rec, monkeypatch, scene, '720p', {('720p', '2160p'): 'lower'})

        assert Path(scene['dst']).read_text() == '2160p REMUX 60GB', (
            'a lower-quality download destroyed the better library copy -- '
            'unrecoverable'
        )
        assert os.path.exists(scene['src']), 'and the download was thrown away too'
        assert rec.deleted_folders == [], 'cleaned up after refusing the move'

    def test_an_unknown_existing_quality_is_not_replaced(self, tmp_path, monkeypatch):
        """Fail safe: if we cannot tell what is on disk, keep it."""
        scene = _quality_scene(tmp_path, '1080p', 'SOMETHING')
        scene['media']['releases'] = []          # nothing matches this path
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})

        _run_with_quality(rec, monkeypatch, scene, '1080p', {})

        assert Path(scene['dst']).read_text() == 'SOMETHING', (
            'replaced a file whose quality could not be determined'
        )


class TestAnUpgradeStillReplaces:
    """The other direction -- the gate must not block real upgrades, or the
    whole feature is inert."""

    def test_a_2160p_download_replaces_a_720p_library_copy(self, tmp_path, monkeypatch):
        scene = _quality_scene(tmp_path, '720p', '720p SMALL')
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})

        _run_with_quality(rec, monkeypatch, scene, '2160p', {('2160p', '720p'): 'higher'})

        assert Path(scene['dst']).read_text() == 'INCOMING', 'the upgrade did not land'

    def test_an_equal_quality_download_replaces(self, tmp_path, monkeypatch):
        """"Remove lower/EQUAL quality copies" -- re-grabbing the same rung to
        replace a bad encode is the case FEAT-008 exists for."""
        scene = _quality_scene(tmp_path, '1080p', 'BAD ENCODE')
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})

        _run_with_quality(rec, monkeypatch, scene, '1080p', {('1080p', '1080p'): 'equal'})

        assert Path(scene['dst']).read_text() == 'INCOMING'


class TestAStaleStagingFileDoesNotDeadlockTheMovie:
    """A fixed staging name plus moveFile's "Destination already exists" guard
    meant one interrupted replacement wedged that movie forever: every later
    scan failed identically, the library kept the old copy, the download was
    never cleaned up, and a full-size orphan sat in the library folder that
    CouchPotato cannot see. Reachable whenever library and downloads are
    different mounts (the normal Docker layout), because moveFile is then a
    full copy that can take minutes -- any restart in that window leaves it."""

    def test_a_leftover_staging_file_does_not_block_the_replacement(self, scene, monkeypatch, tmp_path):
        stale = scene['dst'] + '.cp_incoming'
        with open(stale, 'w') as fh:
            fh.write('INTERRUPTED EARLIER')

        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})
        _run(rec, monkeypatch, scene)

        assert Path(scene['dst']).read_text() == 'NEW BETTER COPY', (
            'a leftover staging file wedged this movie permanently'
        )
        leftovers = [p for p in os.listdir(os.path.dirname(scene['dst']))
                     if p.endswith('.cp_incoming')]
        assert leftovers == [], 'left a staging file behind: %r' % leftovers

    def test_a_failed_replacement_cleans_up_its_staging_file(self, scene, monkeypatch, tmp_path):
        """Otherwise the failure itself creates the wedge for next time."""
        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})
        rec.install(monkeypatch)
        monkeypatch.setattr('couchpotato.core.plugins.renamer.main.fireEvent',
                            lambda name, *a, **k: 'higher' if name == 'quality.ishigher' else None)

        real_move = type(rec.plugin).moveFile

        def _move_then_fail(_self, src, dst, **kw):
            real_move(_self, src, dst, **kw)
            raise OSError('interrupted after the copy')

        monkeypatch.setattr(type(rec.plugin), 'moveFile', _move_then_fail, raising=False)
        group = {'parentdir': scene['source_folder'], 'media': scene['media'],
                 'meta_data': {'quality': {'identifier': '1080p', 'is_3d': 0}}}
        rec.plugin._moveRenamedFiles({scene['src']: scene['dst']}, group)

        leftovers = [p for p in os.listdir(os.path.dirname(scene['dst']))
                     if p.endswith('.cp_incoming')]
        assert leftovers == [], 'a failed replacement left its staging file: %r' % leftovers
        assert Path(scene['dst']).read_text() == 'OLD COPY', 'and destroyed the library copy'


class TestAMissingSourceMidGroupStopsCleanup:
    """Finding 7: mutating `skipped = True` on the missing-source branch
    SURVIVED the whole suite, because every other test skips EVERY file, so
    cleanup was already suppressed by `moved_any` being false. This exercises
    the mixed case -- movie.mkv moves, movie.srt's source vanished between the
    scan and the move (an ordinary torrent-client/Bazarr race)."""

    def test_cleanup_is_skipped_when_one_source_disappeared(self, tmp_path, monkeypatch):
        movie_src = _make(tmp_path, 'downloads/Some.Movie-GRP/movie.mkv', 'NEW')
        # _processGroup creates the destination folder before calling this.
        (tmp_path / 'library/Some Movie (2020)').mkdir(parents=True, exist_ok=True)
        movie_dst = str(tmp_path / 'library/Some Movie (2020)/Some Movie.mkv')
        vanished = str(tmp_path / 'downloads/Some.Movie-GRP/movie.srt')
        sub_dst = str(tmp_path / 'library/Some Movie (2020)/Some Movie.srt')

        rec = _Recorder(tmp_path, {'remove_lower_quality_copies': True, 'cleanup': True})
        rec.install(monkeypatch)
        rec.plugin._moveRenamedFiles({movie_src: movie_dst, vanished: sub_dst},
                                     {'parentdir': os.path.dirname(movie_src)})

        assert Path(movie_dst).read_text() == 'NEW'
        assert rec.deleted_folders == [], (
            'cleaned up a source folder even though one file never moved'
        )
