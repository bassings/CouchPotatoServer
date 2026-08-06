"""Pins the current behaviour of `MoverMixin.moveFile`
(couchpotato/core/plugins/renamer/mover.py:16-78) -- the function that moves,
copies, hardlinks or symlinks the user's completed download into the library.
It had no real tests before this file: the only existing coverage
(`test_renamer_cleanup_safety.py`) monkeypatches `moveFile` away entirely.

Fixture rules, not negotiable (spec: specs/REMEDIATION-2026-08.md T1.1):
  - Real files under `tmp_path`, real `shutil`, real `os`. The only things
    ever stubbed are `self.conf` and `Env.getPermission`.
  - The failure-injection tests below (the "Failed move ..." and "fallback"
    groups) are the one deliberate exception: forcing the *specific* partial
    or poisoned filesystem state a real disk-full or dropped-mount failure
    leaves behind is not reproducible on a single local filesystem through
    `os.rename` alone, because same-filesystem rename is atomic -- it cannot
    leave a partial file. Those tests monkeypatch the exact call that would
    fail in production (`shutil.move`, `shutil.copy`, `link`, `symlink`, or
    `os.rename`) but still perform REAL writes/deletes to reach the documented
    end state, and still assert against the real filesystem afterwards. This
    is failure injection, not a happy-path stub: nothing here makes `moveFile`
    more permissive than production, only more able to fail the way production
    can fail.
  - Distinct, asserted content (THE DOWNLOAD vs THE LIBRARY COPY) at >=1 MiB,
    compared by SHA-256 on the happy paths, so a size-only check cannot pass a
    content assertion.

Three tests below pin behaviour that is a LIVE DATA-LOSS DEFECT, not a design
choice. They are named `test_pins_current_bug_*` and their docstrings explain
why; T1.8 fixes the underlying code and inverts these same assertions.
"""
import hashlib
import os
import shutil
import stat
from pathlib import Path

import pytest

from couchpotato.core.plugins.renamer import mover as mover_module
from couchpotato.core.plugins.renamer.main import Renamer
from couchpotato.environment import Env

# ---------------------------------------------------------------------------
# Fixtures / helpers (local to this file -- no shared helper module, no
# conftest.py, per AC-SIMP-6).
# ---------------------------------------------------------------------------

MIB = 1024 * 1024
PAYLOAD_SIZE = MIB + 37  # >=1 MiB, deliberately not a round number
PERM_MODE = 0o640  # distinctive: not a default umask outcome either way


def _payload(label: str, size: int = PAYLOAD_SIZE) -> bytes:
    """A deterministic, >=1 MiB payload whose content is visibly `label`."""
    unit = ('%s\n' % label).encode()
    reps = size // len(unit) + 1
    return (unit * reps)[:size]


DOWNLOAD = _payload('THE DOWNLOAD')
LIBRARY = _payload('THE LIBRARY COPY')
assert len(DOWNLOAD) == len(LIBRARY) == PAYLOAD_SIZE, 'fixtures must be equal-size, distinct-content'
assert DOWNLOAD != LIBRARY


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _within_tmp_path(tmp_path, *paths):
    """AC-SEC-14: every path handed to moveFile must be a child of tmp_path.

    A test for the os.unlink(old) branch that resolves outside the fixture is
    the one way this suite could itself destroy data.
    """
    root = Path(tmp_path).resolve()
    for p in paths:
        resolved = Path(p).resolve()
        assert resolved == root or root in resolved.parents, (
            '%s is not inside the test tmp_path (%s) -- refusing to call '
            'moveFile with it' % (p, root)
        )


def _mover(monkeypatch, **conf):
    """A Renamer instance (as test_renamer_cleanup_safety.py instantiates it)
    with ONLY `conf` and `Env.getPermission` stubbed."""
    plugin = Renamer.__new__(Renamer)
    monkeypatch.setattr(
        type(plugin), 'conf',
        lambda _self, key, default=None, **kw: conf.get(key, default),
        raising=False,
    )
    monkeypatch.setattr(Env, 'getPermission', lambda _kind: PERM_MODE, raising=False)
    return plugin


def _move(plugin, tmp_path, old, dest, **kw):
    _within_tmp_path(tmp_path, old, dest)
    return plugin.moveFile(old, dest, **kw)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

