"""Tests for scripts/e2e_worker_data.py -- the ONE guarded helper that
validates and deletes a per-E2E-worker data dir (T1.7, AC-DATA-24/25/26).

Why this exists: `CouchPotato.py:53` gates `--data_dir` on truthiness, so an
empty string falls through to `Env.setting('data_dir')` and then
`getDataDir()` -- the developer's REAL library. Measured neighbours:
`.config` is a 68 MiB live database and `test_data/` is 71 MiB of
gitignored, git-unrecoverable data, both siblings of the repo root. A
per-worker E2E harness computes a fresh data dir string for every worker and
deletes it on teardown; if that computation is ever wrong -- empty, a typo,
a symlink -- the guard here is what stands between that bug and a real rm
-rf of irreplaceable data.

Every hostile input in AC-DATA-25's list is exercised, matching the shape
`scripts/backup.sh:244-301` documents on this exact repo: an allowlist
regex on the basename, a check that the path resolves to a DIRECT child of
the designated root (not just somewhere underneath it), and symlinks
followed via `os.path.realpath` so a symlink whose OWN name looks safe but
points somewhere else is refused by the same check, not a special case.
"""
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT_DIR = os.path.join(_REPO_ROOT, 'scripts')
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from e2e_worker_data import (  # noqa: E402
    UnsafeDataDirError,
    resolve_worker_data_dir,
    safe_rmtree,
    validate_worker_data_dir,
)


class TestValidateWorkerDataDirHostileInputs:
    """AC-DATA-25's exact hostile-input list. Every one must be refused."""

    @pytest.mark.parametrize('hostile', [
        '',
        '/',
        '.',
        '..',
        '~',
        '.config',
        'test_data',
        'a path with a space',
    ])
    def test_refuses_hostile_input(self, hostile, tmp_path):
        with pytest.raises(UnsafeDataDirError):
            validate_worker_data_dir(str(tmp_path / hostile) if hostile not in ('', '/', '.', '..', '~') else hostile,
                                      scratch_root=str(tmp_path))

    def test_refuses_a_symlink_pointing_at_test_data(self, tmp_path):
        real_target = tmp_path / 'test_data'
        real_target.mkdir()
        (real_target / 'irreplaceable.txt').write_text('do not delete me')

        symlink_path = tmp_path / '.e2e-w0-data'
        symlink_path.symlink_to(real_target, target_is_directory=True)

        with pytest.raises(UnsafeDataDirError):
            validate_worker_data_dir(str(symlink_path), scratch_root=str(tmp_path))

        # The guard must not have touched the real target either.
        assert (real_target / 'irreplaceable.txt').read_text() == 'do not delete me'

    def test_refuses_a_path_that_is_not_a_direct_child_of_the_scratch_root(self, tmp_path):
        nested = tmp_path / 'subdir' / '.e2e-w0-data'
        with pytest.raises(UnsafeDataDirError):
            validate_worker_data_dir(str(nested), scratch_root=str(tmp_path))

    def test_refuses_a_basename_not_matching_the_e2e_dash_dash_data_shape(self, tmp_path):
        # AC-SEC-9: the name must start with .e2e and end with data. A
        # near-miss like the OLD .e2e-data-mobile shape (ends in the spec
        # slug, not "data") must also be refused.
        with pytest.raises(UnsafeDataDirError):
            validate_worker_data_dir(str(tmp_path / '.e2e-data-mobile'), scratch_root=str(tmp_path))


class TestValidateWorkerDataDirAccepts:

    def test_accepts_a_correctly_shaped_direct_child(self, tmp_path):
        path = tmp_path / '.e2e-w3-data'
        resolved = validate_worker_data_dir(str(path), scratch_root=str(tmp_path))
        assert resolved == str(path.resolve())

    def test_accepts_before_the_directory_exists(self, tmp_path):
        # Validation is a pure path-shape check -- callable BEFORE a server
        # is started or anything is created on disk (AC-DATA-24: "before
        # starting a server").
        path = tmp_path / '.e2e-w7-data'
        assert not path.exists()
        validate_worker_data_dir(str(path), scratch_root=str(tmp_path))


