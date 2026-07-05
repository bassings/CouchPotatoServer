"""Tests for GitUpdater (VENDORED-06).

Replaces the vendored `couchpotato/lib/git` shell-out (which used
`subprocess.Popen(..., shell=True)` -- a command-injection surface via the
now-removed `git_command` setting) with dulwich, a pure-Python git
implementation. No system `git` binary or shell is involved anywhere below.

Pull semantics change: `doUpdate()` is a `fetch` + hard reset of the current
branch to `refs/remotes/origin/<branch>`, not a merge/rebase `git pull`. A
source install is not expected to carry local commits, so reset-to-upstream
always converges instead of failing on a diverged history. See
`test_discards_local_commits_not_on_remote` for the explicit behavior this
implies, and `specs/VENDORED-06-replace-git-dulwich.md` for the write-up.
"""
import inspect
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs'))

dulwich = pytest.importorskip('dulwich')

from dulwich import porcelain  # noqa: E402
from dulwich.repo import Repo  # noqa: E402

from couchpotato.environment import Env  # noqa: E402

AUTHOR = b'Test User <test@example.com>'


def _commit(repo, filename, content, message):
    """Write `filename` with `content` and commit it, returning the new sha."""
    path = os.path.join(repo.path, filename)
    with open(path, 'w') as f:
        f.write(content)
    porcelain.add(repo, paths=[path])
    return porcelain.commit(repo, message=message.encode(), author=AUTHOR, committer=AUTHOR)


def _make_updater(app_dir, dev=False):
    from couchpotato.core._base.updater.main import GitUpdater
    Env.set('app_dir', str(app_dir))
    Env.set('dev', dev)
    return GitUpdater()


@pytest.fixture
def repo_pair(tmp_path):
    """A local repo cloned from a "remote", both real dulwich repos on disk.

    This mirrors a genuine source install: `git clone` sets up `origin` and
    remote-tracking refs, and the "remote" can be advanced independently to
    exercise fetch / check / update.
    """
    remote_path = tmp_path / 'remote'
    local_path = tmp_path / 'local'
    remote_path.mkdir()

    remote = Repo.init(str(remote_path))
    _commit(remote, 'version.txt', 'v1', 'initial commit')

    local = porcelain.clone(str(remote_path), str(local_path))

    return remote, local


@pytest.fixture(autouse=True)
def _reset_env():
    yield
    Env.set('app_dir', '')
    Env.set('dev', False)


class TestSignatureDriftGuard:
    """GitUpdater calls a handful of dulwich porcelain/Repo functions with
    specific argument shapes. If a future dulwich release renames or
    reorders these, this guard fails loudly here instead of GitUpdater
    silently breaking for users running from source."""

    def test_porcelain_fetch_accepts_remote_location(self):
        sig = inspect.signature(porcelain.fetch)
        assert 'remote_location' in sig.parameters

    def test_porcelain_reset_accepts_mode_and_treeish(self):
        sig = inspect.signature(porcelain.reset)
        assert {'mode', 'treeish'} <= set(sig.parameters)

    def test_porcelain_active_branch_exists(self):
        assert callable(porcelain.active_branch)

    def test_repo_exposes_head_getitem_and_config(self):
        assert hasattr(Repo, 'head')
        assert hasattr(Repo, '__getitem__')
        assert hasattr(Repo, 'get_config')


class TestGetVersion:

    def test_returns_hash_date_branch_for_local_head(self, repo_pair):
        _remote, local = repo_pair
        updater = _make_updater(local.path)

        version = updater.getVersion()

        assert version['type'] == 'git'
        assert version['branch'] == 'master'
        assert version['hash'] == local.head().decode()[:8]
        assert version['date'] == local[local.head()].author_time

    def test_caches_result_after_first_call(self, repo_pair):
        remote, local = repo_pair
        updater = _make_updater(local.path)

        first = updater.getVersion()
        _commit(remote, 'version.txt', 'v2', 'second commit')  # mutate remote only
        second = updater.getVersion()

        assert first is second


