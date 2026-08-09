"""Atomic replacement of a library file (FEAT-009B B3b).

This is the only function in the project that destroys an irreplaceable file,
so every test here runs against a REAL filesystem (`tmp_path`) rather than
mocks, and every failure case asserts the same two things:

  * the library file is byte-identical to what it was, and
  * a complete copy of the download still exists somewhere.

Asserting only "the call returned False" would pass for a function that had
already deleted the movie and then errored.

AC-SEC-6 (aliased paths: hardlink, symlink, broken symlink) and AC-SEC-7
(the staging file: unique per attempt, never left behind while the source
survives, never deleted when it is the only complete copy).

Deliberately NOT claimed: AC-DATA-3, which is about releases belonging to
the group's own media and needs a real SQLiteAdapter -- this file never
touches the database. An earlier version of this docstring cited it, and
an over-claimed citation is worse than none: it tells the next reader a
criterion is covered when nothing here can cover it.
"""
import hashlib
import os
import shutil

import pytest

from couchpotato.core.plugins.renamer.swap import (
    FAILED_SIZE_MISMATCH,
    FAILED_STAGING,
    FAILED_SWAP,
    REFUSED_DESTINATION_IS_SYMLINK,
    REFUSED_DESTINATION_MISSING,
    REFUSED_NO_SOURCE,
    REFUSED_SAME_FILE,
    REPLACED,
    replace_atomically,
)

OLD = b'the existing library copy, 720p' * 40
NEW = b'the better incoming copy, 2160p' * 900


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


@pytest.fixture
def library(tmp_path):
    """A real library file and a real download, on a real filesystem."""
    lib = tmp_path / 'library' / 'The Thing (1982)'
    lib.mkdir(parents=True)
    dst = lib / 'The Thing.mkv'
    dst.write_bytes(OLD)

    dl = tmp_path / 'downloads' / 'The.Thing.1982.2160p'
    dl.mkdir(parents=True)
    src = dl / 'movie.mkv'
    src.write_bytes(NEW)
    return {'src': str(src), 'dst': str(dst), 'dir': lib, 'old_sha': _sha(dst)}


def _real_move(src, dst):
    shutil.move(src, dst)


def _no_stray_staging(directory):
    return [p.name for p in directory.iterdir() if p.name.startswith('.cp-upgrade-')]


class TestTheSuccessfulPath:
    def test_the_better_copy_takes_the_destination(self, library):
        ok, reason = replace_atomically(library['src'], library['dst'], _real_move)
        assert (ok, reason) == (True, REPLACED)
        assert open(library['dst'], 'rb').read() == NEW
        assert not os.path.exists(library['src']), 'a real move should consume the source'

    def test_no_staging_file_is_left_behind(self, library):
        replace_atomically(library['src'], library['dst'], _real_move)
        assert _no_stray_staging(library['dir']) == []

    def test_the_destination_keeps_its_exact_path(self, library):
        """The library file must be replaced in place, not renamed alongside."""
        before = sorted(p.name for p in library['dir'].iterdir())
        replace_atomically(library['src'], library['dst'], _real_move)
        assert sorted(p.name for p in library['dir'].iterdir()) == before


