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
            # Fail-closed: an ABSENT answer must still run the suites. See
            # TestTheBrowserJobsFailClosedWhenScopeCannotDecide.
            assert "needs.scope.outputs.browser != 'false'" in spec.get('if', ''), job

    def test_the_scope_job_forces_yes_off_pull_requests(self):
        """The change-surface rule is a PR-time optimisation. Master and the
        nightly run are held to the full suite regardless, or a long stretch of
        Python-only work would never exercise the UI at all."""
        text = CI.read_text(encoding='utf-8')
        assert '"$EVENT_NAME" != "pull_request"' in text
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


class TestTheLiveStaticAssetTreeIsCovered:
    """`couchpotato/static/` is a SEPARATE tree from `couchpotato/ui/`, and it
    is the one holding the client-side JavaScript the modern UI actually loads
    (`base.html` pulls in `static/scripts/ui/index.js`). The first version of
    this matcher covered only `couchpotato/ui/` and its comment claimed that
    "covers static assets" -- which was simply wrong about the layout.

    `movie-filter.js` is the code `tests/e2e/filters.spec.ts` exercises, so the
    hole let a change to the exact file a named E2E spec covers take the fast
    path. The gap shipped green because no parametrised case named this
    directory at all.
    """

    @pytest.mark.parametrize('path', [
        'couchpotato/static/scripts/ui/movie-filter.js',
        'couchpotato/static/scripts/ui/profile-editor.js',
        'couchpotato/static/sw.js',
        'couchpotato/static/manifest.json',
        'couchpotato/static/style/main.css',
    ])
    def test_a_change_to_a_served_static_asset_needs_the_suites(self, repo, path):
        repo['commit'](path)
        assert _run('main', cwd=repo['dir']) == 0, path


class TestARenameAwayFromTheUiStillCounts:
    def test_moving_a_template_out_of_the_ui_tree_needs_the_suites(self, repo):
        """Git rename detection reports only the DESTINATION. Moving a live
        template to `docs/` therefore looked like a docs-only change, so the
        rendered UI could lose a template while every browser suite was
        skipped. A deletion dressed as a rename must not be quieter than a
        deletion."""
        import subprocess as sp

        def _git(*args):
            sp.run(['git', *args], cwd=repo['dir'], check=True, capture_output=True)

        # The template must exist on the BASE, or the net diff is just an
        # added docs file and the test proves nothing.
        _git('checkout', '-q', 'main')
        target = repo['dir'] / 'couchpotato' / 'ui' / 'templates'
        target.mkdir(parents=True, exist_ok=True)
        (target / 'view.html').write_text('x' * 400)
        _git('add', '-A')
        _git('commit', '-qm', 'template lives here')
        _git('checkout', '-q', 'work')
        _git('rebase', '-q', 'main')

        _git('rm', '-q', 'couchpotato/ui/templates/view.html')
        (repo['dir'] / 'docs').mkdir(exist_ok=True)
        (repo['dir'] / 'docs' / 'view.txt').write_text('x' * 400)
        _git('add', '-A')
        _git('commit', '-qm', 'move it out')

        # Precondition: git really does collapse this to a rename, otherwise
        # the test passes for the wrong reason.
        renamed = sp.run(['git', 'diff', '--name-only', 'main...HEAD'],
                         cwd=repo['dir'], capture_output=True, text=True).stdout.split()
        assert renamed == ['docs/view.txt'], (
            'git did not detect a rename, so this fixture cannot provoke the '
            'bug: %r' % renamed
        )

        assert _run('main', cwd=repo['dir']) == 0


class TestALargeDiffDoesNotSilentlySkip:
    def test_an_early_match_among_thousands_of_files_still_answers_yes(self, repo):
        """SIGPIPE under `pipefail`, and a fail-OPEN one.

        `echo "$CHANGED" | grep -q` made `grep` exit at the first match. With
        enough remaining output to fill the pipe buffer, the writer took
        SIGPIPE, the pipeline returned 141, and `if` took the FALSE branch --
        so the more browser-visible files a change touched, the more likely it
        was to skip the browser suites. Measured locally: correct at 1,000
        paths, wrong at 4,000.

        The fixture must therefore be big enough to fill the buffer. A handful
        of files cannot provoke it and would pass against the bug.
        """
        import subprocess as sp
        target = repo['dir'] / 'couchpotato' / 'ui' / 'templates'
        target.mkdir(parents=True, exist_ok=True)
        (target / 'aaa.html').write_text('x\n')     # sorts early: matched first
        bulk = repo['dir'] / 'zzz_bulk'
        bulk.mkdir(exist_ok=True)
        for i in range(6000):
            (bulk / ('file_%05d.py' % i)).write_text('x\n')
        sp.run(['git', 'add', '-A'], cwd=repo['dir'], check=True, capture_output=True)
        sp.run(['git', 'commit', '-qm', 'a lot'], cwd=repo['dir'], check=True,
               capture_output=True)

        assert _run('main', cwd=repo['dir']) == 0, (
            'a browser-visible file was lost in a large diff'
        )


