"""The local gate and CI must agree about what needs browser tests (T16).

The hybrid gate skips E2E, accessibility and mobile when nothing
browser-visible changed — locally in `.githooks/pre-push`, and on pull requests
in `ci.yml`. That is only safe while BOTH sides ask the same question.

Two copies of "what counts as a UI change" drift, and when they drift the
quieter side silently stops covering something — which is indistinguishable
from working. So there is exactly one implementation,
`scripts/needs_e2e.sh`, and these tests fail if either caller stops using it
or if the script stops erring towards running.
"""
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip('yaml')

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'scripts' / 'needs_e2e.sh'
HOOK = REPO / '.githooks' / 'pre-push'
CI = REPO / '.github' / 'workflows' / 'ci.yml'

BROWSER_JOBS = ('ui-e2e-tests', 'accessibility')


def _run(*args, cwd):
    return subprocess.run(
        [str(SCRIPT), *args], cwd=str(cwd), capture_output=True, text=True
    ).returncode


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo, so the script is exercised against real diffs
    rather than a mocked `git`."""
    def _git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True,
                       capture_output=True, text=True)

    _git('init', '-q', '-b', 'main')
    _git('config', 'user.email', 't@example.com')
    _git('config', 'user.name', 'T')
    (tmp_path / 'seed.txt').write_text('seed\n')
    _git('add', '-A')
    _git('commit', '-qm', 'seed')

    _git('checkout', '-q', '-b', 'work')

    def _commit(path, body='x\n'):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        _git('add', '-A')
        _git('commit', '-qm', 'change %s' % path)

    return {'dir': tmp_path, 'commit': _commit}


class TestTheScriptAnswersTheQuestion:
    @pytest.mark.parametrize('path', [
        'couchpotato/ui/templates/base.html',
        'couchpotato/ui/static/app.js',
        'couchpotato/templates/login.html',      # the other live render root
        'tests/e2e/navigation.spec.ts',
        'playwright.config.ts',
        'package-lock.json',                     # pins the browser itself
        'scripts/verify.sh',
        '.github/workflows/ci.yml',
    ])
    def test_browser_visible_changes_need_the_suites(self, repo, path):
        repo['commit'](path)
        assert _run('main', cwd=repo['dir']) == 0, path

    @pytest.mark.parametrize('path', [
        'couchpotato/core/plugins/renamer/main.py',
        'tests/unit/test_something.py',
        'docs/technical-debt.md',
        'README.md',
    ])
    def test_non_browser_changes_do_not(self, repo, path):
        repo['commit'](path)
        assert _run('main', cwd=repo['dir']) == 1, path

    def test_a_mixed_change_needs_them(self, repo):
        """One browser-visible file among many is still a reason to run."""
        repo['commit']('couchpotato/core/thing.py')
        repo['commit']('couchpotato/ui/templates/base.html')
        assert _run('main', cwd=repo['dir']) == 0


class TestItErrsTowardsRunning:
    """A slow gate is an annoyance. A skipped gate that should have run is how
    a UI regression reaches master, so every uncertain case must answer YES."""

    def test_no_base_ref(self, repo):
        assert _run(cwd=repo['dir']) == 0

    def test_an_unresolvable_base_ref(self, repo):
        assert _run('no-such-ref', cwd=repo['dir']) == 0

    def test_an_empty_diff(self, repo):
        assert _run('main', cwd=repo['dir']) == 0


class TestBothCallersUseTheSharedScript:
    """The drift guard. If either side grows its own path list, the two stop
    agreeing and the quieter one silently covers less."""

    @staticmethod
    def _invocations(path):
        """Non-comment lines that actually RUN the script.

        Substring-matching the filename was vacuous: the hook's own comment
        mentions `needs_e2e.sh`, so replacing the real call with `if false;`
        left the test green. Mutation testing caught it. A guard that passes
        because of a comment is not a guard.
        """
        return [
            ln for ln in path.read_text(encoding='utf-8').splitlines()
            if 'needs_e2e.sh' in ln and not ln.lstrip().startswith('#')
        ]

    def test_the_pre_push_hook_actually_runs_it(self):
        calls = self._invocations(HOOK)
        assert calls, 'the hook mentions the script but never executes it'
        assert any('$REPO_ROOT' in ln or './scripts' in ln for ln in calls), calls

    def test_the_workflow_actually_runs_it(self):
        calls = self._invocations(CI)
        assert calls, 'the workflow mentions the script but never executes it'
        assert any('./scripts/needs_e2e.sh' in ln for ln in calls), calls

    def test_neither_caller_hardcodes_its_own_ui_path_list(self):
        """A second list is the drift. `couchpotato/ui/` appearing in the hook
        or in a workflow path filter means somebody re-answered the question
        locally instead of asking the script."""
        for caller in (HOOK, CI):
            text = caller.read_text(encoding='utf-8')
            # Prose is fine -- an unrelated job's comment mentions the UI
            # directory, and always did. What must not exist is a second
            # DECISION: a `paths:`/`paths-ignore:` filter, or a grep of the
            # diff, that answers the same question independently.
            lines = [
                ln for ln in text.splitlines()
                if 'couchpotato/ui/' in ln and not ln.lstrip().startswith('#')
            ]
            assert not lines, (
                '%s answers the UI question itself instead of asking the '
                'script; there must be exactly one implementation: %s'
                % (caller.name, lines)
            )


class TestTheBrowserJobsAreGatedButStillReport:
    def test_both_browser_jobs_depend_on_the_scope_decision(self):
        workflow = yaml.safe_load(CI.read_text(encoding='utf-8'))
        for job in BROWSER_JOBS:
            spec = workflow['jobs'][job]
            assert 'scope' in (spec.get('needs') or []), job
            assert spec.get('if') == "needs.scope.outputs.browser == 'true'", job

    def test_the_scope_job_forces_yes_off_pull_requests(self):
        """The change-surface rule is a PR-time optimisation. Master and the
        nightly run are held to the full suite regardless, or a long stretch of
        Python-only work would never exercise the UI at all."""
        text = CI.read_text(encoding='utf-8')
        assert "github.event_name }}\" != \"pull_request\"" in text
        assert 'browser=true' in text

    def test_a_nightly_schedule_exists(self):
        workflow = yaml.safe_load(CI.read_text(encoding='utf-8'))
        triggers = workflow.get(True) or workflow.get('on')
        assert 'schedule' in triggers, 'no nightly run: a quiet week would never test the UI'

    def test_the_accessibility_job_did_not_rejoin_the_serial_chain(self):
        """CI-003 removed `needs: ui-e2e-tests` from accessibility because it
        cost 516s of a 656s wall-clock. Depending on `scope` is fine — that job
        is seconds — but depending on a test job again would undo that work."""
        workflow = yaml.safe_load(CI.read_text(encoding='utf-8'))
        assert workflow['jobs']['accessibility'].get('needs') == ['scope']
