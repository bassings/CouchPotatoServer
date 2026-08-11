"""T17 fix 2 (python:S2612): `SourceUpdater.removeDir` used to respond to a
failed `shutil.rmtree` by making the offending path world-writable
(`os.chmod(inst.filename, 0o777)`) and recursing with no depth bound and no
guarantee the chmod fixed anything -- so a permission error it cannot clear
recurses until the stack blows up.

Fixed shape: grant owner rwx (never widen group/other), and let a failure
`removeDir` cannot fix propagate. A `filename`-less OSError (which can
happen) must propagate without touching `os.chmod` at all. And (T17
follow-up B): if the failing entry is a SYMLINK, `os.stat`/`os.chmod` both
follow it by default -- so chmod-ing `inst.filename` would silently reach
the link's TARGET, potentially outside the tree being deleted. `removeDir`
is called on freshly-extracted archive content (`SourceUpdater.doUpdate`),
which is attacker-influenced input, so this is a first-class
symlink-following risk per CLAUDE.md even though the practical blast
radius is small (chmod requires ownership, so the worst case is adding
owner-write to a file the CouchPotato user already owns). The fix refuses
to chmod a symlink at all: a symlink's own permission bits never block
`shutil.rmtree` from removing it (only the *containing directory*'s
permissions matter for unlink), so there is nothing legitimate a chmod on
it would accomplish.

2026-08-11 review, finding 3: an earlier version of this fix bounded the
retry to a single attempt (see git history), which regressed cleanup of any
tree with MORE than one blocked directory -- the old unbounded recursion
repaired one entry per level and eventually succeeded; a single retry
repairs only the first entry it meets and propagates uncaught on the
second. Measured on HEAD before this fix, real filesystem, no mocks:

    1 blocked dirs  single-retry -> deleted OK
    2 blocked dirs  single-retry -> FAILED: PermissionError
    3 blocked dirs  single-retry -> FAILED: PermissionError

That matters because `removeDir` runs (`SourceUpdater.doUpdate`) AFTER
`replaceWith()` has already overwritten the application directory and
BEFORE `version_file` is written -- so a cleanup failure here makes the
updater report failure and re-apply an already-installed update. Fixed by
bounding the retry to ENTRIES REPAIRED rather than an attempt count or
recursion depth: each distinct failing `inst.filename` is chmod-ed at most
once. See `removeDir`'s own docstring for the termination argument.

Reachability (noted in specs/REMEDIATION-2026-08.md T17): this is called from
SourceUpdater's extract paths, which only run for a source install doing a
self-update -- not the Docker image this project ships. Still reachable, so
still worth fixing correctly rather than papering over.
"""
import os
import stat

import pytest
from unittest.mock import patch

from couchpotato.core._base.updater.main import SourceUpdater


def _bare_updater():
    """SourceUpdater.__init__ touches Env.get('cache_dir') and the real
    filesystem, none of which removeDir() needs -- it only calls
    os/shutil functions and (in the buggy version) itself. Skipping __init__
    via object.__new__ keeps this test isolated from that setup."""
    return object.__new__(SourceUpdater)


