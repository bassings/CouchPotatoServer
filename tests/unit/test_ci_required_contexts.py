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
import json
import re
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


NO_INVOCATIONS = 'no Playwright invocations found; the guard would be vacuous'


def _playwright_npm_scripts() -> set[str]:
    """Names of package.json scripts that reach Playwright, directly or through
    another script. Derived, so a new script cannot slip past by being new."""
    scripts = json.loads((REPO / 'package.json').read_text(encoding='utf-8'))['scripts']
    # `_comment:*` keys are prose that happens to mention Playwright, not scripts.
    scripts = {
        name: body
        for name, body in scripts.items()
        if isinstance(body, str) and not name.startswith('_')
    }
    names = {name for name, body in scripts.items() if 'playwright test' in body}
    changed = True
    while changed:
        changed = False
        for name, body in scripts.items():
            if name in names:
                continue
            called = re.findall(r'npm (?:run(?:-script)? )?([\w:.-]+)', body)
            if any(c in names for c in called):
                names.add(name)
                changed = True
    return names


def playwright_commands(script_text: str) -> list[str]:
    """The shell command segments in a script that run Playwright.

    Backslash continuations are joined first, so a flag on a continuation line
    belongs to its command; whole-line and trailing comments are dropped, so a
    flag that only appears in prose does not count. Each logical line is then
    split on `&&`, `||`, `;` and `|`, and every segment is judged on its own, so
    `cmd --flag || cmd` cannot hide an unflagged retry behind a flagged first
    half. A segment is selected if it runs `playwright test`, runs an npm script
    that package.json maps to Playwright, or mentions `--project` (so nothing a
    line-based guard saw is lost, whatever form `--project` takes).
    """
    npm_names = _playwright_npm_scripts()
    joined = re.sub(r'\\[ \t]*\n', ' ', script_text)
    commands = []
    for line in joined.splitlines():
        code = re.sub(r'(^|\s)#.*$', '', line)
        for segment in re.split(r'&&|\|\||;|\|', code):
            segment = segment.strip()
            npm_call = re.match(r'npm (?:run(?:-script)? )?([\w:.-]+)', segment)
            if (
                'playwright test' in segment
                or '--project' in segment
                or (npm_call and npm_call.group(1) in npm_names)
            ):
                commands.append(segment)
    return commands


def trace_problems(script_text: str) -> list[str]:
    """Commands that do not record a trace on failure, or contradict that."""
    commands = playwright_commands(script_text)
    if not commands:
        return [NO_INVOCATIONS]
    return [
        command
        for command in commands
        if set(re.findall(r'--trace\S*', command)) != {'--trace=retain-on-failure'}
    ]


def flaky_problems(script_text: str) -> list[str]:
    """Commands that can retry a failure into green."""
    commands = playwright_commands(script_text)
    if not commands:
        return [NO_INVOCATIONS]
    return [c for c in commands if '--fail-on-flaky-tests' not in c]


def test_the_local_gate_keeps_fail_on_flaky_tests_too(ci_workflow):
    """`scripts/verify.sh` is the gate the pre-push hook runs, so it must not
    drift from CI: a local run that retries into green is how untested code
    reaches a push."""
    verify = (REPO / 'scripts' / 'verify.sh').read_text(encoding='utf-8')
    problems = flaky_problems(verify)
    assert not problems, (
        'these verify.sh Playwright invocations can retry a failure into green: %s'
        % problems
    )


def test_the_local_gate_retains_a_trace_for_every_failed_e2e_test():
    """Locally `retries` is 0, so the config's `trace: 'on-first-retry'` never
    records anything and a one-off local failure leaves no evidence behind.
    `--trace=retain-on-failure` on each invocation is what keeps one."""
    verify = (REPO / 'scripts' / 'verify.sh').read_text(encoding='utf-8')
    problems = trace_problems(verify)
    assert not problems, (
        'these verify.sh Playwright invocations record no trace on a local failure: %s'
        % problems
    )


def test_the_real_gate_has_exactly_the_four_playwright_commands():
    """Pins the selection itself: a selector that quietly matched more or fewer
    commands would make both guards above vacuous or noisy."""
    verify = (REPO / 'scripts' / 'verify.sh').read_text(encoding='utf-8')
    projects = [re.search(r'--project=(\S+)', c).group(1) for c in playwright_commands(verify)]
    assert projects == ['chromium', 'isolation', 'mobile-chrome', 'accessibility']


T = '--trace=retain-on-failure'
F = '--fail-on-flaky-tests'

