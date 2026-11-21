"""The local gate retries a browser test once and lists what only passed on retry.

Owner decision 2026-11-21 ("fix plus auto-retry"): scripts/verify.sh retries a
failed Playwright test ONCE and does not fail on a test that passed on the
retry, but prints every such test so none hides in a green gate. CI is
unchanged and strict: playwright.config.ts keeps `retries: 2` under CI and
every ci.yml invocation keeps `--fail-on-flaky-tests`.

What each guard here protects:
  - retry count: 0 would make the decision a no-op, 2+ would hide a test that
    needs three goes;
  - no `--fail-on-flaky-tests` locally: with a retry it would fail the gate on
    exactly the tests the decision says to tolerate and list;
  - JSON per invocation plus an explicit file list: the flaky list must come
    from Playwright's result data, and a glob would turn an invocation that
    wrote nothing into a silent "none flaky";
  - the list printed twice: at the end of step 7 and in the final summary.
"""
import re
from pathlib import Path

import pytest

from tests.unit.test_ci_required_contexts import flaky_problems, playwright_commands

yaml = pytest.importorskip('yaml')

REPO = Path(__file__).resolve().parents[2]
VERIFY = REPO / 'scripts' / 'verify.sh'
CI_WORKFLOW = REPO / '.github' / 'workflows' / 'ci.yml'
PLAYWRIGHT_CONFIG = REPO / 'playwright.config.ts'


def _verify_text() -> str:
    return VERIFY.read_text(encoding='utf-8')


def _code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith('#')]


def retry_problems(script_text: str) -> list[str]:
    """Playwright commands that do not retry exactly once, or that fail on flaky."""
    commands = playwright_commands(script_text)
    if not commands:
        return ['no Playwright invocations found; the guard would be vacuous']
    return [
        command
        for command in commands
        if re.findall(r'--retries\S*', command) != ['--retries=1']
        or '--fail-on-flaky-tests' in command
    ]


def test_every_local_playwright_invocation_retries_exactly_once():
    problems = retry_problems(_verify_text())
    assert not problems, 'these verify.sh Playwright invocations do not retry once: %s' % problems


def test_no_local_invocation_fails_the_gate_on_a_flaky_test():
    """The flag would defeat the decision, so its absence is the requirement."""
    flagged = [c for c in playwright_commands(_verify_text()) if '--fail-on-flaky-tests' in c]
    assert not flagged


RETRY_CASES = [
    ('once', 'npx playwright test --project=a --retries=1', True),
    ('none', 'npx playwright test --project=a', False),
    ('twice', 'npx playwright test --project=a --retries=2', False),
    ('zero', 'npx playwright test --project=a --retries=0', False),
    ('space form', 'npx playwright test --project=a --retries 1', False),
    ('once and again', 'npx playwright test --project=a --retries=1 --retries=1', False),
    ('with fail-on-flaky', 'npx playwright test --project=a --retries=1 --fail-on-flaky-tests', False),
    ('second command lacks it', 'npx playwright test --project=a --retries=1 && npx playwright test --project=b', False),
    ('only in a comment', 'npx playwright test --project=a # --retries=1', False),
]


@pytest.mark.parametrize('script,ok', [(c[1], c[2]) for c in RETRY_CASES], ids=[c[0] for c in RETRY_CASES])
def test_the_retry_guard_can_actually_fail(script, ok):
    assert (not retry_problems(script)) is ok


def _json_outputs(script_text: str) -> list[str]:
    return [
        match.group(1)
        for command in playwright_commands(script_text)
        if (match := re.search(r'PLAYWRIGHT_JSON_OUTPUT_NAME=(\S+)', command))
    ]


def test_every_local_invocation_writes_its_own_json_report():
    text = _verify_text()
    commands = playwright_commands(text)
    outputs = _json_outputs(text)
    assert len(outputs) == len(commands) == 4
    assert len(set(outputs)) == 4, 'two invocations would overwrite each other: %s' % outputs
    for command in commands:
        reporters = re.search(r'--reporter=(\S+)', command)
        assert reporters
        assert 'json' in reporters.group(1).split(',')


def _summary_commands(text: str) -> list[str]:
    return [line for line in _code_lines(text) if 'scripts/e2e_flaky_summary.py' in line]


def test_the_flaky_summary_is_run_on_exactly_the_four_reports():
    text = _verify_text()
    summaries = _summary_commands(text)
    assert len(summaries) == 1
    for output in _json_outputs(text):
        assert output in summaries[0], '%s is not passed to the summary' % output
    assert '*' not in summaries[0], 'a glob turns a missing report into a silent "none flaky"'


def test_the_flaky_list_is_printed_after_step_7_and_in_the_final_summary():
    """The report is captured once and printed in two places: the end of step 7,
    and after the final 'All checks passed' banner so it is the last thing read."""
    text = _verify_text()
    prints = [line for line in _code_lines(text) if re.search(r'printf .*\$\{?FLAKY_REPORT', line)]
    assert len(prints) == 2
    step7_end = text.index('step "info: security lint')
    final = text.index('All checks passed')
    positions = [text.index(line) for line in prints]
    assert positions[0] < step7_end, 'the first listing belongs at the end of step 7'
    assert positions[1] > final, 'the second listing belongs after the final banner'


# ---- CI stays strict -------------------------------------------------------

def test_the_config_still_retries_twice_only_under_ci():
    """`--fail-on-flaky-tests` only means something if CI really retries, and the
    local retry must come from verify.sh alone so a plain local run is unchanged."""
    config = PLAYWRIGHT_CONFIG.read_text(encoding='utf-8')
    assert re.search(r'^\s*retries:\s*process\.env\.CI \? 2 : 0,', config, re.M)


def test_ci_overrides_neither_the_retry_count_nor_the_flaky_flag():
    ci = yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8'))
    run_text = '\n'.join(
        str(step.get('run', ''))
        for job in ci['jobs'].values()
        for step in job.get('steps', [])
    )
    assert playwright_commands(run_text), 'no CI Playwright invocations found'
    assert '--retries' not in run_text
    assert flaky_problems(run_text) == []