class TestHappyPaths:

    def test_move_relocates_the_file_and_sets_permission(self, tmp_path, monkeypatch):
        """AC-QA-1. Break: shutil.move -> shutil.copy; 'source is gone' fails."""
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/Movie (2020)/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        plugin = _mover(monkeypatch, file_action='move')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True
        assert not os.path.exists(old), 'the source must be gone after a move'
        assert _sha256_file(dest) == _sha256_bytes(DOWNLOAD)
        assert stat.S_IMODE(os.stat(dest).st_mode) == PERM_MODE

    def test_copy_leaves_the_source_and_creates_an_independent_destination(self, tmp_path, monkeypatch):
        """AC-QA-2. Break: swap copy for link; the inode assertion fails."""
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        plugin = _mover(monkeypatch, file_action='copy')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True
        assert os.path.exists(old), 'copy must not remove the source'
        assert _sha256_file(old) == _sha256_bytes(DOWNLOAD)
        assert _sha256_file(dest) == _sha256_bytes(DOWNLOAD)
        assert os.stat(old).st_ino != os.stat(dest).st_ino, (
            'copy must produce an independent file, not a second name for the same inode'
        )

    def test_link_creates_a_second_name_for_the_same_inode(self, tmp_path, monkeypatch):
        """AC-DATA-2 / AC-QA-3. If tmp_path's filesystem cannot hardlink, this
        must fail loudly (a plain assertion mismatch) rather than skip -- a
        silent skip is how this branch stayed untested in the first place.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        plugin = _mover(monkeypatch, file_action='link')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True
        old_stat = os.stat(old)
        dest_stat = os.stat(dest)
        assert old_stat.st_ino == dest_stat.st_ino, (
            'expected a hardlink (equal inode); got old=%s dest=%s -- moveFile '
            'silently fell back to a copy instead of hardlinking'
            % (old_stat.st_ino, dest_stat.st_ino)
        )
        assert dest_stat.st_nlink == 2
        assert _sha256_file(dest) == _sha256_bytes(DOWNLOAD)

    def test_symlink_reversed_moves_the_file_and_leaves_a_symlink_behind(self, tmp_path, monkeypatch):
        """AC-QA-4."""
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        plugin = _mover(monkeypatch, file_action='symlink_reversed')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True
        assert not os.path.islink(dest), 'the destination must be a real file, not a link'
        assert _sha256_file(dest) == _sha256_bytes(DOWNLOAD)
        assert os.path.islink(old), 'old must become a symlink pointing back at dest'
        assert os.path.realpath(old) == os.path.realpath(dest)

    def test_use_default_reads_default_file_action_not_file_action(self, tmp_path, monkeypatch):
        """AC-QA-5. file_action and default_file_action are set to DIFFERENT
        actions ('copy' vs 'move'); use_default=True must run 'move'. Asserted
        by observing the filesystem, not a mock's call args.
        Break: delete the `if use_default:` block at :23-24.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        plugin = _mover(monkeypatch, file_action='copy', default_file_action='move')

        result = _move(plugin, tmp_path, str(old), str(dest), use_default=True)

        assert result is True
        assert not os.path.exists(old), (
            'use_default=True must read default_file_action (move), not file_action (copy)'
        )
        assert _sha256_file(dest) == _sha256_bytes(DOWNLOAD)


# ---------------------------------------------------------------------------
# Failed move recovery (the try/except inside the plain "move" branch)
# ---------------------------------------------------------------------------

