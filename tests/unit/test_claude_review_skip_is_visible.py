"""`claude-review` is a REQUIRED check that can pass without running.

GitHub refuses to run a workflow from a pull request that modifies that
workflow's own file: "the workflow file must exist and have identical content
to the version on the repository's default branch". `claude-review` is a
required status check, so on any PR editing `.github/workflows/claude-review.yml`
the check reports success while the reviewer never executed.

Measured, four for four: #129, #132, #149 and #281 each edit this file and each
carries ZERO `claude[bot]` comments. Two of those were themselves fixes to the
reviewer, so the changes least able to afford going unreviewed are precisely the
ones that did. The reason sits in the job log 568 lines in, where nobody looks,
and a skipped run takes 13-17 seconds against about four minutes for a real
review -- the cheapest available tell, and nothing reads it.

WHY THIS IS NOT FIXED BY FAILING THE JOB

Failing deadlocks the workflow permanently: the only way to repair the file
would be a PR that the gate now blocks. The requirement is that a SKIPPED
review must not be indistinguishable from a CLEAN one, which is a reporting
problem, not a gating one.

WHY THIS ASSERTS ON ONE STEP AND NOT ON THE FILE

An earlier draft of this file checked `'gh pr comment' in text`. That passed
before the fix existed, because the string already appears in the action's
`--allowedTools` list. It was an incidentally-passing test: it would have gone
green with no protection whatsoever, which is the failure mode this repo's
standards name explicitly. Every assertion below is therefore scoped to the
detection STEP, located by its `if: always()` guard, so removing that step
fails the suite rather than quietly satisfying it.

KNOWN LIMIT, stated because a guard whose blind spot is undocumented is worse
than one with a narrow scope: this reads the workflow FILE. It proves the step
is present and shaped to run; it cannot prove GitHub's runners behave as
expected. The behavioural half is proven by the PR that introduces it, which
edits this very workflow and must therefore trigger the skip it detects.
"""
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / '.github' / 'workflows' / 'claude-review.yml'


def _steps():
    """Every step of the claude-review job, as dicts."""
    assert WORKFLOW.is_file(), f'workflow not found at {WORKFLOW}'
    doc = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
    jobs = doc.get('jobs') or {}
    job = jobs.get('claude-review')
    assert job, (
        "no `claude-review` job in the workflow. If it was renamed, the "
        "required status check on master was renamed with it -- update this "
        "test WITH the file"
    )
    return job.get('steps') or []


def _detection_step():
    """The step that must run even when the action above it was skipped."""
    always = [s for s in _steps() if str(s.get('if', '')).strip() == 'always()']
    assert len(always) == 1, (
        'expected exactly one `if: always()` step in claude-review.yml, found '
        '%d. That step is the skip detection: without it, nothing executes on '
        'a run GitHub skipped by workflow validation, so the required check '
        'reports success with no review and no trace. Four PRs have already '
        'passed that way' % len(always)
    )
    return always[0]


class TestTheJobIsStillTheOneWeGuard:

    def test_the_workflow_runs_the_review_action(self):
        """Guards the guard: if this is no longer the workflow that runs the
        reviewer, every assertion below is about the wrong file."""
        uses = ' '.join(str(s.get('uses', '')) for s in _steps())
        assert 'claude-code-action' in uses, (
            'this workflow no longer runs claude-code-action; update this test '
            'WITH the file it guards'
        )


class TestTheSkipIsDetected:

    def test_a_step_runs_even_when_the_review_action_is_skipped(self):
        assert _detection_step() is not None

    def test_the_detection_compares_against_the_default_branch(self):
        """GitHub's own rule for skipping is content equality with the default
        branch, so that is what the detection must test. The 13-17s duration
        tell would rot the first time the reviewer got faster or slower."""
        step = _detection_step()
        blob = yaml.safe_dump(step)
        assert 'default_branch' in blob, (
            'the detection step never references the default branch. GitHub '
            'skips precisely when this file differs from the default-branch '
            'copy, so comparing against it is the only non-heuristic test'
        )

    def test_the_detection_reports_where_a_human_reads_it(self):
        """Scoped to the step, not the file: `gh pr comment` also appears in
        the action's --allowedTools, so a file-wide check passes with no
        protection at all."""
        run = str(_detection_step().get('run', ''))
        assert 'gh pr comment' in run or 'gh api' in run, (
            'the detection step posts nothing. The job log already carries the '
            'reason 568 lines in, where nobody looks -- that is the status quo '
            'this guard exists to change'
        )

    def test_the_detection_says_the_review_was_skipped(self):
        """The message must name the condition. "check the logs" reproduces the
        defect: it is indistinguishable from a clean review to anyone skimming."""
        run = str(_detection_step().get('run', '')).lower()
        assert 'skip' in run, (
            'the detection step never says the review was SKIPPED. A message '
            'that does not name the condition leaves a false green looking '
            'exactly like a real one'
        )

    def test_the_detection_does_not_fail_the_job(self):
        """A skipped review must be VISIBLE, not blocking. Failing deadlocks
        every future edit to this workflow, because the only way to fix the
        file would be a PR this gate now blocks. Review raised this
        explicitly, and it is the constraint most likely to be lost in a later
        "tighten the gate" change."""
        run = str(_detection_step().get('run', ''))
        offenders = [
            ln.strip() for ln in run.splitlines()
            if ln.strip() in ('exit 1', 'exit 2') or ln.strip().startswith('exit 1 ')
        ]
        assert not offenders, (
            'the detection step exits non-zero (%r). That deadlocks every '
            'future edit to this workflow: the fix would need a PR that this '
            'gate now blocks' % offenders
        )
        assert str(_detection_step().get('continue-on-error', '')) != 'true', (
            'continue-on-error on the detection step hides its own failures, '
            'so a broken detector would be silent -- the same class of defect '
            'this step exists to remove'
        )
