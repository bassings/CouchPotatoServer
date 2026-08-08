"""Every branch-protection required context must still be published by a job.

AC-QA-65 of specs/CI-003-fast-gate.md, generalised from the one context that
change touched to all eight this workflow owns.

A required status check is matched by NAME. Branch protection has no idea which
workflow or job is meant to produce it, so renaming a job -- or deleting it, or
folding it into another one -- does not fail anything at the time. It leaves
`master` waiting forever for a context nothing publishes, and every subsequent
PR is unmergeable until somebody with admin rights notices and edits branch
protection by hand.

This is a live hazard on this repo, not a theoretical one:

  - CI-003 removes `needs: ui-e2e-tests` from `accessibility` and was one step
    away from the larger "win" of folding the accessibility project INTO
    ui-e2e-tests, which would have deleted the job publishing `accessibility`.
  - `ci.yml:88-92` already carries a hand-written warning saying exactly this
    about the `secrets` job. A comment asking the next person to remember is
    weaker than a test (CLAUDE.md rule 9), so this is that test.

Scope: the eight contexts produced by ci.yml. The other four in the required set
(`claude-review`, `Analyze (python)`, `Analyze (javascript)`,
`dependency-review`) come from other workflows and are out of this file's reach;
they are listed below so the omission is visible rather than silent.

The reported check-run name is the job's `name:` when it has one, and the job
key otherwise -- that fallback is why a bare rename of a key is enough to break
this, and why the test resolves the name the same way GitHub does.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip('yaml')

REPO = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO / '.github' / 'workflows' / 'ci.yml'

# Verified against branch protection on master, 2026-08-08. The full required
# set is these eight plus claude-review, Analyze (python), Analyze (javascript)
# and dependency-review, which other workflows publish.
REQUIRED_CONTEXTS_FROM_CI = frozenset({
    'lint',
    'conformance',
    'secrets',
    'test-summary',
    'ui-unit-tests',
    'ui-e2e-tests',
    'accessibility',
    'docker',
})


def published_check_names(workflow: dict) -> set:
    """The check-run names a workflow publishes, resolved as GitHub resolves them."""
    return {
        definition.get('name', key) if isinstance(definition, dict) else key
        for key, definition in workflow['jobs'].items()
    }


@pytest.fixture(scope='module')
def ci_workflow() -> dict:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))


def test_every_required_context_is_published_by_a_job(ci_workflow):
    missing = REQUIRED_CONTEXTS_FROM_CI - published_check_names(ci_workflow)
    assert not missing, (
        'These contexts are REQUIRED by branch protection on master but no job '
        'in ci.yml publishes them: %s.\n'
        'A required context nothing publishes blocks every PR forever, waiting '
        'for a check that never reports. Either restore the job name, or remove '
        'the context from branch protection IN THE SAME CHANGE.' % sorted(missing)
    )


def test_the_accessibility_gate_still_runs_the_accessibility_project(ci_workflow):
    """Publishing the context is necessary but not sufficient: it must still run.

    A job kept only to satisfy branch protection, with its test step dropped or
    made conditional, is a green light attached to nothing -- the exact
    false-green shape CLAUDE.md rule 10 is about.
    """
    steps = ci_workflow['jobs']['accessibility']['steps']
    runners = [s for s in steps if '--project=accessibility' in str(s.get('run', ''))]

    assert runners, 'the accessibility job no longer runs --project=accessibility'
    for step in runners:
        assert 'if' not in step, (
            'the accessibility run step is conditional (%r), so the job can '
            'report success having executed no accessibility tests' % step['if']
        )
        assert '--fail-on-flaky-tests' in step['run'], (
            'the accessibility job dropped --fail-on-flaky-tests, so a test that '
            'fails once and passes on retry reports green (AC-A11Y-4)'
        )


def test_every_playwright_invocation_in_ci_keeps_fail_on_flaky_tests(ci_workflow):
    """AC-A11Y-4 names the whole file, not just the accessibility job.

    Without this, a flaky small-screen test could later be retried quietly
    into green -- and phone width is where this project's first real a11y
    regression was found (a 441px restore picker on a 393px device).
    """
    # Per INVOCATION, not per step. A `run:` block is often multi-line --
    # ui-e2e-tests' "Run E2E tests" step carries two `--project=` lines today --
    # so checking the whole block for the substring passes as soon as ANY line
    # has the flag. A third invocation added to that same step without it would
    # not have been caught: a guard vacuous against the one change it exists to
    # catch. Matches the per-line shape of the verify.sh test below.
    unguarded = [
        '%s: %s' % (job_name, line.strip())
        for job_name, job in ci_workflow['jobs'].items()
        for step in job.get('steps', [])
        for line in str(step.get('run', '')).splitlines()
        if '--project=' in line
        and not line.lstrip().startswith('#')
        and '--fail-on-flaky-tests' not in line
    ]
    assert not unguarded, (
        'these CI Playwright invocations can retry a failure into green: %s' % unguarded
    )


def test_the_local_gate_keeps_fail_on_flaky_tests_too(ci_workflow):
    """`scripts/verify.sh` is the gate the pre-push hook runs, so it must not
    drift from CI: a local run that retries into green is how untested code
    reaches a push."""
    verify = (REPO / 'scripts' / 'verify.sh').read_text(encoding='utf-8')
    unguarded = [
        line.strip()
        for line in verify.splitlines()
        if '--project=' in line
        and not line.lstrip().startswith('#')  # prose, not an invocation
        and '--fail-on-flaky-tests' not in line
    ]
    assert not unguarded, (
        'these verify.sh Playwright invocations can retry a failure into green: %s'
        % unguarded
    )


def test_the_guard_can_actually_fail():
    """Prove the matcher is not vacuous, without mutating the real workflow.

    The positive tests above pass on a correct file; this pins that they would
    NOT pass on a broken one. Without it, a `published_check_names` that
    returned every string imaginable would look just as green.
    """
    renamed = {'jobs': {'a11y': {'steps': []}, 'lint': {'steps': []}}}
    assert 'accessibility' not in published_check_names(renamed)

    explicit_name = {'jobs': {'whatever': {'name': 'accessibility', 'steps': []}}}
    assert 'accessibility' in published_check_names(explicit_name)