class TestRefusalsTakenBeforeAnythingIsTouched:
    def test_a_missing_source_refuses(self, library):
        os.remove(library['src'])
        ok, reason = replace_atomically(library['src'], library['dst'], _real_move)
        assert (ok, reason) == (False, REFUSED_NO_SOURCE)
        assert _sha(library['dst']) == library['old_sha']

    def test_a_missing_destination_refuses_rather_than_installing(self, library):
        """This function replaces; it does not install. Guessing would turn a
        caller's bug into a file operation."""
        os.remove(library['dst'])
        ok, reason = replace_atomically(library['src'], library['dst'], _real_move)
        assert (ok, reason) == (False, REFUSED_DESTINATION_MISSING)
        assert os.path.exists(library['src']), 'the download must survive'

    def test_a_symlinked_destination_refuses_and_its_target_survives(self, tmp_path, library):
        """AC-SEC-6. Writing through the link would modify a file OUTSIDE the
        library, which is not the file the library thinks it holds."""
        outside = tmp_path / 'outside.mkv'
        outside.write_bytes(b'not the librarys to touch')
        outside_sha = _sha(outside)

        link = library['dir'] / 'linked.mkv'
        link.symlink_to(outside)

        ok, reason = replace_atomically(library['src'], str(link), _real_move)
        assert (ok, reason) == (False, REFUSED_DESTINATION_IS_SYMLINK)
        assert _sha(outside) == outside_sha
        assert os.path.exists(library['src'])

    def test_a_BROKEN_symlink_destination_refuses(self, library):
        """`os.path.exists` follows the link and reports False for a broken
        one, so an `exists` check would have sent this down the
        "nothing to replace" path. `islink` is checked first for that reason."""
        broken = library['dir'] / 'broken.mkv'
        broken.symlink_to(library['dir'] / 'does-not-exist.mkv')
        ok, reason = replace_atomically(library['src'], str(broken), _real_move)
        assert (ok, reason) == (False, REFUSED_DESTINATION_IS_SYMLINK)

    def test_a_hardlink_of_the_source_refuses(self, library):
        """AC-SEC-6. The shipping default `file_action = link` hardlinks the
        download into the library, so source and destination can be the same
        inode -- and moving a file onto itself destroys it."""
        hard = library['dir'] / 'hardlinked.mkv'
        os.link(library['src'], hard)
        ok, reason = replace_atomically(library['src'], str(hard), _real_move)
        assert (ok, reason) == (False, REFUSED_SAME_FILE)
        assert os.path.exists(library['src'])
        assert os.path.exists(hard)


class TestFailuresLeaveTheLibraryIntactAndTheDownloadRecoverable:
    """The whole point of the staging step. In each case the destination must
    be byte-identical and a complete copy of the download must still exist."""

    def test_a_failing_move_leaves_both_files(self, library):
        def _boom(src, dst):
            raise OSError('mount went away')

        ok, reason = replace_atomically(library['src'], library['dst'], _boom)
        assert (ok, reason) == (False, FAILED_STAGING)
        assert _sha(library['dst']) == library['old_sha']
        assert open(library['src'], 'rb').read() == NEW
        assert _no_stray_staging(library['dir']) == []

    def test_a_truncated_staging_file_is_caught_before_the_swap(self, library):
        """The verify step exists for exactly this: a move that "succeeded"
        but did not write everything."""
        def _truncating_move(src, dst):
            with open(dst, 'wb') as fh:
                fh.write(open(src, 'rb').read()[:10])

        ok, reason = replace_atomically(library['src'], library['dst'], _truncating_move)
        assert (ok, reason) == (False, FAILED_SIZE_MISMATCH)
        assert _sha(library['dst']) == library['old_sha']
        assert open(library['src'], 'rb').read() == NEW
        assert _no_stray_staging(library['dir']) == [], 'source intact, so tidy up'

    def test_a_failing_swap_leaves_the_destination_untouched(self, library, monkeypatch):
        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.swap.os.replace',
            lambda a, b: (_ for _ in ()).throw(OSError('cross-device')),
        )
        ok, reason = replace_atomically(library['src'], library['dst'], _real_move)
        assert (ok, reason) == (False, FAILED_SWAP)
        assert _sha(library['dst']) == library['old_sha']


