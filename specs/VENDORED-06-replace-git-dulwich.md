# VENDORED-06: Replace vendored `git` library with `dulwich`

## Problem

`couchpotato/lib/git/` is a small vendored git wrapper (Python 2-era, MIT/BSD
"Rotem Yaari" library) used only by `GitUpdater` in
`couchpotato/core/_base/updater/main.py` to self-update source (`.git`
present) installs. It has two independent problems:

1. **Already broken on Python 3.** `repository.py` uses `basestring` (Py2-only,
   no Py3 builtin) in `_asURL`/`__contains__`, and several call sites are
   wrapped in broad `except Exception` that silently swallow the resulting
   `NameError`. In practice `GitUpdater` limps along for the read paths
   (`getHead`, `getCurrentBranch`) that don't hit the broken code, but is
   fragile.
2. **Command-injection surface.** `Repository._executeGitCommand` shells out
   via `subprocess.Popen(command, shell=True, ...)`, string-formatting the
   configured `git_command` setting directly into the shell command line.
   The `git_command` setting (`couchpotato/core/_base/updater/__init__.py`)
   was validated with a permissive regex
   (`^[a-zA-Z0-9_/\.\-]+$`) but still let a user point it at an arbitrary
   local binary, and combined with `shell=True` any future refactor that
   passes untrusted input through this path is one mistake away from command
   injection.

Because GitUpdater is source-install-only (not the Docker path most users
run), the blast radius is limited, but it's still worth removing the shell-out
and the setting that drives it.

## Approach

Replace `couchpotato/lib/git` entirely with `dulwich` (pinned `1.2.7`, pure
Python, no system `git` binary or shell involved). `GitUpdater` is rewritten
against `dulwich.repo.Repo` + `dulwich.porcelain`:

- **Current branch:** `dulwich.porcelain.active_branch(repo)`
- **Current commit / hash:** `repo.head()` (40-char hex sha, truncated to 8
  for display, matching the old behavior)
- **Last-commit date:** `repo[repo.head()].author_time` (unix timestamp;
  matches the vendored lib's `git log --pretty=format:%at`, i.e. author date,
  not committer date)
- **Fetching:** `dulwich.porcelain.fetch(repo, 'origin')` — must be called
  with the *remote name* `'origin'`, not a raw path/URL; dulwich only updates
  the `refs/remotes/origin/<branch>` tracking refs when fetching by
  configured remote name (verified experimentally: fetching by literal path
  pulls objects but does not update the remote-tracking ref).
- **Comparing local vs remote:** after fetch, read
  `repo.refs[b'refs/remotes/origin/<branch>']` and compare its
  `author_time` against the local `HEAD` commit's `author_time`.
- **Pulling:** see "Pull semantics change" below.

### Pull semantics change

The vendored lib's `pull()` shelled out to `git pull` (fetch + merge/rebase
per the user's git config). The dulwich rewrite instead does:

1. `porcelain.fetch(repo, 'origin')`
2. Look up `refs/remotes/origin/<current-branch>`
3. `porcelain.reset(repo, 'hard', treeish=<that sha>)`

This is a **fetch + hard reset to `origin/<branch>`**, not a merge. A
CouchPotato source install is not expected to carry local commits ahead of
`origin` — the whole point of `GitUpdater` is "make this checkout match
upstream" — so reset-to-upstream always converges, whereas a merge/rebase
could fail outright on a diverged history (which the old code didn't handle
either; `_executeGitCommandAssertSuccess` would just raise, caught by the
broad `except Exception` in `doUpdate()`). The behavioral difference that
matters: **any local-only commits in the working copy are silently discarded**
on update, same as they always were on the DockerUpdater/SourceUpdater tarball
paths, and now made explicit for GitUpdater too (see
`test_discards_local_commits_not_on_remote` in
`tests/unit/test_updater.py`).

### `git_command` setting removed

The `git_command` option (in `couchpotato/core/_base/updater/__init__.py`,
gated by `git_only`/hidden-unless-`.git`-present) is deleted outright, along
with the derivation/validation logic in `Updater.__init__`
(`couchpotato/core/_base/updater/main.py`). `GitUpdater()` now takes no
arguments — dulwich needs no external binary, so there is nothing to
configure or inject through.

### Old-organization URL remap preserved

`GitUpdater` still rewrites a lingering `origin` remote pointing at the old
`RuudBurger/CouchPotatoServer` GitHub org to `CouchPotato/CouchPotatoServer`,
now via `dulwich`'s `ConfigFile` (`repo.get_config()` / `.set()` /
`.write_to_path()`) instead of a `git remote set-url` shell-out. A repo with
no `origin` remote configured at all (`KeyError` from `config.get(...)`) is a
no-op, not an error.

### Public interface preserved

`getVersion()` / `check()` / `doUpdate()` signatures and the version dict
shape (`hash`, `date`, `type`, `branch`, `repr`) are unchanged — the rest of
`updater/main.py` (`Updater.info()`, `.check()`, `.autoUpdate()`) and the
settings UI (`updater.js`) consume these unmodified.

## What did not change

- `DockerUpdater`, `SourceUpdater`, `DesktopUpdater` — untouched; `Updater`
  still picks one class based on install type
  (`Env.get('desktop')` / `CP_DOCKER` env / `.dockerenv` / `.git` dir
  present / fallback).
- CodernityDB — not touched by this change.
- The other vendored libraries under `couchpotato/lib/` (`rtorrent`,
  `qbittorrent`, `subliminal`, `unrar2`) and the `couchpotato/lib/__init__.py`
  sys.path shim that makes their internal imports work — untouched.

## Files changed

- `requirements.txt` — add `dulwich==1.2.7`
- `couchpotato/core/_base/updater/main.py` — `GitUpdater` rewritten against
  dulwich; `Updater.__init__` no longer derives/passes `git_command`; unused
  `import re` removed
- `couchpotato/core/_base/updater/__init__.py` — `git_command` setting
  definition removed; now-unused `os` / `Env` imports removed
- `couchpotato/lib/git/` — deleted entirely (11 files)
- `tests/unit/test_updater.py` — new; TDD coverage for `GitUpdater`

## Acceptance Criteria

- [x] `dulwich==1.2.7` pinned in `requirements.txt`, installs as a wheel
      (`cp314-cp314-macosx_11_0_arm64` confirmed locally, no compilation)
- [x] `couchpotato/lib/git/` fully deleted; no remaining `lib.git` / vendored
      git imports anywhere in the tree
- [x] `git_command` setting fully removed (definition + all references)
- [x] `GitUpdater` reimplemented on dulwich; `getVersion()` / `check()` /
      `doUpdate()` preserve their public signatures and return shapes
- [x] `couchpotato.core._base.updater.main` imports cleanly (verified
      directly, and via `tests/unit/test_plugin_import_sweep.py`'s
      whole-core-tree import sweep)
- [x] New `tests/unit/test_updater.py`: real on-disk dulwich repos (no
      network, no mocked git plumbing) covering `getVersion` (hash/date/
      branch + caching), `check` (up-to-date / update-detected / dev-mode
      skips fetch / fetch-error handling), `doUpdate` (fast-forward reset,
      discarding local-only commits, error handling), the old-org URL remap
      (rewrite / leave-alone / no-origin-remote), and a signature-drift guard
      asserting the exact `dulwich.porcelain` functions/args this code
      depends on still exist
- [x] `pytest tests/unit/ -q` green (867 passed)
- [x] `ruff check .` clean
