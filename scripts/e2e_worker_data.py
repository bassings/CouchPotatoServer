"""The ONE guarded helper for validating and deleting a per-E2E-worker data
dir (T1.7, AC-DATA-24/25/26).

Why this exists: `CouchPotato.py:53` gates `--data_dir` on truthiness, so an
empty string silently falls through to `Env.setting('data_dir')` and then
`getDataDir()` -- the developer's REAL library, not a throwaway one.
Measured neighbours in this repo: `.config` is a 68 MiB live database and
`test_data/` is 71 MiB of gitignored, git-unrecoverable data, both siblings
of the repo root. A per-worker E2E harness computes a fresh data dir string
for every Playwright worker and deletes it again on teardown; if that
computation is ever wrong -- empty, a typo, a symlink -- this is what stands
between that bug and an `rm -rf` of irreplaceable data.

Two functions, and every caller in this codebase goes through them:

  validate_worker_data_dir(path)  -- pure path-shape check, no filesystem
                                      writes. Callable BEFORE a server is
                                      started (AC-DATA-24).
  safe_rmtree(path)               -- the ONE place a worker data dir is
                                      ever deleted (AC-DATA-25). Validates
                                      first, then deletes.

The validation shape mirrors `scripts/backup.sh:244-301`'s prune_snapshots,
which documents this exact class of guard on this repo: an allowlist regex
on the basename (not a blacklist -- a blacklist only ever refuses the
attacks someone thought of), a check that the path resolves to a DIRECT
child of the designated scratch root (not merely somewhere underneath it),
and symlinks handled by resolving through `os.path.realpath` before either
check runs, so a symlink whose own name looks safe but points somewhere
else is refused by the SAME two checks rather than a special case bolted on
for symlinks specifically.
"""
import os
import re
import shutil

#: AC-SEC-9: the basename must start with ".e2e" and end with "data" --
#: `.gitignore` (`.e2e-*data/`) and `.gitleaks.toml`
#: (`^\.e2e-[^/]*data/`) both key off exactly that shape. A worker dir named
#: `.e2e-data-mobile` (the OLD convention) matches neither and is refused
#: here for the same reason those two files would leak it.
_WORKER_DIR_RE = re.compile(r'^\.e2e-[A-Za-z0-9_.-]+-data$')

#: Default scratch root: the repo root, matching where every other E2E
#: throwaway dir (`.e2e-data`, `.config`, `test_data/`) already lives, and
#: where `scripts/seed_e2e_data.py`'s own `_is_safe_seed_target` anchors its
#: equivalent check. Every caller can override it (tests do, to stay inside
#: `tmp_path` rather than touching this checkout).
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_SCRIPT_DIR)


class UnsafeDataDirError(RuntimeError):
    """Raised when a path fails the AC-DATA-24/25 validation. Never caught
    and silently downgraded by any caller in this codebase -- an unsafe
    path must abort the run, not fall back to some other directory."""


def validate_worker_data_dir(path, scratch_root=None):
    """Refuse anything that is not obviously a disposable per-worker E2E
    data dir. Raises `UnsafeDataDirError` naming the problem; returns the
    resolved absolute path on success.

    Refuses:
      - an empty path,
      - anything that does not resolve to a DIRECT child of `scratch_root`
        (default: the repo root) -- '.', '..', '/', '~', a nested path, or
        a symlink whose target resolves elsewhere all fail this,
      - a basename that does not match `.e2e-<anything>-data` -- '.config',
        'test_data', a bare space-containing string, or the OLD
        `.e2e-data-mobile` shape all fail this.

    Pure path-shape check: makes no filesystem writes, so it is callable
    before anything -- including a server -- has started (AC-DATA-24).
    """
    root = os.path.realpath(os.path.abspath(scratch_root or REPO_ROOT))

    if not path:
        raise UnsafeDataDirError('data dir path is empty')

    # realpath resolves symlinks, '.', '..' and '~' is NOT expanded (we
    # deliberately do not call expanduser -- a literal '~' is just a
    # basename that will not match _WORKER_DIR_RE below). A symlink whose
    # own name looks safe but points outside the scratch root, or at a
    # differently-named real directory (e.g. test_data/), is caught by
    # resolving BEFORE either check runs -- both checks below then operate
    # on where the path actually points, not what it is called.
    resolved = os.path.realpath(os.path.abspath(path))

    if os.path.dirname(resolved) != root:
        raise UnsafeDataDirError(
            '%r does not resolve to a direct child of the scratch root %r '
            '(resolved to %r) -- refusing to treat it as a disposable E2E '
            'data dir' % (path, root, resolved)
        )

    basename = os.path.basename(resolved)
    if not _WORKER_DIR_RE.match(basename):
        raise UnsafeDataDirError(
            '%r (basename %r) does not match the required .e2e-*-data '
            'naming shape' % (path, basename)
        )

    return resolved


def resolve_worker_data_dir(worker_index, scratch_root=None):
    """Build the per-worker data dir path for `worker_index` and validate
    it before returning -- never hands back a path validate_worker_data_dir
    would refuse (AC-DATA-24: validated before a server is ever started).
    """
    root = scratch_root or REPO_ROOT
    path = os.path.join(root, '.e2e-w%s-data' % worker_index)
    return validate_worker_data_dir(path, scratch_root=root)


def safe_rmtree(path, scratch_root=None):
    """The ONE place an E2E worker data dir is ever deleted (AC-DATA-25).

    Validates `path` first (raises `UnsafeDataDirError` on anything that
    fails `validate_worker_data_dir`, including a symlink -- explicitly
    re-checked here even though validation already resolves through it, so
    the refusal reads as "this is a symlink" rather than a naming-shape
    mismatch further down the diagnostic chain), then deletes it. A path
    that does not exist is a no-op, not an error -- teardown must not fail
    a run just because a worker never got as far as creating its dir.
    """
    resolved = validate_worker_data_dir(path, scratch_root=scratch_root)

    if os.path.islink(path):
        raise UnsafeDataDirError(
            '%r is a symlink -- refusing to delete through it' % path
        )

    if not os.path.exists(resolved):
        return

    if not os.path.isdir(resolved):
        raise UnsafeDataDirError(
            '%r exists but is not a directory -- refusing to delete it' % path
        )

    shutil.rmtree(resolved)