class TestTheStagedFileIsNeverTheOnlyCopyWeDelete:
    """The subtle rule, and the one worth getting wrong slowly.

    `move` may consume the source (a real move) or leave it (copy/link). After
    a failure the staged file is therefore sometimes the ONLY complete copy of
    the download, and tidying it away would destroy hours of fetching --
    turning a recoverable failure into a loss.
    """

    def test_when_the_source_was_consumed_the_staged_copy_is_KEPT(self, library, monkeypatch):
        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.swap.os.replace',
            lambda a, b: (_ for _ in ()).throw(OSError('boom')),
        )
        ok, reason = replace_atomically(library['src'], library['dst'], _real_move)

        assert (ok, reason) == (False, FAILED_SWAP)
        assert not os.path.exists(library['src']), 'precondition: the move consumed it'
        stray = _no_stray_staging(library['dir'])
        assert len(stray) == 1, 'the only complete copy of the download was deleted'
        assert (library['dir'] / stray[0]).read_bytes() == NEW
        assert _sha(library['dst']) == library['old_sha']

    def test_when_the_source_survives_the_staged_copy_is_removed(self, library, monkeypatch):
        """The control. Keeping every staged file regardless would fill the
        library with .part files, so the rule has to discriminate."""
        def _copying_move(src, dst):
            shutil.copyfile(src, dst)      # leaves the source, as `copy` mode does

        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.swap.os.replace',
            lambda a, b: (_ for _ in ()).throw(OSError('boom')),
        )
        ok, reason = replace_atomically(library['src'], library['dst'], _copying_move)

        assert (ok, reason) == (False, FAILED_SWAP)
        assert os.path.exists(library['src'])
        assert _no_stray_staging(library['dir']) == []

    def test_a_TRUNCATED_source_counts_as_not_intact_so_the_copy_is_kept(self, library, monkeypatch):
        """"The source still exists" is not the same as "a complete copy still
        exists". A half-written source is not a copy of anything."""
        def _move_then_truncate_source(src, dst):
            shutil.copyfile(src, dst)
            with open(src, 'wb') as fh:
                fh.write(b'partial')

        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.swap.os.replace',
            lambda a, b: (_ for _ in ()).throw(OSError('boom')),
        )
        replace_atomically(library['src'], library['dst'], _move_then_truncate_source)
        assert len(_no_stray_staging(library['dir'])) == 1
        assert _sha(library['dst']) == library['old_sha']


class TestTheTOCTOUGuardsActuallyGuard:
    """Both `os.path.getsize` calls are wrapped because the paths were checked
    moments earlier and can vanish in between.

    Review pointed out that adding the guards is not the same as proving them,
    which is CLAUDE.md rule 10 applied to my own fix -- so each one is forced
    to raise here. Without these, an OSError escapes and breaks this
    function's `(ok, reason)` contract, reaching the renamer as an untyped
    failure instead of a named refusal.
    """

    def test_the_source_vanishing_after_its_existence_check_is_a_named_refusal(
        self, library, monkeypatch
    ):
        real_getsize = os.path.getsize

        def _vanishing(path):
            if path == library['src']:
                raise OSError('source removed between the check and the stat')
            return real_getsize(path)

        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.swap.os.path.getsize', _vanishing
        )
        ok, reason = replace_atomically(library['src'], library['dst'], _real_move)
        assert (ok, reason) == (False, REFUSED_NO_SOURCE)
        assert _sha(library['dst']) == library['old_sha']

    def test_an_unstattable_staged_file_is_a_named_failure(self, library, monkeypatch):
        real_getsize = os.path.getsize
        state = {'moved': False}

        def _move_then_break(src, dst):
            shutil.move(src, dst)
            state['moved'] = dst

        def _breaks_on_staging(path):
            if state['moved'] and path == state['moved']:
                raise OSError('staged file unreadable')
            return real_getsize(path)

        monkeypatch.setattr(
            'couchpotato.core.plugins.renamer.swap.os.path.getsize', _breaks_on_staging
        )
        ok, reason = replace_atomically(library['src'], library['dst'], _move_then_break)
        assert (ok, reason) == (False, FAILED_STAGING)
        assert _sha(library['dst']) == library['old_sha']


class TestStagingHappensInTheDestinationDirectory:
    def test_the_staged_file_appears_beside_the_destination(self, library):
        """`os.replace` is atomic only WITHIN a filesystem, and the library and
        download folder are routinely different mounts on this project's target
        deployment. Staging in the source directory would make the final step
        a cross-device copy -- non-atomic, and the whole design would be
        pointless."""
        seen = {}

        def _recording_move(src, dst):
            seen['dst'] = dst
            shutil.move(src, dst)

        replace_atomically(library['src'], library['dst'], _recording_move)
        assert os.path.dirname(seen['dst']) == os.path.dirname(library['dst'])

    def test_the_staging_name_is_unique_per_attempt(self, library):
        names = set()

        def _recording_move(src, dst):
            names.add(os.path.basename(dst))
            raise OSError('stop here')

        for _ in range(5):
            replace_atomically(library['src'], library['dst'], _recording_move)
        assert len(names) == 5, 'staging names collided: %s' % names