class TestRemoveDirPermissionRetry:

    def test_an_entry_that_cannot_be_repaired_propagates_rather_than_looping(self, tmp_path):
        """The SAME entry keeps failing (chmod cannot fix whatever this is
        -- a different user's file, a filesystem that ignores mode bits...).
        removeDir must repair it once, retry once, see the identical
        filename fail again, and stop -- not loop.

        The fake is DELIBERATELY BOUNDED (five failures, then a sixth call
        that would succeed) rather than an unconditional always-raise: an
        always-raise fake would hang for real if `removeDir`'s
        once-per-entry guard (`if inst.filename in repaired: raise`) were
        ever removed, which is exactly the mutation this test exists to
        catch -- "do not write a test that could hang" cuts against making
        the fake itself unbounded. With the guard, removeDir must stop
        after the SECOND failure on the identical filename (2 rmtree calls,
        1 chmod call) rather than retrying it three more times to reach
        the fake's eventual "success"."""
        updater = _bare_updater()
        target = str(tmp_path / 'locked')

        call_count = {'n': 0}

        def fake_rmtree(path):
            call_count['n'] += 1
            if call_count['n'] <= 5:
                raise PermissionError(13, 'Permission denied', target)
            return None  # never reached if the guard behaves correctly

        with patch('couchpotato.core._base.updater.main.shutil.rmtree', side_effect = fake_rmtree), \
             patch('couchpotato.core._base.updater.main.os.path.isdir', return_value = True), \
             patch('couchpotato.core._base.updater.main.os.stat') as mock_stat, \
             patch('couchpotato.core._base.updater.main.os.chmod') as mock_chmod:
            mock_stat.return_value.st_mode = 0o100444

            with pytest.raises(PermissionError):
                updater.removeDir(target)

        assert call_count['n'] == 2, (
            'must repair the failing entry once, retry once, then propagate on the '
            'SAME filename failing again -- not keep retrying it'
        )
        mock_chmod.assert_called_once()

    def test_none_filename_propagates_without_chmod(self, tmp_path):
        updater = _bare_updater()
        target = str(tmp_path / 'locked')

        def fake_rmtree(path):
            # No filename positional arg -> .filename is None, as can
            # genuinely happen on some OSErrors.
            raise PermissionError(13, 'Permission denied')

        with patch('couchpotato.core._base.updater.main.shutil.rmtree', side_effect = fake_rmtree), \
             patch('couchpotato.core._base.updater.main.os.path.isdir', return_value = True), \
             patch('couchpotato.core._base.updater.main.os.chmod') as mock_chmod:

            with pytest.raises(PermissionError):
                updater.removeDir(target)

        mock_chmod.assert_not_called()

    def test_symlink_target_permissions_are_never_touched(self, tmp_path):
        """A real symlink on disk, pointing at a real file OUTSIDE the tree
        being deleted. No mocking of os.stat/os.chmod -- if removeDir follows
        the link (the bug), this genuinely widens the target's mode on disk;
        if it refuses (the fix), the target's mode is provably untouched.

        Platform note: os.chmod on a symlink follows the link on every
        platform this project ships on (Linux/Alpine in Docker, macOS in
        dev) -- `os.chmod(path, ..., follow_symlinks=False)` raises
        NotImplementedError on Linux, which is why the fix refuses to chmod
        a symlink at all rather than trying to chmod the link itself.
        """
        updater = _bare_updater()

        outside_dir = tmp_path / 'outside'
        outside_dir.mkdir()
        target = outside_dir / 'target.txt'
        target.write_text('do not touch')
        os.chmod(str(target), 0o444)  # read-only, so a widened mode is observable
        mode_before = stat.S_IMODE(os.stat(str(target)).st_mode)

        tree = tmp_path / 'tree'
        tree.mkdir()
        link = tree / 'evil-link'
        link.symlink_to(target)

        def fake_rmtree(path):
            raise PermissionError(13, 'Permission denied', str(link))

        with patch('couchpotato.core._base.updater.main.shutil.rmtree', side_effect = fake_rmtree), \
             patch('couchpotato.core._base.updater.main.os.path.isdir', return_value = True):
            with pytest.raises(PermissionError):
                updater.removeDir(str(tree))

        mode_after = stat.S_IMODE(os.stat(str(target)).st_mode)
        assert mode_after == mode_before, 'chmod must never reach the symlink target'

    def test_successful_rmtree_never_touches_chmod(self, tmp_path):
        """The happy path (no OSError at all) must not retry or chmod anything."""
        updater = _bare_updater()
        target = str(tmp_path / 'clean')

        with patch('couchpotato.core._base.updater.main.shutil.rmtree') as mock_rmtree, \
             patch('couchpotato.core._base.updater.main.os.path.isdir', return_value = True), \
             patch('couchpotato.core._base.updater.main.os.chmod') as mock_chmod:
            updater.removeDir(target)

        mock_rmtree.assert_called_once_with(target)
        mock_chmod.assert_not_called()