# Each shape slipped past an earlier version of the guard (or the old line-based
# one). `ok` is whether the script is acceptable to that guard.
TRACE_GUARD_CASES = [
    ('plain', f'npx playwright test --project=a {T}', True),
    ('continued', f'npx playwright test --project=a \\\n  {T} \\\n  || fail x', True),
    ('flag on a continuation line only', f'npx playwright test --project=a \\\n  {T}', True),
    ('missing', f'npx playwright test --project=a {F}', False),
    ('flag only in a trailing comment', f'npx playwright test --project=a # TODO: {T}', False),
    ('flag only in a comment line, real invocation without it', f'# npx playwright test {T}\nnpx playwright test --project=a', False),
    ('space form of --project', 'npx playwright test --project mobile-chrome', False),
    ('no --project at all', 'npx playwright test', False),
    ('contradicted by a later --trace', f'npx playwright test --project=a {T} --trace=off', False),
    ('contradicted by an earlier --trace', f'npx playwright test --trace=off {T}', False),
    ('space-form trace value', 'npx playwright test --trace off', False),
    ('continuation hides a bad invocation', 'npx playwright test --project=a \\\n  --workers=2', False),
    ('shell retry into green via ||', f'npx playwright test --project=a {T} {F} \\\n  || npx playwright test --project=a || fail x', False),
    ('npm script with --project', 'npm run test:e2e -- --project=mobile-chrome', False),
    ('npm script with no --project', 'npm run test:e2e', False),
    ('npm script reaching Playwright through another script', 'npm test', False),
    ('two commands on one line, only the first has it', f'npx playwright test --project=a {T} && npx playwright test --project=b', False),
    ('two commands on one line, both have it', f'npx playwright test --project=a {T} && npx playwright test --project=b {T}', True),
    ('wrapper that passes --project without saying playwright', f'./run-e2e.sh --project=a {F}', False),
    ('unrelated npm script', 'npm run lint', False),
]

FLAKY_GUARD_CASES = [
    ('plain', f'npx playwright test --project=a {F}', True),
    ('continued', f'npx playwright test --project=a \\\n  {F} \\\n  || fail x', True),
    ('missing', f'npx playwright test --project=a {T}', False),
    ('flag only in a trailing comment', f'npx playwright test --project=a # {F}', False),
    ('flag only in a comment line, real invocation without it', f'# npx playwright test {F}\nnpx playwright test --project=a', False),
    ('missing in the second segment', f'npx playwright test --project=a {F} && npx playwright test --project=b', False),
    ('shell retry into green via ||', f'npx playwright test --project=a {F} || npx playwright test --project=a', False),
    ('npm script form', 'npm run test:e2e -- --project=mobile-chrome', False),
    ('space form of --project', 'npx playwright test --project mobile-chrome', False),
    ('no --project at all', 'npx playwright test', False),
    ('wrapper that passes --project without saying playwright', f'./run-e2e.sh --project=a {T}', False),
]


def _ids(cases):
    return [c[0] for c in cases]


@pytest.mark.parametrize('script,ok', [(c[1], c[2]) for c in TRACE_GUARD_CASES], ids=_ids(TRACE_GUARD_CASES))
def test_the_trace_guard_can_actually_fail(script, ok):
    """Feed the matcher the shapes that fooled it, without mutating verify.sh."""
    assert (not trace_problems(script)) is ok


@pytest.mark.parametrize('script,ok', [(c[1], c[2]) for c in FLAKY_GUARD_CASES], ids=_ids(FLAKY_GUARD_CASES))
def test_the_flaky_guard_can_actually_fail(script, ok):
    assert (not flaky_problems(script)) is ok


@pytest.mark.parametrize(
    'script',
    [c[1] for c in TRACE_GUARD_CASES + FLAKY_GUARD_CASES if c[0] != 'unrelated npm script'],
)
def test_every_case_script_is_selected_rather_than_ignored(script):
    """A not-ok case that selects nothing is rejected as "vacuous", which looks
    like the guard working while testing nothing about the shape it names."""
    assert playwright_commands(script) != []


@pytest.mark.parametrize('guard', [trace_problems, flaky_problems])
def test_a_script_with_only_comments_reports_no_invocations(guard):
    """Proves comment stripping is load-bearing: this script mentions a full
    Playwright command and both flags, but only in prose."""
    script = f'# npx playwright test --project=a {T} {F}\necho done  # npx playwright test {T}\n'
    assert guard(script) == [NO_INVOCATIONS]


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
