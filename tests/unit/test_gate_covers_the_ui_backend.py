"""The gate runs the browser suites unless a change is provably irrelevant.

**This inverts the original rule, and the measurement is why.**

The first design listed what a browser could see and skipped everything else.
It was wrong twice in review, and the second time showed it could not be made
right: the UI calls the API from templates as well as from Python, across 33
endpoints in 16 top-level namespaces -- `app category collection directory
download logging manage media movie profile provider quality release search
settings updater`. That is the whole application. An allowlist that covered it
honestly would be `couchpotato/`.

So the saving was not real independence between backend and UI; it came from
under-covering. `renamer`, `searcher`, `updater` and `quality` all skipped the
browser suites while the browser called every one of those namespaces.

The rule is now: SKIP only what cannot reach a browser -- documentation, plans,
QA notes, unit tests, agent scratch. Everything else runs.

Measured cost: of the last 60 commits, 6 touch only skip-listed paths. That is
the honest saving, and it is smaller than the original claim. The failure
direction is what changed: an unrecognised path now RUNS the suites instead of
skipping them, which is the direction every other decision in this gate takes.
"""
import subprocess
from pathlib import Path

import pytest

from tests.unit.conftest import sanitized_git_env

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'scripts' / 'needs_e2e.sh'


def classify(repo_dir, *paths, base='main'):
    """Commit `paths` in a throwaway repo and ask the real script."""
    def git(*args):
        subprocess.run(['git', *args], cwd=str(repo_dir), check=True,
                       capture_output=True, text=True, env=sanitized_git_env())
    for rel in paths:
        target = repo_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('changed\n')
    git('add', '-A')
    git('commit', '-qm', 'change')
    return subprocess.run([str(SCRIPT), base], cwd=str(repo_dir),
                          capture_output=True, text=True,
                          env=sanitized_git_env()).returncode


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=str(tmp_path), check=True,
                       capture_output=True, text=True, env=sanitized_git_env())
    git('init', '-q', '-b', 'main')

    # Defense in depth: verify the effect, not just the input. See
    # test_hybrid_gate.py's `repo` fixture for the full rationale and
    # tests/unit/test_fixtures_do_not_leak_gitdir.py for the regression test.
    absolute_git_dir = subprocess.run(
        ['git', 'rev-parse', '--absolute-git-dir'], cwd=str(tmp_path),
        check=True, capture_output=True, text=True, env=sanitized_git_env(),
    ).stdout.strip()
    assert Path(absolute_git_dir).resolve() == (tmp_path / '.git').resolve(), (
        'this fixture\'s git operations are not targeting the throwaway '
        'tmp_path (got %s) -- refusing to continue rather than risk running '
        'further git commands against a real repository' % absolute_git_dir
    )

    git('config', 'user.email', 't@example.com')
    git('config', 'user.name', 'T')
    (tmp_path / 'seed.txt').write_text('seed\n')
    git('add', '-A')
    git('commit', '-qm', 'seed')
    git('checkout', '-q', '-b', 'work')
    return tmp_path


class TestBackendChangesRunTheBrowserSuites:
    """The whole point of the inversion. Every one of these SKIPPED under the
    allowlist while the browser called its namespace."""

    @pytest.mark.parametrize('path', [
        'couchpotato/core/plugins/renamer/main.py',      # browser calls release.*
        'couchpotato/core/media/movie/searcher.py',      # movie.searcher.*
        'couchpotato/core/_base/updater/main.py',        # updater.info
        'couchpotato/core/plugins/quality/main.py',      # quality.list
        'couchpotato/core/plugins/category/main.py',     # category.*
        'couchpotato/core/plugins/profile/main.py',      # profile.*
        'couchpotato/core/settings.py',                  # settings, settings.save
        'couchpotato/api.py',                            # every call goes through it
        'couchpotato/runner.py',
    ])
    def test_a_backend_change_runs_them(self, repo, path):
        assert classify(repo, path) == 0, (
            '%s skipped the browser suites, but the browser reaches this code '
            'through the API' % path
        )


class TestOnlyProvablyIrrelevantPathsSkip:
    @pytest.mark.parametrize('path', [
        'docs/technical-debt.md',
        'specs/SOME-SPEC.md',
        'QA/findings.md',
        'tests/unit/test_something.py',
        '.claude/agents/whatever.md',
        'README.md',
    ])
    def test_these_skip(self, repo, path):
        assert classify(repo, path) == 1, '%s should not need a browser' % path

    def test_a_mixed_change_runs_them(self, repo):
        """One relevant file among documentation is still a reason to run."""
        assert classify(repo, 'docs/notes.md', 'couchpotato/core/thing.py') == 0

    @pytest.mark.parametrize('path', [
        'libs/README.md',
        'couchpotato/core/plugins/renamer/NOTES.md',
    ])
    def test_a_nested_markdown_file_RUNS_them(self, repo, path):
        """`[^/]*\\.md$` is root-level only, and that is deliberate.

        A `.md` sitting inside a code tree has not been reasoned about, so it
        takes the safe direction. This pins it: broadening the pattern to a
        bare `\\.md$` to make "markdown always skips" true would fail here,
        which is the point -- the comment in the script says do not do that,
        and a comment cannot fail.
        """
        assert classify(repo, path) == 0, (
            '%s skipped, so the .md branch is no longer root-only' % path
        )

    def test_an_unrecognised_path_RUNS_them(self, repo):
        """The direction that matters. Under the allowlist an unknown path
        skipped; now it runs, which is how every other uncertainty in this
        script resolves."""
        assert classify(repo, 'some/brand/new/place.py') == 0


class TestTheOriginalBrowserPathsStillRun:
    @pytest.mark.parametrize('path', [
        'couchpotato/ui/templates/base.html',
        'couchpotato/static/scripts/ui/movie-filter.js',
        'couchpotato/templates/login.html',
        'tests/e2e/navigation.spec.ts',
        'playwright.config.ts',
        'package.json',
        'scripts/verify.sh',
        'scripts/needs_e2e.sh',
        '.github/workflows/ci.yml',
    ])
    def test_still_runs(self, repo, path):
        assert classify(repo, path) == 0, path