class TestFailedMoveRecovery:

    def test_failed_move_with_equal_size_destination_unlinks_the_source(self, tmp_path, monkeypatch):
        """AC-DATA-3 / AC-QA-7. Pins current behaviour: recovery after a failed
        shutil.move checks SIZE ONLY. A destination that happens to be the
        same size as the source -- e.g. a copy phase that completed writing
        before its final step failed -- is treated as 'the move actually
        succeeded', and the source is deleted.
        Break: os.unlink(old) at :34 -> pass.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _fake_move(src, dst):
            Path(dst).write_bytes(LIBRARY)  # real write: same size, different content
            raise OSError('simulated: failure after the copy phase completed')

        monkeypatch.setattr(shutil, 'move', _fake_move)
        plugin = _mover(monkeypatch, file_action='move')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True
        assert not os.path.exists(old), 'source must be unlinked once sizes match'
        assert dest.read_bytes() == LIBRARY

    @pytest.mark.xfail(strict=True, reason='recovery verifies size, not content')
    def test_failed_move_with_equal_size_but_different_content_should_not_be_accepted(self, tmp_path, monkeypatch):
        """AC-DATA-4 / AC-QA-8. Desired behaviour: recovery should verify the
        destination actually IS the source's content before deleting the only
        other copy, not merely that the sizes match. It does not today, so
        this documents the gap as xfail(strict=True): the day a checksum is
        added, this test XPASSes and the suite reds, forcing acknowledgement.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _fake_move(src, dst):
            Path(dst).write_bytes(LIBRARY)  # same size as DOWNLOAD, different bytes
            raise OSError('simulated: failure after the copy phase completed')

        monkeypatch.setattr(shutil, 'move', _fake_move)
        plugin = _mover(monkeypatch, file_action='move')

        _move(plugin, tmp_path, str(old), str(dest))

        assert os.path.exists(old), 'the only good copy must survive a content mismatch'

    def test_failed_move_with_a_short_destination_restores_the_source_and_removes_the_partial_file(self, tmp_path, monkeypatch):
        """AC-DATA-5 / AC-QA-9. Source survives byte-identical, the partial
        destination is removed, the exception propagates.
        Break, two directions: os.unlink(dest) at :37 -> pass; delete `raise`
        at :38.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _fake_move(src, dst):
            Path(dst).write_bytes(DOWNLOAD[:1024])  # a real, short/partial write
            raise OSError('simulated: interrupted copy (disk full / dropped mount)')

        monkeypatch.setattr(shutil, 'move', _fake_move)
        plugin = _mover(monkeypatch, file_action='move')

        with pytest.raises(OSError):
            _move(plugin, tmp_path, str(old), str(dest))

        assert Path(old).read_bytes() == DOWNLOAD, 'source must survive byte-identical'
        assert not os.path.exists(dest), 'the partial destination must be removed'

    def test_failed_move_when_the_source_vanished_mid_flight_never_touches_the_destination(self, tmp_path, monkeypatch):
        """AC-DATA-6. Regression pin against 'hardening' os.path.getsize(old)
        at mover.py:32. Simulates shutil.move's real fallback: the copy phase
        completes (dest gets full, correct content), but its own final
        unlink(src) then fails because `old` was ALREADY removed by something
        else (a race). Today, the resulting FileNotFoundError from
        `os.path.getsize(old)` propagates BEFORE execution ever reaches
        os.unlink(dest) at :37 -- that FileNotFoundError is the only thing
        standing between this state and the else branch deleting the last
        remaining copy.
        """
        old = tmp_path / 'downloads' / 'movie.mkv'
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_bytes(DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _fake_move(src, dst):
            Path(dst).write_bytes(DOWNLOAD)  # the copy phase really completes
            os.remove(src)  # a concurrent actor removes `old` first
            raise FileNotFoundError(src)  # shutil.move's own final unlink(src) then fails

        monkeypatch.setattr(shutil, 'move', _fake_move)
        plugin = _mover(monkeypatch, file_action='move')

        with pytest.raises(FileNotFoundError):
            _move(plugin, tmp_path, str(old), str(dest))

        assert dest.read_bytes() == DOWNLOAD, 'the only good copy must not be touched'

    def test_failed_move_with_a_directory_at_the_destination_raises_and_leaves_the_source_intact(self, tmp_path, monkeypatch):
        """AC-QA-12. A directory sits at `dest`, already containing a file
        with the same basename as `old` -- shutil.move's own real_dst-exists
        check raises before it ever renames anything. Asserted: it raises, and
        the source is intact. NOT the errno: measured PermissionError on
        macOS, IsADirectoryError on Linux (both from os.unlink(dest) failing
        against a directory) -- an errno assertion is green-on-macOS,
        red-on-Alpine.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest_dir = tmp_path / 'library' / 'movie.mkv'
        dest_dir.mkdir(parents=True)
        (dest_dir / 'movie.mkv').write_bytes(LIBRARY)  # basename collision inside the dir
        plugin = _mover(monkeypatch, file_action='move')

        with pytest.raises(OSError):
            _move(plugin, tmp_path, str(old), str(dest_dir))

        assert Path(old).read_bytes() == DOWNLOAD, 'source must be untouched by the failure'


# ---------------------------------------------------------------------------
# Hardlink-fallback branch (link() fails -> copy + symlink-renamed-over-old)
# ---------------------------------------------------------------------------

