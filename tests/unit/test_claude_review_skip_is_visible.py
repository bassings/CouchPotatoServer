"""`claude-review` is a REQUIRED check that can pass without running.

GitHub refuses to run a workflow from a pull request that modifies that
workflow's own file: "the workflow file must exist and have identical content
to the version on the repository's default branch". `claude-review` is a
required status check, so on any PR editing `.github/workflows/claude-review.yml`
the check reports success while the reviewer never executed.

Measured, four for four: #129, #132, #149 and #281 each edit this file and each
carries ZERO `claude[bot]` comments, while every non-Dependabot PR around them
has them. ALL FOUR were themselves changes to the reviewer -- a visible verdict,
comment permissions, the Dependabot skip, and finding routing -- so the changes
least able to afford going unreviewed are exactly the ones that did. The reason
appears in the job log a few hundred lines in, where nobody looks.

WHY THIS FILE EXECUTES THE STEP INSTEAD OF READING IT

The first two versions of this file asserted on the TEXT of the workflow: does
it contain `gh pr comment`, does it mention the default branch. Adversarial
review found FOURTEEN mutations that left every one of those assertions green,
five of which permanently deadlock the workflow, and one of which made the step
announce the exact opposite of the truth by changing a single token
(`origin/$DEFAULT_BRANCH` -> `HEAD`). Two earlier rounds each fixed one instance
and missed the class: a substring grep is the wrong instrument for pinning shell
BEHAVIOUR, and no amount of tightening the greps changes that.

So the important tests here extract the step's `run:` body from the YAML and
EXECUTE it against a real throwaway git repository with a stubbed `gh`, then
assert on what actually happened: the exit status, what was printed, and whether
a comment was posted. Every one of those fourteen mutations is red against this,
because none of them survives being run.

The YAML-shape tests that remain guard what execution cannot see: that the step
exists at all, that it is wired to run when the action above it was skipped, and
that the job still has the name branch protection requires.

WHY THE STEP MUST NOT FAIL THE JOB

Failing deadlocks the workflow permanently: the only way to repair the file
would be a PR that the gate now blocks. A skipped review must be VISIBLE, not
BLOCKING. Every behavioural test below asserts exit 0 for that reason, including
the paths where the step cannot determine an answer.

KNOWN LIMITS, stated because a guard whose blind spot is undocumented is worse
than one with a narrow scope:

- These tests prove the step's shell behaves correctly. They cannot prove
  GitHub's runners invoke it, nor that GitHub still skips workflows for this
  reason. The behavioural half is proven by the PR that introduces this, which
  edits this very workflow and must therefore trigger the skip it detects.
- Step-level `if: always()` does NOT override the JOB-level `if:` guard. On a
  fork PR or a Dependabot PR that edits this workflow, the whole job is skipped
  and no notice posts. Those report `skipped` rather than `success`, so they are
  a different false green, and this step does not cover them.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.unit.conftest import sanitized_git_env

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / '.github' / 'workflows' / 'claude-review.yml'
SELF_PATH = '.github/workflows/claude-review.yml'


def _job():
    assert WORKFLOW.is_file(), f'workflow not found at {WORKFLOW}'
    doc = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
    job = (doc.get('jobs') or {}).get('claude-review')
    assert job, (
        "no `claude-review` job in the workflow. If it was renamed, the required "
        "status check on master was renamed with it -- update this test WITH the file"
    )
    return job


def _detection_step():
    """The step that must run even when the action above it was skipped.

    Matched on the `if` expression CONTAINING always(), not equalling it:
    `if: ${{ always() }}` and `if: always() && <cond>` are both legal GitHub and
    both were false failures under an equality match.
    """
    steps = [s for s in (_job().get('steps') or []) if 'always()' in str(s.get('if', ''))]
    assert len(steps) == 1, (
        'expected exactly one step whose `if:` contains always() in %s, found %d. '
        'That step is the skip detection: without it nothing executes on a run '
        'GitHub skipped by workflow validation, so the required check reports '
        'success with no review and no trace. Four PRs have already passed that '
        'way' % (SELF_PATH, len(steps))
    )
    return steps[0]


def _git(*args, cwd):
    return subprocess.run(
        ['git', *args], cwd=str(cwd), env=sanitized_git_env(),
        capture_output=True, text=True,
    )


def _step_env():
    """The step's declared `env:`, with GitHub-supplied expressions resolved.

    Literal values -- notably SELF, the path the guard watches -- are taken
    from the workflow ITSELF rather than supplied by the test. Review changed
    SELF to `.github/workflows/ci.yml`, which disables the guard permanently,
    and the earlier harness passed because it overrode SELF with the value it
    wanted. A test that supplies the thing under test proves nothing.
    """
    declared = (_detection_step().get('env') or {})
    for required in ('PR_NUMBER', 'DEFAULT_BRANCH', 'SELF', 'REVIEW_OUTCOME'):
        assert required in declared, (
            '%s is not declared in the detection step\'s env. The shell reads '
            'it, so deleting the declaration changes behaviour -- and under '
            '`set -u` an undeclared variable exits 1, which fails a REQUIRED '
            'check and deadlocks every future edit to this workflow' % required
        )
    supplied = {
        'PR_NUMBER': '4242',
        'DEFAULT_BRANCH': 'main',
        'REVIEW_OUTCOME': 'success',
    }
    out = {}
    for key, value in declared.items():
        text = str(value)
        # `${{ ... }}` is filled in by GitHub at run time; anything else is a
        # literal the workflow chose, and must be used as written.
        out[key] = supplied.get(key, '') if '${{' in text else text
    return out


def _drive_step(tmp_path, state, review_outcome='success', preexisting_notice=False):
    """Execute the detection step's shell against a real repo.

    `state`: 'same' (workflow matches the default branch), 'differs' (this PR
    edited it), 'new' (absent from the default branch), 'unfetchable'.
    Returns (exit_code, output, gh_body); gh_body is None if `gh pr comment`
    was never invoked, which is itself an assertion target.
    """
    run = str(_detection_step().get('run', ''))
    assert run.strip(), 'the detection step has no shell to run'

    env = sanitized_git_env()
    env.update(_step_env())
    env['REVIEW_OUTCOME'] = review_outcome
    if state == 'unfetchable':
        env['DEFAULT_BRANCH'] = 'no-such-branch'
    watched = env['SELF']

    origin = tmp_path / 'origin.git'
    work = tmp_path / 'work'
    _git('init', '-q', '--bare', str(origin), cwd=tmp_path)
    _git('clone', '-q', str(origin), str(work), cwd=tmp_path)
    _git('config', 'user.email', 't@example.com', cwd=work)
    _git('config', 'user.name', 'T', cwd=work)

    # The repo always contains the REAL workflow path. `watched` is whatever the
    # step says it watches, so pointing it elsewhere makes the guard blind and
    # the tests notice.
    real = work / SELF_PATH
    real.parent.mkdir(parents=True, exist_ok=True)
    if state != 'new':
        real.write_text('name: baseline\n', encoding='utf-8')
    else:
        (work / 'unrelated.txt').write_text('x\n', encoding='utf-8')
    _git('add', '-A', cwd=work)
    _git('commit', '-q', '-m', 'baseline', cwd=work)
    _git('branch', '-M', 'main', cwd=work)
    _git('push', '-q', '-u', 'origin', 'main', cwd=work)

    if state in ('differs', 'new'):
        real.write_text('name: edited by this PR\n', encoding='utf-8')
        _git('add', '-A', cwd=work)
        _git('commit', '-q', '-m', 'edit the workflow', cwd=work)

    bindir = tmp_path / 'bin'
    bindir.mkdir()
    record = tmp_path / 'gh-body.txt'
    existing = tmp_path / 'existing-comments.txt'
    existing.write_text(
        '<!-- claude-review-did-not-run -->\nan earlier notice\n'
        if preexisting_notice else 'unrelated chatter\n',
        encoding='utf-8',
    )
    shim = bindir / 'gh'
    shim.write_text(
        '#!/bin/sh\n'
        '# `gh pr view ... --json comments` feeds the duplicate check;\n'
        '# `gh pr comment --body X` records what would be posted.\n'
        'if [ "${1:-}" = "pr" ] && [ "${2:-}" = "view" ]; then\n'
        '  cat "' + str(existing) + '"\n'
        '  exit 0\n'
        'fi\n'
        'while [ $# -gt 0 ]; do\n'
        '  if [ "$1" = "--body" ]; then printf %s "$2" > "' + str(record) + '"; fi\n'
        '  shift\n'
        'done\n'
        'exit 0\n',
        encoding='utf-8',
    )
    shim.chmod(0o755)

    env['PATH'] = str(bindir) + os.pathsep + env.get('PATH', '')
    env['GH_TOKEN'] = 'stub-token-not-a-real-credential'

    proc = subprocess.run(
        ['sh', '-c', run], cwd=str(work), env=env, capture_output=True, text=True,
    )
    body = record.read_text(encoding='utf-8') if record.exists() else None
    return proc.returncode, proc.stdout + proc.stderr, body


needs_git = pytest.mark.skipif(
    shutil.which('git') is None or shutil.which('sh') is None,
    reason='needs git and sh to drive the step',
)


class TestTheStepExistsAndIsWired:
    """Shape, not behaviour: what executing the step cannot tell us."""

    def test_the_workflow_still_runs_the_review_action(self):
        uses = ' '.join(str(s.get('uses', '')) for s in (_job().get('steps') or []))
        assert 'claude-code-action' in uses, (
            'this workflow no longer runs claude-code-action; update this test '
            'WITH the file it guards'
        )

    def test_exactly_one_step_runs_when_the_action_was_skipped(self):
        assert _detection_step() is not None

    def test_the_job_itself_is_not_conditional(self):
        """A job skipped by a JOB-level `if:` runs ZERO steps, `if: always()`
        ones included. Measured on run 31556193805: conclusion "skipped",
        steps 0.

        The fork and Dependabot exclusion therefore belongs on the review STEP,
        never on the job. With it on the job the detection below can never fire
        for a fork or Dependabot pull request -- and dependabot.yml watches the
        github-actions ecosystem weekly, so Dependabot will open pull requests
        bumping `anthropics/claude-code-action` itself: a supply-chain change to
        the reviewer, merging on a green required check with nobody told.

        This is the one regression the behavioural tests cannot see, because
        they execute the step's shell and the shell is fine. Only the job's
        shape says whether it ever runs."""
        job_if = _job().get('if')
        assert not job_if, (
            'the claude-review JOB has a top-level `if:` (%r). A skipped job '
            'runs no steps at all, so the skip-detection step cannot fire for '
            'whichever pull requests this excludes -- and those are exactly the '
            'ones nobody reviews. Put the condition on the review STEP instead: '
            'the job then always runs, still reports a green required check, '
            'and the detection always fires' % job_if
        )

    def test_the_review_step_carries_the_fork_and_bot_exclusion(self):
        """Guards the other direction: moving the condition to the step is only
        safe if it is actually THERE. Dropping it entirely would run the
        reviewer on fork pull requests with this repo's token."""
        steps = _job().get('steps') or []
        review = [s for s in steps if 'claude-code-action' in str(s.get('uses', ''))]
        assert len(review) == 1, 'expected one claude-code-action step, got %d' % len(review)
        cond = str(review[0].get('if', ''))
        assert 'head.repo.full_name' in cond and 'dependabot' in cond, (
            'the review step no longer excludes fork and Dependabot pull '
            'requests (`if:` is %r). That condition was moved here from the job '
            'deliberately; losing it in the move would run the reviewer on '
            'untrusted fork pull requests' % cond
        )