class TestCheck:

    def test_no_update_when_local_matches_remote(self, repo_pair):
        _remote, local = repo_pair
        updater = _make_updater(local.path)

        assert updater.check() is False
        assert updater.update_version is None

    def test_detects_update_when_remote_has_newer_commit(self, repo_pair):
        remote, local = repo_pair
        updater = _make_updater(local.path)

        time.sleep(1.1)  # author_time has 1s resolution; force a distinct value
        remote_sha = _commit(remote, 'version.txt', 'v2', 'second commit')

        assert updater.check() is True
        assert updater.update_version['hash'] == remote_sha.decode()[:8]

    def test_short_circuits_when_update_version_already_set(self, repo_pair):
        _remote, local = repo_pair
        updater = _make_updater(local.path)
        updater.update_version = {'hash': 'deadbeef', 'date': 0}

        assert updater.check() is True

    def test_skips_fetch_in_dev_mode(self, repo_pair, monkeypatch):
        _remote, local = repo_pair
        updater = _make_updater(local.path, dev=True)

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError('fetch must not be called when Env.dev is True')
        monkeypatch.setattr(porcelain, 'fetch', fail_if_called)

        assert updater.check() is False

    def test_swallows_fetch_errors_and_returns_false(self, repo_pair, monkeypatch):
        _remote, local = repo_pair
        updater = _make_updater(local.path)

        def boom(*_args, **_kwargs):
            raise RuntimeError('network is down')
        monkeypatch.setattr(porcelain, 'fetch', boom)

        assert updater.check() is False
        assert updater.update_version is None


class TestDoUpdate:

    def test_fetches_and_hard_resets_to_remote_head(self, repo_pair):
        remote, local = repo_pair
        updater = _make_updater(local.path)

        remote_sha = _commit(remote, 'version.txt', 'v2', 'second commit')

        assert updater.doUpdate() is True
        assert local.head() == remote_sha
        with open(os.path.join(local.path, 'version.txt')) as f:
            assert f.read() == 'v2'

    def test_discards_local_commits_not_on_remote(self, repo_pair):
        """doUpdate() is reset --hard, not a merge -- the documented
        pull-semantics change from the vendored git `pull()`."""
        remote, local = repo_pair
        updater = _make_updater(local.path)

        _commit(local, 'local_only.txt', 'local change', 'local-only commit')
        remote_sha = _commit(remote, 'version.txt', 'v2', 'remote advances')

        assert updater.doUpdate() is True
        assert local.head() == remote_sha
        assert not os.path.exists(os.path.join(local.path, 'local_only.txt'))

    def test_returns_false_and_sets_update_failed_on_error(self, repo_pair, monkeypatch):
        _remote, local = repo_pair
        updater = _make_updater(local.path)

        def boom(*_args, **_kwargs):
            raise RuntimeError('network is down')
        monkeypatch.setattr(porcelain, 'fetch', boom)

        assert updater.doUpdate() is False
        assert updater.update_failed is True


class TestOldRepoRemap:
    """CouchPotato's GitHub organization moved (RuudBurger -> CouchPotato,
    and later to this fork); GitUpdater rewrites a lingering old-org
    `origin` URL on init."""

    def test_rewrites_old_organization_url(self, repo_pair):
        _remote, local = repo_pair
        config = local.get_config()
        config.set((b'remote', b'origin'), b'url', b'https://github.com/RuudBurger/CouchPotatoServer.git')
        config.write_to_path()

        updater = _make_updater(local.path)

        new_url = updater.repo.get_config().get((b'remote', b'origin'), b'url').decode()
        assert new_url == 'https://github.com/CouchPotato/CouchPotatoServer.git'

    def test_leaves_other_urls_untouched(self, repo_pair):
        _remote, local = repo_pair
        original_url = local.get_config().get((b'remote', b'origin'), b'url').decode()

        updater = _make_updater(local.path)

        current_url = updater.repo.get_config().get((b'remote', b'origin'), b'url').decode()
        assert current_url == original_url

    def test_repo_without_origin_remote_does_not_raise(self, tmp_path):
        repo_path = tmp_path / 'solo'
        repo_path.mkdir()
        repo = Repo.init(str(repo_path))
        _commit(repo, 'f.txt', 'x', 'init')

        updater = _make_updater(repo_path)  # must not raise KeyError

        assert updater.getVersion()['hash'] == repo.head().decode()[:8]