class TestLinkFallback:

    def test_link_fallback_to_copy_leaves_old_as_a_symlink_to_dest(self, tmp_path, monkeypatch):
        """AC-DATA-9 / AC-QA-13. When the filesystem refuses a hardlink
        (FAT/exFAT, SMB, cross-device -- not reproducible on tmp_path's real
        filesystem, hence `link` is monkeypatched to raise here, simulating
        that OS-level refusal; the copy, symlink, unlink and rename that
        follow are all real), moveFile falls back to a real copy plus a
        symlink that takes over `old`'s name.
        Break: delete os.rename(old_link, old) at :64 -- no stray `<old>.link`
        must survive.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            mover_module, 'link',
            lambda src, dst: (_ for _ in ()).throw(OSError('simulated: filesystem cannot hardlink')),
        )
        plugin = _mover(monkeypatch, file_action='link')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True
        assert dest.read_bytes() == DOWNLOAD
        assert os.path.islink(old), 'old must become a symlink to dest'
        assert os.path.realpath(old) == os.path.realpath(dest)
        assert not os.path.exists('%s.link' % old), 'a stray <old>.link must not survive'

    def test_link_fallback_removes_its_partial_copy_when_the_copy_fails(self, tmp_path, monkeypatch):
        """AC-DATA-10, INVERTED at review 2026-08-06.

        When BOTH the hardlink attempt and the subsequent copy fail partway,
        `old` survives -- and the partial `dest` is now removed rather than
        left behind.

        This test previously ASSERTED the truncated file must stay, as
        documented known behaviour. That stopped being defensible once the
        same commit cleaned up after `copy` and `symlink_reversed`: the suite
        was pinning both directions of one property, in one file. And this is
        the branch that matters most, because `link` is the shipping default
        (`renamer/api.py`'s `file_action`) and the hardlink fails whenever the
        download directory and the library are on different filesystems --
        an SSD and a NAS, i.e. the ordinary setup. So the fallback copy here
        is the likeliest place in the whole function to meet a full disk.

        Left behind, the truncated file poisoned every retry: the
        top-of-function `lexists` guard fires, `_moveRenamedFiles` sets
        `skipped` forever, and the scanner attaches a file that plays for its
        first few seconds to the movie. The download itself survives, so this
        was expensive rather than irreplaceable -- which is why it was
        accepted once and should not have been twice.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            mover_module, 'link',
            lambda src, dst: (_ for _ in ()).throw(OSError('simulated: cannot hardlink')),
        )

        _real_copy = shutil.copy

        def _fake_copy(src, dst):
            Path(dst).write_bytes(DOWNLOAD[:1024])  # real, truncated write
            raise OSError('simulated: interrupted copy (disk full)')

        monkeypatch.setattr(shutil, 'copy', _fake_copy)
        plugin = _mover(monkeypatch, file_action='link')

        with pytest.raises(OSError):
            _move(plugin, tmp_path, str(old), str(dest))

        assert Path(old).read_bytes() == DOWNLOAD, 'source must survive a failed copy'
        assert not os.path.exists(dest), (
            'the partial copy must not be left at the library filename: it plays '
            'for a few seconds, the scanner attaches it, and the lexists guard '
            'makes every retry fail forever'
        )

        # And the point of removing it: the retry is now possible. Restore a
        # working copy and drive it again.
        monkeypatch.setattr(shutil, 'copy', _real_copy)
        assert _move(plugin, tmp_path, str(old), str(dest)) is True
        assert dest.read_bytes() == DOWNLOAD

    def test_link_with_both_hardlink_and_symlink_failing_degrades_to_a_plain_copy(self, tmp_path, monkeypatch):
        """AC-QA-14. Both link() and symlink() fail; moveFile degrades to a
        plain copy, both paths exist, returns True."""
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            mover_module, 'link',
            lambda src, dst: (_ for _ in ()).throw(OSError('simulated: cannot hardlink')),
        )
        monkeypatch.setattr(
            mover_module, 'symlink',
            lambda src, dst: (_ for _ in ()).throw(OSError('simulated: cannot symlink')),
        )
        plugin = _mover(monkeypatch, file_action='link')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True
        assert os.path.exists(old) and not os.path.islink(old), 'old must remain a real file'
        assert Path(old).read_bytes() == DOWNLOAD
        assert dest.read_bytes() == DOWNLOAD
        assert not os.path.islink(dest)