@needs_git
class TestTheStepBehavesWhenRun:
    """The tests that matter. Fourteen mutations survived text assertions; none
    survives execution."""

    @staticmethod
    def _assert_says_no_review_happened(body):
        low = body.lower()
        assert 'did not run' in low or 'skip' in low, (
            'the notice never says the review did not happen, so it reads like '
            'any other automated comment. Body:\n%s' % body
        )
        assert 'green' in low and ('not' in low or 'does not' in low), (
            'the notice does not tell the reader that the green check is not a '
            'passed review, which is the single thing it exists to say. '
            'Body:\n%s' % body
        )
        assert 'other means' in low, (
            'the notice does not tell the reader what to DO. Body:\n%s' % body
        )

    def test_a_validation_skip_is_announced_and_posted(self, tmp_path):
        code, out, body = _drive_step(tmp_path, 'differs')
        assert code == 0, (
            'exited %d on a workflow-editing PR. Any non-zero exit fails a '
            'REQUIRED check, which deadlocks every future edit to this '
            'workflow: the only PR that could repair it would be blocked by '
            'this gate. Output:\n%s' % (code, out)
        )
        assert 'SKIP' in out.upper(), 'nothing logged about a skip:\n%s' % out
        assert body is not None, (
            'no comment posted for a skipped review. The job log already carries '
            'the reason a few hundred lines in, where nobody looks -- that is the '
            'status quo this step exists to change'
        )
        self._assert_says_no_review_happened(body)

    def test_the_step_being_skipped_by_its_own_gate_is_also_reported(self, tmp_path):
        """The population that matters most. dependabot.yml watches the
        github-actions ecosystem weekly, so Dependabot will open PRs bumping
        `anthropics/claude-code-action` -- changing the reviewer itself, on a PR
        the reviewer does not review."""
        code, out, body = _drive_step(
            tmp_path, 'same', review_outcome='skipped',
        )
        assert code == 0, 'exited %d:\n%s' % (code, out)
        assert body is not None, (
            'the review step was skipped by its own condition (fork or '
            'Dependabot) and NOTHING was reported. The workflow file matches the '
            'default branch, so the validation check stays silent -- if this path '
            'is not covered, those PRs get a green required check, no review, and '
            'no notice'
        )
        self._assert_says_no_review_happened(body)
        assert 'dependabot' in body.lower() or 'fork' in body.lower(), (
            'the notice does not say WHY the review did not run, so the reader '
            'cannot tell this from a validation skip. Body:\n%s' % body
        )

    def test_an_ordinary_pull_request_posts_nothing(self, tmp_path):
        code, out, body = _drive_step(tmp_path, 'same')
        assert code == 0, 'exited %d on an ordinary PR:\n%s' % (code, out)
        assert body is None, (
            'a notice was posted on a PR where the review DID run. Every clean '
            'PR would carry a false warning, which trains people to scroll past '
            'the real one. Body:\n%s' % body
        )

    def test_a_workflow_absent_from_the_default_branch_is_reported(self, tmp_path):
        """A brand-new workflow is not on the default branch at all, and the
        action skips that case too ("must EXIST and have identical content"), so
        silence would be wrong."""
        code, out, body = _drive_step(tmp_path, 'new')
        assert code == 0, 'exited %d for a new workflow:\n%s' % (code, out)
        assert body is not None, (
            'a workflow absent from the default branch posted no notice'
        )

    def test_the_notice_is_posted_once_per_pull_request_not_once_per_push(self, tmp_path):
        """The reviewer's own summaries show the failure mode: #277 and #279 each
        accumulated five comments. Repeating the one notice that must not be
        ignored is how it gets ignored."""
        code, out, body = _drive_step(
            tmp_path, 'differs', preexisting_notice=True,
        )
        assert code == 0, 'exited %d:\n%s' % (code, out)
        assert body is None, (
            'a second identical notice was posted although one is already on the '
            'pull request. Six pushes would mean six copies. Body:\n%s' % body
        )

    def test_an_unknown_answer_says_so_and_does_not_claim_success(self, tmp_path):
        code, out, body = _drive_step(tmp_path, 'unfetchable')
        assert code == 0, (
            'exited %d when the default branch could not be fetched. An '
            'environmental failure must not fail a required check:\n%s' % (code, out)
        )
        low = out.lower()
        assert 'unknown' in low or 'unproven' in low, (
            'when it cannot tell whether the review ran, the step must SAY so. '
            'Silence is indistinguishable from "the review ran", which is the '
            'defect this file exists to remove. Output:\n%s' % out
        )
        assert 'was not skipped' not in low, (
            'claimed the review was not skipped when it could not determine '
            'that. Output:\n%s' % out
        )