class TestRemoveDirGrantsTraversalNotJustWrite:
    """2026-08-11 review finding, and a correction to this file's own prior
    instruction: narrowing the chmod to owner-WRITE-only
    (`current_mode | stat.S_IWUSR`) regressed `removeDir`'s actual purpose.
    `shutil.rmtree` needs owner read+write+EXECUTE on a directory to list
    and unlink its contents -- write alone is not enough to descend into or
    clear it. Measured on a real filesystem, no mocks (uid 501, macOS
    APFS):

        mode 0o500  S_IWUSR -> deleted OK        S_IRWXU -> deleted OK
        mode 0o400  S_IWUSR -> FAILED             S_IRWXU -> deleted OK
        mode 0o000  S_IWUSR -> FAILED             S_IRWXU -> deleted OK

    `stat.S_IRWXU` (owner rwx) still never touches group/other -- that was
    the actual point of the S2612 finding (0o777 made the path WORLD-
    writable), not "grant the single narrowest bit possible". Do not
    re-narrow this to `S_IWUSR`: it looks more conservative and is actually
    broken for the directories this function exists to remove.

    The PREVIOUS version of this test (removed here) mocked
    `shutil.rmtree`, `os.stat` AND `os.chmod`, so its four assertions held
    equally for the broken `S_IWUSR` and the correct `S_IRWXU` -- it could
    not have failed on this regression, because it measured the argument
    handed to a fake rather than whether anything became removable.
    Rewritten against a real filesystem: build a genuinely locked
    directory, call the real `removeDir` with nothing mocked, and assert
    the tree is actually gone.

    Root bypasses permission checks entirely (plausible for the Alpine
    container image this project ships, which may run as root) -- a
    permission-based test would pass unconditionally and silently prove
    nothing there, so it is skipped in that case rather than reported as a
    false green.
    """

    @pytest.fixture(autouse = True)
    def _skip_as_root(self):
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            pytest.skip('running as root: file/directory modes are not enforced')

    @pytest.mark.parametrize('locked_mode', [0o500, 0o400, 0o000], ids = ['0o500', '0o400', '0o000'])
    def test_directory_is_actually_removed_regardless_of_starting_mode(self, tmp_path, locked_mode):
        updater = _bare_updater()

        tree = tmp_path / 'locked'
        tree.mkdir()
        (tree / 'file.txt').write_text('content')
        os.chmod(str(tree), locked_mode)

        try:
            updater.removeDir(str(tree))
        finally:
            # Best-effort: if the assertion below is about to fail, leave
            # tmp_path in a state its own teardown can still clean up.
            if tree.exists():
                os.chmod(str(tree), 0o700)

        assert not tree.exists(), (
            'removeDir must actually delete a directory whose permissions it can fix -- '
            'S_IWUSR alone cannot, because rmtree needs owner EXECUTE to traverse a directory too'
        )

    def test_never_grants_group_or_other_write(self, tmp_path, monkeypatch):
        """Group/other write must never be granted -- 0o777 was the actual
        S2612 defect. Captures every mode actually passed to os.chmod on a
        real (failing-then-fixed) directory, without mocking shutil.rmtree
        itself."""
        updater = _bare_updater()

        tree = tmp_path / 'locked'
        tree.mkdir()
        (tree / 'file.txt').write_text('content')
        os.chmod(str(tree), 0o400)

        captured_modes = []
        real_chmod = os.chmod

        def spy_chmod(path, mode, *args, **kwargs):
            captured_modes.append(mode)
            return real_chmod(path, mode, *args, **kwargs)

        monkeypatch.setattr('couchpotato.core._base.updater.main.os.chmod', spy_chmod)

        try:
            updater.removeDir(str(tree))
        finally:
            # Best-effort: a mutated implementation under test can leave the
            # directory locked (0o400), which pytest's own tmp_path cleanup
            # cannot remove either -- widen it back so teardown succeeds
            # regardless of what this test's assertions find.
            if tree.exists():
                os.chmod(str(tree), 0o700)

        assert captured_modes, 'chmod should have been called to fix the permission error'
        for mode in captured_modes:
            assert not (mode & stat.S_IWGRP), 'must not widen group write'
            assert not (mode & stat.S_IWOTH), 'must not widen other write'
            assert mode != 0o777
        assert not tree.exists(), 'the directory must actually end up removed'