class TestThePushBaseIsTheTargetBranchNotTheLastPush:
    """`@{upstream}` is the branch's OWN remote-tracking ref once it has been
    pushed, not the branch it will merge into.

    So the first push of a branch diffed against master and ran the full gate,
    and every push after that diffed against the previous push. A branch whose
    first commit touched the UI and whose second was Python-only took the fast
    path locally while the cumulative PR still changed the UI. CI was
    unaffected (it diffs `github.base_ref` explicitly), which is worse rather
    than better: the two callers of the "single source of truth" were asking
    it different questions, the exact drift this design exists to prevent.
    """

    BASE_SCRIPT = REPO / 'scripts' / 'push_base_ref.sh'

    def _remote_repo(self, tmp_path):
        import subprocess as sp
        origin = tmp_path / 'origin.git'
        sp.run(['git', 'init', '-q', '--bare', '-b', 'master', str(origin)],
               check=True, capture_output=True)
        clone = tmp_path / 'clone'
        sp.run(['git', 'clone', '-q', str(origin), str(clone)],
               check=True, capture_output=True)

        def _git(*args, cwd=clone):
            return sp.run(['git', *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()

        _git('config', 'user.email', 't@example.com')
        _git('config', 'user.name', 'T')
        (clone / 'seed.txt').write_text('seed\n')
        _git('add', '-A')
        _git('commit', '-qm', 'seed')
        _git('push', '-q', 'origin', 'master')
        return clone, _git

    def _base(self, cwd):
        import subprocess as sp
        return sp.run([str(self.BASE_SCRIPT)], cwd=str(cwd),
                      capture_output=True, text=True).stdout.strip()

    def test_before_the_first_push_the_base_is_master(self, tmp_path):
        clone, git = self._remote_repo(tmp_path)
        git('checkout', '-q', '-b', 'feature')
        assert self._base(clone).endswith('master')

    def test_AFTER_the_first_push_the_base_is_STILL_master(self, tmp_path):
        """The regression itself. With `@{upstream}` this returned
        `origin/feature` and the gate narrowed to "since my last push"."""
        clone, git = self._remote_repo(tmp_path)
        git('checkout', '-q', '-b', 'feature')
        (clone / 'a.txt').write_text('a\n')
        git('add', '-A')
        git('commit', '-qm', 'one')
        git('push', '-q', '-u', 'origin', 'feature')

        # Precondition: upstream really is the branch's own ref now, so this
        # test would be vacuous if it were not.
        assert git('rev-parse', '--abbrev-ref', '--symbolic-full-name',
                   '@{upstream}') == 'origin/feature'

        assert self._base(clone).endswith('master'), (
            'the pre-push base narrowed to the last push'
        )

    def test_the_hook_uses_the_helper_and_not_the_upstream_ref(self):
        code = [
            line for line in HOOK.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')
        ]
        assert not any('@{upstream}' in line for line in code), (
            'the hook went back to diffing against its own last push'
        )
        assert any('push_base_ref.sh' in line for line in code)


class TestTheBrowserJobsFailClosedWhenScopeCannotDecide:
    """A skipped job SATISFIES a required status check on GitHub.

    So if `scope` dies before writing its output -- a failed checkout, a
    classifier that cannot run -- then `needs.scope.outputs.browser` is empty,
    `== 'true'` is false, both browser jobs skip, and the PR is mergeable with
    no E2E and no accessibility coverage at all. The condition must therefore
    key on the only value that is safe to skip on: an explicit 'false'.
    """

    @pytest.fixture
    def jobs(self):
        return yaml.safe_load(CI.read_text())['jobs']

    @pytest.mark.parametrize('job', BROWSER_JOBS)
    def test_the_gate_is_an_explicit_false_not_a_missing_true(self, jobs, job):
        condition = jobs[job]['if']
        assert "needs.scope.outputs.browser != 'false'" in condition, (
            '%s skips whenever scope fails to produce an answer' % job
        )
        assert "needs.scope.outputs.browser == 'true'" not in condition, (
            '%s still keys on the presence of a true, so an absent answer '
            'silently skips it' % job
        )

    @pytest.mark.parametrize('job', BROWSER_JOBS)
    def test_a_failed_scope_job_does_not_skip_the_browser_job(self, jobs, job):
        """`needs:` alone would skip the dependent job when scope fails, no
        matter what the `if` says, so the condition must survive that."""
        condition = jobs[job]['if']
        assert 'cancelled()' in condition, (
            '%s relies on the implicit success() of its needs, so a failed '
            'scope job skips it before the condition is even read' % job
        )


class TestTheScopeStepDoesNotSpliceContextIntoTheShell:
    def test_the_classifier_reads_its_inputs_from_env(self):
        """Not exploitable today -- the `pull_request` trigger is filtered to
        two literal branches. It is the shape that matters: the filter is one
        careless widening away from being untrusted input in a `run:` block,
        and `env:` costs nothing."""
        scope = yaml.safe_load(CI.read_text())['jobs']['scope']
        step = [s for s in scope['steps'] if s.get('id') == 'decide'][0]
        assert '${{' not in step['run'], (
            'GitHub context is interpolated straight into the shell: %s'
            % step['run']
        )
        assert 'BASE_REF' in step.get('env', {})