# ---------------------------------------------------------------------------
# Permission handling
# ---------------------------------------------------------------------------

class TestPermissions:

    def test_os_chmod_failure_is_swallowed_and_the_move_still_succeeds(self, tmp_path, monkeypatch):
        """AC-QA-18. os.chmod raising is swallowed; the move still returns
        True and the destination is intact. Monkeypatching os.chmod (targeted
        to `dest` only, so pytest's own teardown chmod calls elsewhere are
        unaffected) rather than a real permission trick, which is unreliable
        when the suite runs as root in Alpine.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        plugin = _mover(monkeypatch, file_action='move')

        real_chmod = os.chmod
        dest_abspath = os.path.abspath(str(dest))

        def _raising_chmod(path, *a, **kw):
            if os.path.abspath(str(path)) == dest_abspath:
                raise OSError('simulated: chmod not permitted')
            return real_chmod(path, *a, **kw)

        monkeypatch.setattr(os, 'chmod', _raising_chmod)

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True
        assert dest.read_bytes() == DOWNLOAD
        assert not os.path.exists(old)


# ---------------------------------------------------------------------------
# T1.8 data-loss fixes (formerly TestLiveDefects, which pinned these as bugs
# -- the tests are inverted in place: same scenarios, fixed-behaviour
# assertions).
# ---------------------------------------------------------------------------

class TestT18DataLossFixes:

    def test_fix_a_a_directory_at_the_destination_is_refused_and_both_sides_are_untouched(self, tmp_path, monkeypatch):
        """T1.8 fix (a), mover.py:19. FIXED: the top-of-function guard now
        tests os.path.lexists(dest) alone, so an existing DIRECTORY at `dest`
        is refused exactly like an existing file always was -- it no longer
        falls through to shutil.move, which used to place the file INSIDE the
        directory, unrenamed, as dest/<old's basename>, and then strip the
        directory's own execute bit via the trailing os.chmod (previously
        measured and pinned here as a live defect: see git history of this
        test). AC-DATA-8 / AC-QA-11: raises, and neither side is touched.
        Break: revert to `os.path.exists(dest) and os.path.isfile(dest)` --
        this test must fail (result is True instead of raising).
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest_dir = tmp_path / 'library' / 'movie.mkv'
        dest_dir.mkdir(parents=True)  # empty: no basename collision inside
        plugin = _mover(monkeypatch, file_action='move')

        with pytest.raises(Exception, match='already exists'):
            _move(plugin, tmp_path, str(old), str(dest_dir))

        assert Path(old).read_bytes() == DOWNLOAD, 'the source must be untouched'
        assert os.access(dest_dir, os.X_OK), (
            'the directory must not be touched at all -- not even its permissions'
        )
        assert list(dest_dir.iterdir()) == [], 'nothing must land inside the directory'

    def test_fix_b_a_failed_replace_after_hardlink_fallback_leaves_old_intact_with_no_stray_link(self, tmp_path, monkeypatch):
        """T1.8 fix (b), mover.py:60-69. FIXED: `old` is never unlinked ahead
        of time -- `os.replace(old_link, old)` is atomic, so it either lands
        as the symlink or leaves `old` exactly as it was. When it fails (a
        real, reachable failure mode: another process holding `old_link`
        open, a dropped mount between the two calls -- simulated here by
        monkeypatching os.replace itself), the branch also removes the now-
        orphaned `old_link` (AC-QA-15: no stray `<old>.link` survives any
        failure ordering). Break: restore the old unlink-then-rename pair --
        this test must fail (old gone, a stray `.link` left behind).
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        old_link_path = '%s.link' % old
        monkeypatch.setattr(
            mover_module, 'link',
            lambda src, dst: (_ for _ in ()).throw(OSError('simulated: cannot hardlink')),
        )
        # Fail whichever call the code under test happens to make for
        # old_link -> old: os.replace (fixed code) or os.rename (the
        # unlink-then-rename pair this test's Break note reverts to). Patching
        # only one would make this test blind to a revert of the OTHER call,
        # since the unpatched syscall would then simply succeed.
        real_replace, real_rename = os.replace, os.rename

        def _raising_replace(src, dst):
            if str(src) == old_link_path:
                raise OSError('simulated: replace of the fallback link failed')
            return real_replace(src, dst)

        def _raising_rename(src, dst):
            if str(src) == old_link_path:
                raise OSError('simulated: rename of the fallback link failed')
            return real_rename(src, dst)

        monkeypatch.setattr(os, 'replace', _raising_replace)
        monkeypatch.setattr(os, 'rename', _raising_rename)
        plugin = _mover(monkeypatch, file_action='link')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True, 'this branch still degrades to a plain copy and reports success'
        assert os.path.exists(old) and not os.path.islink(old), (
            'old must remain the real file -- never unlinked ahead of the replace'
        )
        assert Path(old).read_bytes() == DOWNLOAD
        assert not os.path.lexists(old_link_path), 'no stray <old>.link may survive any failure ordering'
        assert dest.read_bytes() == DOWNLOAD

    def test_fix_c_symlink_reversed_raises_when_the_move_fails_instead_of_reporting_success(self, tmp_path, monkeypatch):
        """T1.8 fix (c), mover.py:42-52. FIXED: the initial shutil.move in the
        symlink_reversed branch is no longer wrapped in a swallowing
        try/except -- a failed move now propagates out of moveFile entirely
        (only the best-effort symlink-back stays swallowed). `_moveRenamedFiles`
        therefore sees a real exception instead of a false True, sets
        `skipped`, and cleanup is suppressed -- this is the guard against
        deleting a completed download on a full disk or a dropped NAS mount.
        Break: re-wrap the shutil.move call in try/except -- this test must
        fail (result is True instead of raising).
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _failing_move(src, dst):
            raise OSError('simulated: disk full / dropped mount, nothing written')

        monkeypatch.setattr(shutil, 'move', _failing_move)
        plugin = _mover(monkeypatch, file_action='symlink_reversed')

        with pytest.raises(OSError):
            _move(plugin, tmp_path, str(old), str(dest))

        assert Path(old).read_bytes() == DOWNLOAD, 'old is untouched -- the move never happened'
        assert not os.path.exists(dest), 'nothing reached the destination either'

    def test_fix_c_a_partially_written_destination_is_removed_when_the_move_fails(self, tmp_path, monkeypatch):
        """The fixture above is not hostile enough, and that hid a real gap.

        Its `_failing_move` writes NOTHING before raising, so it can only ever
        prove the exception propagates. `shutil.move`'s real fallback is
        `copy2`, which on a full disk or a dropped mount writes part of the
        file and THEN raises. Driven that way, T1.8 fix (c) left a truncated
        .mkv sitting at the library filename: `_moveRenamedFiles` skipped that
        file on every subsequent run (the fix (a) `lexists` guard refuses a
        destination that already exists, so the retry could never succeed),
        and the scanner attached the truncated file to the movie.

        The default-move branch has cleaned this up since before T1.8
        (mover.py:36-37); the symlink_reversed and copy branches did not.

        Removing the partial cannot lose data: the source is intact in every
        one of these cases, so the only copy being deleted is the one that is
        already wrong.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _partial_move(src, dst):
            Path(dst).write_bytes(DOWNLOAD[:400])  # a real, short write
            raise OSError('simulated: disk full part-way through the copy')

        monkeypatch.setattr(shutil, 'move', _partial_move)
        plugin = _mover(monkeypatch, file_action='symlink_reversed')

        with pytest.raises(OSError):
            _move(plugin, tmp_path, str(old), str(dest))

        assert Path(old).read_bytes() == DOWNLOAD, 'source must survive byte-identical'
        assert not os.path.exists(dest), (
            'a truncated destination must not be left in the library: it blocks '
            'every retry through the lexists guard and the scanner will attach it'
        )

    def test_fix_c_a_complete_destination_is_kept_when_the_move_fails_afterwards(self, tmp_path, monkeypatch):
        """The other direction: never delete a copy that is actually complete.

        `shutil.move` can finish copying and then fail on its own final
        `unlink(src)`. Deleting `dest` there would throw away a good copy of
        the user's completed download to tidy up after a failure that already
        succeeded at the part that matters. So the cleanup is conditional on
        the destination being demonstrably short, not on the call having
        raised.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _complete_then_fail(src, dst):
            Path(dst).write_bytes(DOWNLOAD)  # the copy phase really completes
            raise OSError('simulated: failure after the bytes were all written')

        monkeypatch.setattr(shutil, 'move', _complete_then_fail)
        plugin = _mover(monkeypatch, file_action='symlink_reversed')

        with pytest.raises(OSError):
            _move(plugin, tmp_path, str(old), str(dest))

        assert Path(old).read_bytes() == DOWNLOAD, 'source must survive'
        assert dest.read_bytes() == DOWNLOAD, 'a complete copy must never be discarded'

    def test_a_partially_written_copy_is_removed_too(self, tmp_path, monkeypatch):
        """The `copy` file_action has the same shape and the same gap.

        Fixing only symlink_reversed would leave the identical truncated-file
        outcome one branch away -- the "fix the instance, miss the class"
        pattern this branch has already hit twice.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _partial_copy(src, dst):
            Path(dst).write_bytes(DOWNLOAD[:400])
            raise OSError('simulated: disk full part-way through the copy')

        monkeypatch.setattr(shutil, 'copy', _partial_copy)
        plugin = _mover(monkeypatch, file_action='copy')

        with pytest.raises(OSError):
            _move(plugin, tmp_path, str(old), str(dest))

        assert Path(old).read_bytes() == DOWNLOAD, 'source must survive byte-identical'
        assert not os.path.exists(dest), 'the partial copy must not be left in the library'


# ---------------------------------------------------------------------------
# T1.8 caller-level proof (AC-DATA-12 / AC-QA-17). The assertions above are a
# curiosity on their own -- moveFile is not the code that deletes anything.
# These drive the real Renamer._moveRenamedFiles (renamer/main.py), with a
# REAL moveFile underneath (only `conf`, `Env.getPermission` and
# `deleteFolder` are stubbed -- deleteFolder purely to record whether cleanup
# ran, following test_renamer_cleanup_safety.py's _Recorder pattern, without
# actually touching the tmp_path fixture we still want to assert against
# afterwards), against a real filesystem, and assert whether the source
# folder gets cleaned up.
# ---------------------------------------------------------------------------

class TestCallerLevelDataLossGuards:

    def _run(self, monkeypatch, conf, rename_files, source_folder):
        plugin = _mover(monkeypatch, **conf)
        deleted = []
        monkeypatch.setattr(
            type(plugin), 'deleteFolder',
            lambda _self, folder, **kw: deleted.append(folder),
            raising=False,
        )
        plugin._moveRenamedFiles(rename_files, {'parentdir': source_folder})
        return deleted

    def test_caller_refuses_any_pre_existing_destination_before_calling_movefile(self, tmp_path, monkeypatch):
        """Pins `Renamer._moveRenamedFiles`'s OWN guard, not mover.py's.

        Renamed from `test_fix_a_...` during T1.8 review. Under that name the
        test claimed to prove fix (a) load-bearing at the caller level, and it
        cannot: `renamer/main.py:154-157` refuses ANY pre-existing `dst` (file
        or directory) before `moveFile` is ever reached, so reverting fix (a)
        leaves this green. That is the "incidentally passing" shape in
        CLAUDE.md section 11: it passed for a reason unrelated to what its name
        claimed. The unit-level `test_fix_a_...` is what proves fix (a).

        Kept, because what it actually guards is worth guarding: the caller's
        skip-and-warn on a pre-existing destination, which sets `skipped = True`
        and so keeps `cleanup` away from the source folder. PR 4 (FEAT-009
        Part B, T4.3) rewrites exactly that line to replace the destination
        instead of skipping, and this test is the regression pin for the
        behaviour it is replacing.
        """
        old = _write(tmp_path / 'downloads/Movie-GRP/movie.mkv', DOWNLOAD)
        dest_dir = tmp_path / 'library' / 'movie.mkv'
        dest_dir.mkdir(parents=True)
        source_folder = str(old.parent)

        deleted = self._run(
            monkeypatch, {'default_file_action': 'move', 'cleanup': True},
            {str(old): str(dest_dir)}, source_folder,
        )

        assert deleted == [], 'source folder must not be cleaned up when nothing moved'
        assert old.exists() and old.read_bytes() == DOWNLOAD, 'the download must survive'

    def test_fix_b_a_failed_hardlink_fallback_replace_leaves_no_stray_link_via_the_real_caller(self, tmp_path, monkeypatch):
        """AC-DATA-12 / AC-QA-15 / AC-QA-17 at the caller level. Unlike (a) and
        (c), a failed replace in this branch does not put the library copy at
        risk -- shutil.copy(old, dest) already completed before the replace is
        even attempted, so `dest` is correct either way and cleanup running is
        safe. What T1.8 fix (b) guarantees at this boundary is the one thing
        that was NOT safe before: `old` is never left absent, and no stray
        `<old>.link` survives, even driven through the real caller rather than
        moveFile directly.
        """
        old = _write(tmp_path / 'downloads/Movie-GRP/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/Movie (2020)/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        source_folder = str(old.parent)
        old_link_path = '%s.link' % old

        monkeypatch.setattr(
            mover_module, 'link',
            lambda src, dst: (_ for _ in ()).throw(OSError('simulated: cannot hardlink')),
        )
        # See the unit-level test_fix_b for why both are patched.
        real_replace, real_rename = os.replace, os.rename

        def _raising_replace(src, dst):
            if str(src) == old_link_path:
                raise OSError('simulated: replace of the fallback link failed')
            return real_replace(src, dst)

        def _raising_rename(src, dst):
            if str(src) == old_link_path:
                raise OSError('simulated: rename of the fallback link failed')
            return real_rename(src, dst)

        monkeypatch.setattr(os, 'replace', _raising_replace)
        monkeypatch.setattr(os, 'rename', _raising_rename)

        deleted = self._run(
            monkeypatch, {'default_file_action': 'link', 'cleanup': True},
            {str(old): str(dest)}, source_folder,
        )

        assert deleted == [source_folder], 'cleanup should still run -- dest already holds the full content'
        assert dest.read_bytes() == DOWNLOAD
        assert not os.path.lexists(old_link_path), 'no stray <old>.link must survive, even via the real caller'

        # Reverting fix (b) to the old unlink-then-rename pair leaves the
        # stray-link assertion above GREEN, because the except branch removes
        # the orphan under both versions. The half that actually pins fix (b)
        # is that `old` is never left absent: assert it survives, as a real
        # file, byte-intact.
        assert os.path.exists(old), (
            'os.replace must never leave `old` absent: the unlink-then-rename '
            'pair it replaced could, if the rename failed in between'
        )
        assert not os.path.islink(old), '`old` must still be the real file'

    def test_fix_c_a_failed_symlink_reversed_move_is_not_cleaned_up(self, tmp_path, monkeypatch):
        """AC-DATA-12 / AC-QA-17 -- the actual data-loss guard this task
        exists for. Before T1.8, a failed shutil.move inside the
        symlink_reversed branch was swallowed and moveFile still returned
        True; `_moveRenamedFiles` took that as a completed move and, with
        cleanup on, deleted the source folder -- destroying the only copy of
        a completed download on a full disk or a dropped NAS mount. After the
        fix, the failure propagates out of moveFile, `_moveRenamedFiles`
        catches it and sets `skipped`, and cleanup is suppressed.
        """
        old = _write(tmp_path / 'downloads/Movie-GRP/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/Movie (2020)/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        source_folder = str(old.parent)

        def _failing_move(src, dst):
            raise OSError('simulated: disk full / dropped mount, nothing written')

        monkeypatch.setattr(shutil, 'move', _failing_move)

        deleted = self._run(
            monkeypatch, {'default_file_action': 'symlink_reversed', 'cleanup': True},
            {str(old): str(dest)}, source_folder,
        )

        assert deleted == [], 'the source folder must not be cleaned up when the move never happened'
        assert old.exists() and old.read_bytes() == DOWNLOAD, 'the download must survive'
        assert not os.path.exists(dest), 'nothing reached the destination either'


# ---------------------------------------------------------------------------
# Platform gaps, deliberately left uncovered
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.name != 'nt',
    reason=(
        "Windows-only branch (mover.py:70-71): os.popen('icacls \"' + dest + "
        '\'" * /reset /T\') builds a shell command by string concatenation '
        'from `dest`, which can carry indexer-supplied release names -- a '
        'real command-injection surface on Windows with ntfs_permission '
        'enabled. Deferred to PR 3 (specs/REMEDIATION-2026-08.md T1.1, which '
        'already edits renamer/); left explicitly uncovered here rather than '
        'silently absent.'
    ),
)
def test_ntfs_permission_reset_on_windows_is_not_covered_here():
    """AC-DATA-15 / AC-QA-19. Placeholder: real coverage of the icacls branch
    is deferred to PR 3 alongside the injection fix; this only exists so the
    gap is a named, explicit skip rather than silent absence."""
    pytest.skip('Windows-only branch; see the module-level skip reason above')