class TestRemoveDirHandlesMultipleBlockedEntries:
    """2026-08-11 review finding 3: a single blanket retry only repairs the
    FIRST blocked directory it meets in a tree, then propagates uncaught on
    the second -- measured on HEAD (single-retry) before this fix, real
    filesystem, no mocks:

        1 blocked dirs  single-retry -> deleted OK
        2 blocked dirs  single-retry -> FAILED: PermissionError
        3 blocked dirs  single-retry -> FAILED: PermissionError

    That matters because removeDir runs (SourceUpdater.doUpdate) AFTER
    replaceWith() has already overwritten the application directory and
    BEFORE version_file is written -- a cleanup failure here makes the
    updater report failure and re-apply an already-installed update.

    Fixed by bounding the retry to entries repaired rather than an attempt
    count. Tested here on a real filesystem (no mocks) across both layouts
    a tree can actually have: multiple blocked SIBLINGS and multiple
    blocked NESTED directories, at 1/2/3/5 blocked entries each.

    Root bypasses permission checks entirely -- skipped there, same as the
    class above, rather than reporting a false green.
    """

    @pytest.fixture(autouse = True)
    def _skip_as_root(self):
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            pytest.skip('running as root: file/directory modes are not enforced')

    def _make_sibling_tree(self, tmp_path, n_blocked):
        tree = tmp_path / 'tree'
        tree.mkdir()
        blocked = []
        for i in range(n_blocked):
            sub = tree / ('sub%d' % i)
            sub.mkdir()
            (sub / 'f.txt').write_text('content')
            blocked.append(sub)
        for b in blocked:
            os.chmod(str(b), 0o400)
        return tree, blocked

    def _make_nested_tree(self, tmp_path, n_blocked):
        tree = tmp_path / 'tree'
        tree.mkdir()
        current = tree
        blocked = []
        for i in range(n_blocked):
            current = current / ('lvl%d' % i)
            current.mkdir()
            (current / 'f.txt').write_text('content')
            blocked.append(current)
        # Lock innermost-first: locking an ancestor before its descendant
        # is created underneath it would block the setup itself.
        for b in reversed(blocked):
            os.chmod(str(b), 0o400)
        return tree, blocked

    def _cleanup(self, tree, blocked):
        # Best-effort, OUTERMOST-first (opposite of the locking order):
        # checking whether a NESTED entry still exists requires traversing
        # its ancestors, and Path.exists() silently returns False (not
        # raise) when a locked ancestor blocks that traversal -- so
        # repairing innermost-first would skip the very entries still
        # blocked by their still-locked parent. Fix the parent's
        # permissions before asking whether the child is even reachable.
        if tree.exists():
            os.chmod(str(tree), 0o700)
        for b in blocked:
            if b.exists():
                os.chmod(str(b), 0o700)

    @pytest.mark.parametrize('n_blocked', [1, 2, 3, 5])
    def test_multiple_blocked_sibling_directories_are_removed(self, tmp_path, n_blocked):
        updater = _bare_updater()
        tree, blocked = self._make_sibling_tree(tmp_path, n_blocked)

        try:
            updater.removeDir(str(tree))
        finally:
            self._cleanup(tree, blocked)

        assert not tree.exists(), (
            'removeDir must remove a tree with %d blocked SIBLING directories, '
            'not just the first one it meets' % n_blocked
        )

    @pytest.mark.parametrize('n_blocked', [1, 2, 3, 5])
    def test_multiple_blocked_nested_directories_are_removed(self, tmp_path, n_blocked):
        updater = _bare_updater()
        tree, blocked = self._make_nested_tree(tmp_path, n_blocked)

        try:
            updater.removeDir(str(tree))
        finally:
            self._cleanup(tree, blocked)

        assert not tree.exists(), (
            'removeDir must remove a tree with %d blocked NESTED directories, '
            'not just the first one it meets' % n_blocked
        )
