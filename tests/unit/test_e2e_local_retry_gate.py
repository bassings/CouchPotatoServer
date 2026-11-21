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
  - the list printed twice: at the end of step 7 and in the final summary;
  - and, because text and position cannot show that a line DOES anything,
    `test_step7_*` below run the real `scripts/verify.sh --e2e-only` against a
    stub `npx` and read what it prints and how it exits.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.test_ci_required_contexts import flaky_problems, playwright_commands
from tests.unit.test_e2e_flaky_summary import make_report

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


# ---- Step 7 RUN, not read ----------------------------------------------------
#
# The text guards above cannot tell a summary line that runs from one turned into
# an `echo`, an assignment moved below its prints, a print moved before any test,
# or `|| fail` softened to `|| true`. These run the real step 7 (`--e2e-only`
# skips steps 0-6) with a stub `npx` first on PATH. The stub writes a real-shaped
# report to PLAYWRIGHT_JSON_OUTPUT_NAME (flaky in one project) and can fail one.

BANNER = 'All checks passed'
SEAM_BANNER = 'ONLY step 7 ran'   # what --e2e-only prints instead of the full-gate banner
LISTING = 'tests/e2e/settings.spec.ts:5'
PROJECTS = ['chromium', 'isolation', 'mobile-chrome', 'accessibility']

STUB_NPX = r"""#!/bin/bash
project=$(echo "$*" | sed -n 's/.*--project=\([^ ]*\).*/\1/p')
[ -z "$project" ] && exit 0                     # `npx playwright install chromium`
if [ "$project" = "$STUB_FLAKY_PROJECT" ]; then
  cp "$STUB_REPORT" "$PLAYWRIGHT_JSON_OUTPUT_NAME"
else
  echo '{"suites": []}' > "$PLAYWRIGHT_JSON_OUTPUT_NAME"
fi
echo "STUB-RAN $project"
[ "$project" = "$STUB_FAIL_PROJECT" ] && exit 1
exit 0
"""


def run_step7(tmp_path, flaky='chromium', fail=''):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    npx = bin_dir / 'npx'
    npx.write_text(STUB_NPX, encoding='utf-8')
    npx.chmod(0o755)
    report = tmp_path / 'flaky.json'
    report.write_text(json.dumps(make_report()), encoding='utf-8')
    env = dict(os.environ, PATH=f'{bin_dir}{os.pathsep}{os.environ["PATH"]}', PYTHON=sys.executable,
               STUB_REPORT=str(report), STUB_FLAKY_PROJECT=flaky, STUB_FAIL_PROJECT=fail)
    result = subprocess.run(['bash', str(VERIFY), '--e2e-only'], cwd=REPO, env=env,
                            capture_output=True, text=True, timeout=120, check=False)
    return result.returncode, result.stdout + result.stderr


def test_step7_green_run_lists_the_flaky_test_after_step_7_and_after_the_banner(tmp_path):
    code, out = run_step7(tmp_path)
    assert code == 0, out
    assert out.count(LISTING) == 2
    assert out.rindex('STUB-RAN') < out.index(LISTING), 'the first listing was printed before the tests ran'
    assert out.index(LISTING) < out.index(SEAM_BANNER) < out.rindex(LISTING)


def test_step7_green_run_with_nothing_flaky_says_so_twice(tmp_path):
    code, out = run_step7(tmp_path, flaky='none')
    assert code == 0, out
    assert out.count('No flaky E2E tests') == 2


def test_step7_only_run_never_claims_the_full_gate_passed(tmp_path):
    """--e2e-only is a test seam. Its summary must say steps 0-6 were NOT run and
    must not carry the full gate's all-clear, which would be a false green."""
    code, out = run_step7(tmp_path)
    assert code == 0, out
    assert BANNER not in out
    assert 'safe to open a PR' not in out
    assert SEAM_BANNER in out
    assert 'steps 0-6 were NOT run' in out


def test_the_full_gate_banner_is_only_reachable_when_e2e_only_is_off():
    """Walk back from the banner: its nearest `else` must belong to an
    `if [[ "$E2E_ONLY" -eq 1 ]]`, with no `fi` between that `if` and the banner."""
    lines = _verify_text().splitlines()
    banner = next(i for i, line in enumerate(lines) if BANNER in line and not line.lstrip().startswith('#'))
    els = max(i for i in range(banner) if lines[i].strip() == 'else')
    cond = max(i for i in range(els) if re.match(r'\s*if \[\[ "\$E2E_ONLY" -eq 1 \]\]; then', lines[i]))
    assert not any(lines[i].strip() == 'fi' for i in range(cond, banner))


@pytest.mark.parametrize('path', ['.githooks/pre-push', 'Makefile'])
def test_nothing_that_gates_a_push_passes_e2e_only(path):
    assert '--e2e-only' not in (REPO / path).read_text(encoding='utf-8')


@pytest.mark.parametrize('project', PROJECTS)
def test_step7_a_failed_invocation_fails_the_gate_with_no_banner(tmp_path, project):
    code, out = run_step7(tmp_path, fail=project)
    assert code != 0
    assert BANNER not in out


def test_step7_red_gate_still_lists_a_test_that_passed_only_on_retry_earlier(tmp_path):
    """Flaky in chromium, hard failure in accessibility: the listing is shown once
    (from the EXIT trap, before the reports are removed) and the exit stays non-zero."""
    code, out = run_step7(tmp_path, flaky='chromium', fail='accessibility')
    assert code != 0
    assert out.count(LISTING) == 1
    assert BANNER not in out
    assert 'Accessibility tests failed' in out


def test_step7_red_gate_reports_invocations_that_never_ran_as_unknown(tmp_path):
    code, out = run_step7(tmp_path, flaky='none', fail='chromium')
    assert code != 0
    assert out.count('UNKNOWN') == 3
    assert 'No flaky' not in out
