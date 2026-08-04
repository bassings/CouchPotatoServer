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

    def test_link_fallback_when_the_copy_itself_fails_poisons_the_destination_for_a_retry(self, tmp_path, monkeypatch):
        """AC-DATA-10. When BOTH the hardlink attempt and the subsequent copy
        fail partway, `old` survives (the unlink at :63 only runs after a
        successful copy+symlink), but a truncated file is left at `dest`.
        That truncated file then poisons any retry: the retry's own
        top-of-function guard ('Destination "%s" already exists') fires,
        because dest now exists as a file. Documented as known behaviour, not
        fixed here.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            mover_module, 'link',
            lambda src, dst: (_ for _ in ()).throw(OSError('simulated: cannot hardlink')),
        )

        def _fake_copy(src, dst):
            Path(dst).write_bytes(DOWNLOAD[:1024])  # real, truncated write
            raise OSError('simulated: interrupted copy (disk full)')

        monkeypatch.setattr(shutil, 'copy', _fake_copy)
        plugin = _mover(monkeypatch, file_action='link')

        with pytest.raises(OSError):
            _move(plugin, tmp_path, str(old), str(dest))

        assert Path(old).read_bytes() == DOWNLOAD, 'source must survive a failed copy'
        assert dest.exists() and dest.read_bytes() == DOWNLOAD[:1024], (
            'a truncated file is left sitting at dest'
        )

        with pytest.raises(Exception, match='already exists'):
            _move(plugin, tmp_path, str(old), str(dest))

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
# Live defects (T1.8 fixes these; these tests pin TODAY's behaviour so T1.8
# can invert them).
# ---------------------------------------------------------------------------

class TestLiveDefects:

    def test_pins_current_bug_a_move_into_an_empty_directory_at_the_destination_silently_succeeds(self, tmp_path, monkeypatch):
        """PINS A LIVE DEFECT (T1.8 fix (a), mover.py:19). The top-of-function
        guard only refuses an existing destination when os.path.isfile(dest)
        is true, so an existing DIRECTORY at `dest` sails straight through.
        shutil.move then genuinely succeeds by placing the file INSIDE that
        directory, unrenamed, as dest/<old's basename>. moveFile returns True,
        so `_moveRenamedFiles` treats this as a completed move -- and cleanup
        goes on to delete the source folder, having moved nothing to the name
        the caller actually asked for. The trailing os.chmod(dest, ...) then
        strips the directory's own execute bit (PERM_MODE here has no `x`),
        making it non-traversable -- measured directly below. T1.8 fixes the
        guard to os.path.exists(dest) alone, which will make this test's own
        assertions false -- that is the point: T1.8 inverts it.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest_dir = tmp_path / 'library' / 'movie.mkv'
        dest_dir.mkdir(parents=True)  # empty: no basename collision inside
        plugin = _mover(monkeypatch, file_action='move')

        result = _move(plugin, tmp_path, str(old), str(dest_dir))

        assert result is True, 'today: a directory at dest is treated as a successful move'
        assert not os.path.exists(old), 'the file was "moved" -- into the directory'
        assert not os.access(dest_dir, os.X_OK), (
            'the trailing os.chmod(dest, PERM_MODE) strips the directory\'s own '
            'execute bit -- it is no longer traversable, which is itself part '
            'of the defect'
        )
        # Restore traversal ourselves purely so this test (and pytest's own
        # tmp_path teardown) can look inside -- the loss of +x above IS the
        # defect being pinned, not something that needs to stay broken for the
        # rest of this test or for cleanup afterwards.
        os.chmod(dest_dir, 0o755)
        landed = dest_dir / 'movie.mkv'
        assert landed.exists() and landed.read_bytes() == DOWNLOAD, (
            'the file lands inside the directory, unrenamed, instead of the '
            'caller ever getting a file at the `dest` path it actually asked for'
        )

    def test_pins_current_bug_b_a_failed_rename_after_hardlink_fallback_leaves_old_absent_and_a_stray_link_file(self, tmp_path, monkeypatch):
        """PINS A LIVE DEFECT (T1.8 fix (b), mover.py:60-64). On the hardlink
        fallback path, `old` is unlinked (:63) BEFORE the rename that restores
        it as a symlink (:64). If that rename then fails -- a real, reachable
        failure mode (another process holding `old_link` open, a dropped
        mount between the two calls) -- `old` is simply gone: no real file, no
        symlink, nothing at that name at all, while a stray `<old>.link`
        survives instead. The whole thing is swallowed by the branch's own
        try/except, so moveFile still reports True. T1.8 replaces the
        unlink+rename pair with one atomic os.replace, which cannot produce
        this state -- that is what this test's assertions will invert.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)
        old_link_path = '%s.link' % old
        monkeypatch.setattr(
            mover_module, 'link',
            lambda src, dst: (_ for _ in ()).throw(OSError('simulated: cannot hardlink')),
        )
        real_rename = os.rename

        def _raising_rename(src, dst):
            if str(src) == old_link_path:
                raise OSError('simulated: rename of the fallback link failed')
            return real_rename(src, dst)

        monkeypatch.setattr(os, 'rename', _raising_rename)
        plugin = _mover(monkeypatch, file_action='link')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True, 'the branch swallows this failure and still reports success'
        assert not os.path.exists(old), 'today: old is gone -- unlinked before the failed rename'
        assert os.path.exists(old_link_path), 'today: a stray <old>.link survives'
        assert dest.read_bytes() == DOWNLOAD

    def test_pins_current_bug_c_symlink_reversed_swallows_a_failed_move_and_reports_success(self, tmp_path, monkeypatch):
        """PINS A LIVE DEFECT (T1.8 fix (c), mover.py:42-51). Both the initial
        move and the symlink-back attempt in the symlink_reversed branch are
        wrapped in their own try/except that only logs and continues. When the
        move fails, `old` is never moved -- so the follow-up
        `symlink(dest, old)` ALSO fails, because `old` still exists as a real
        file at that exact path (you cannot create a symlink where a regular
        file already sits) -- and that failure is swallowed too. moveFile
        still returns True, with nothing at `dest` and `old` sitting exactly
        where it started. `_moveRenamedFiles` takes that True to mean the file
        reached the library and, with cleanup on, deletes the source folder:
        on a full disk or a dropped NAS mount, this is how a completed
        download disappears with nothing to show for it. T1.8 fixes this by
        re-raising (or returning falsy) when the move itself fails, which will
        make this test's own assertions false -- that is the point.
        """
        old = _write(tmp_path / 'downloads/movie.mkv', DOWNLOAD)
        dest = tmp_path / 'library/movie.mkv'
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _failing_move(src, dst):
            raise OSError('simulated: disk full / dropped mount, nothing written')

        monkeypatch.setattr(shutil, 'move', _failing_move)
        plugin = _mover(monkeypatch, file_action='symlink_reversed')

        result = _move(plugin, tmp_path, str(old), str(dest))

        assert result is True, 'today: a failed move in this branch is swallowed and reported as success'
        assert Path(old).read_bytes() == DOWNLOAD, 'old is untouched -- the move never happened'
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