class TestResolveWorkerDataDir:

    def test_builds_the_expected_shape_under_the_scratch_root(self, tmp_path):
        path = resolve_worker_data_dir(3, scratch_root=str(tmp_path))
        assert path == str((tmp_path / '.e2e-w3-data').resolve())

    def test_result_always_passes_its_own_validation(self, tmp_path):
        # Never hand back a path that validate_worker_data_dir would refuse
        # -- this IS the "before starting a server" guard (AC-DATA-24).
        path = resolve_worker_data_dir(0, scratch_root=str(tmp_path))
        validate_worker_data_dir(path, scratch_root=str(tmp_path))  # must not raise


class TestSafeRmtree:
    """AC-DATA-25: the ONE place a worker data dir is ever deleted."""

    def test_deletes_a_valid_worker_dir(self, tmp_path):
        target = tmp_path / '.e2e-w0-data'
        target.mkdir()
        (target / 'database_v2').mkdir()
        (target / 'database_v2' / 'couchpotato.db').write_text('fixture')

        safe_rmtree(str(target), scratch_root=str(tmp_path))

        assert not target.exists()

    def test_is_a_noop_when_the_directory_does_not_exist(self, tmp_path):
        target = tmp_path / '.e2e-w0-data'
        assert not target.exists()
        safe_rmtree(str(target), scratch_root=str(tmp_path))  # must not raise

    @pytest.mark.parametrize('hostile', [
        '',
        '/',
        '.',
        '..',
        '~',
        '.config',
        'test_data',
        'a path with a space',
    ])
    def test_refuses_hostile_input(self, hostile, tmp_path):
        with pytest.raises(UnsafeDataDirError):
            safe_rmtree(str(tmp_path / hostile) if hostile not in ('', '/', '.', '..', '~') else hostile,
                         scratch_root=str(tmp_path))

    def test_refuses_a_symlink_pointing_at_test_data_and_does_not_delete_the_target(self, tmp_path):
        real_target = tmp_path / 'test_data'
        real_target.mkdir()
        (real_target / 'irreplaceable.txt').write_text('do not delete me')

        symlink_path = tmp_path / '.e2e-w0-data'
        symlink_path.symlink_to(real_target, target_is_directory=True)

        with pytest.raises(UnsafeDataDirError):
            safe_rmtree(str(symlink_path), scratch_root=str(tmp_path))

        assert real_target.is_dir()
        assert (real_target / 'irreplaceable.txt').read_text() == 'do not delete me'

    def test_refuses_a_symlink_pointing_at_another_valid_looking_worker_dir(self, tmp_path):
        # A symlink whose basename passes validation (because it resolves
        # to a DIFFERENT, legitimately-named worker dir also directly under
        # the scratch root) must still be refused: deleting worker 0's
        # symlink must never delete worker 1's real data. This is what the
        # explicit os.path.islink() check in safe_rmtree buys on top of
        # validate_worker_data_dir's naming/parent checks, which this
        # specific case would otherwise pass.
        other_worker_real_dir = tmp_path / '.e2e-w1-data'
        other_worker_real_dir.mkdir()
        (other_worker_real_dir / 'sentinel.txt').write_text('worker 1 data')

        symlink_path = tmp_path / '.e2e-w0-data'
        symlink_path.symlink_to(other_worker_real_dir, target_is_directory=True)

        with pytest.raises(UnsafeDataDirError):
            safe_rmtree(str(symlink_path), scratch_root=str(tmp_path))

        assert other_worker_real_dir.is_dir()
        assert (other_worker_real_dir / 'sentinel.txt').read_text() == 'worker 1 data'

    def test_refuses_a_path_that_exists_but_is_a_plain_file(self, tmp_path):
        # A worker dir that somehow ended up as a file, not a directory, is
        # refused rather than blindly unlinked -- it does not match what
        # this helper is for.
        target = tmp_path / '.e2e-w0-data'
        target.write_text('not a directory')

        with pytest.raises(UnsafeDataDirError):
            safe_rmtree(str(target), scratch_root=str(tmp_path))

        assert target.is_file()
