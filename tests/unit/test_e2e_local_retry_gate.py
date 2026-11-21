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
import signal
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


def test_the_completion_marker_is_the_last_statement_of_the_script():
    code_lines = [line for line in _verify_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
    assert re.fullmatch(r'GATE_DONE=1(\s+#.*)?', code_lines[-1]), code_lines[-1]


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
    assert SEAM_BANNER not in out, 'a red run printed the seam warning banner as if it had finished'


def test_step7_red_gate_still_lists_a_test_that_passed_only_on_retry_earlier(tmp_path):
    """Flaky in chromium, hard failure in accessibility: the listing is shown once
    (from the EXIT trap, before the reports are removed) and the exit stays non-zero."""
    code, out = run_step7(tmp_path, flaky='chromium', fail='accessibility')
    assert code != 0
    assert out.count(LISTING) == 1
    assert BANNER not in out
    assert SEAM_BANNER not in out, 'a red run printed the seam warning banner as if it had finished'
    assert 'Accessibility tests failed' in out


def test_step7_red_gate_reports_invocations_that_never_ran_as_unknown(tmp_path):
    code, out = run_step7(tmp_path, flaky='none', fail='chromium')
    assert code != 0
    assert out.count('UNKNOWN') == 3
    assert 'No flaky' not in out


def test_step7_the_summary_script_itself_failing_is_reported_not_read_as_none(tmp_path):
    code, out, _ = run_gate(tmp_path, ['--e2e-only'], summary_fails=True)
    assert code == 0, out
    assert out.count('UNKNOWN: the flaky-test summary itself failed to run.') == 2
    assert 'No flaky' not in out


# ---- The normal gate still runs steps 0-6 -----------------------------------
#
# Fakes for PYTHON, npm and npx record their argv to a trace and exit 0, so the
# real verify.sh runs end to end in about a second and can never run the real
# pytest (no recursion). PYTHON passes through to the real interpreter for
# exactly scripts/e2e_flaky_summary.py, which is the one thing the script needs
# real output from. Each child runs in its own process group with a timeout and
# the group is killed if it overruns.

FAKE_PYTHON = r"""#!/bin/bash
echo "PYTHON $*" >> "$TRACE"
if [ -n "$FAKE_FAIL" ]; then case "$*" in "$FAKE_FAIL"*) exit 1;; esac; fi
case "$*" in
  "-m ruff --version") [ "$FAKE_FAIL" = "-m ruff --version" ] && exit 1; echo "ruff $FAKE_RUFF_VERSION"; exit 0;;
  *scripts/e2e_flaky_summary.py*)
    [ -n "$FAKE_SUMMARY_FAILS" ] && exit 1
    exec "$REAL_PYTHON" "$@";;
esac
exit 0
"""
FAKE_NPM = """#!/bin/bash
echo "NPM $*" >> "$TRACE"
if [ -n "$FAKE_FAIL" ]; then case "$*" in "$FAKE_FAIL"*) exit 1;; esac; fi
exit 0
"""
FAKE_NPX = r"""#!/bin/bash
echo "NPX $*" >> "$TRACE"
project=$(echo "$*" | sed -n 's/.*--project=\([^ ]*\).*/\1/p')
[ -z "$project" ] && exit 0
echo '{"suites": []}' > "$PLAYWRIGHT_JSON_OUTPUT_NAME"
exit 0
"""
# What steps 0-6 run, in order, as they appear in the trace (the prefix the fake logs).
STEPS_0_TO_6 = [
    'PYTHON -c import bcrypt, httpx, ruff',
    'PYTHON -m ruff --version',
    'PYTHON -m ruff check .',
    'PYTHON scripts/check_test_traps.py --require-git',
    'PYTHON scripts/check_conformance.py',
    'PYTHON -m pytest tests/unit/',
    'PYTHON -m pytest tests/integration/',
    'NPM run test:unit',
]
PLAYWRIGHT_RUNS = [f'NPX playwright test --project={project}' for project in PROJECTS]
BASH = '/bin/bash' if Path('/bin/bash').exists() else 'bash'


def run_gate(tmp_path, args, script=None, summary_fails=False, fail_command='', timeout=30):
    """Run verify.sh (or a copy) under the fakes. Returns (exit code, output, trace lines)."""
    bin_dir = tmp_path / 'fakes'
    bin_dir.mkdir(exist_ok=True)
    for name, body in (('python', FAKE_PYTHON), ('npm', FAKE_NPM), ('npx', FAKE_NPX)):
        (bin_dir / name).write_text(body, encoding='utf-8')
        (bin_dir / name).chmod(0o755)
    trace = tmp_path / 'trace.txt'
    trace.write_text('', encoding='utf-8')
    pin = re.search(r'^ruff==(\S+)', (REPO / 'requirements-dev.txt').read_text(encoding='utf-8'), re.M).group(1)
    env = dict(os.environ, PATH=f'{bin_dir}{os.pathsep}{os.environ["PATH"]}', PYTHON=str(bin_dir / 'python'),
               REAL_PYTHON=sys.executable, TRACE=str(trace), FAKE_RUFF_VERSION=pin,
               FAKE_SUMMARY_FAILS='1' if summary_fails else '', FAKE_FAIL=fail_command)
    proc = subprocess.Popen([BASH, str(script or VERIFY), *args], cwd=REPO, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return proc.returncode, out, trace.read_text(encoding='utf-8').splitlines()


def _in_order(trace, expected):
    position = 0
    for want in expected:
        while position < len(trace) and not trace[position].startswith(want):
            position += 1
        if position == len(trace):
            return want
        position += 1
    return None


def test_the_expected_steps_0_to_6_are_what_the_script_contains():
    """The list above is not a second opinion: each command must really be in verify.sh."""
    text = _verify_text().replace('"', '')
    for entry in STEPS_0_TO_6:
        tool, _, command = entry.partition(' ')
        needle = command.strip().replace('PYTHON ', '')
        assert needle in text, f'{entry!r} is not in verify.sh: update STEPS_0_TO_6'


def test_gate_with_no_flag_runs_steps_0_to_6_then_all_four_playwright_runs_then_the_all_clear(tmp_path):
    code, out, trace = run_gate(tmp_path, [])
    assert code == 0, out
    assert _in_order(trace, STEPS_0_TO_6 + PLAYWRIGHT_RUNS) is None, trace
    assert BANNER in out
    assert 'safe to open a PR' in out
    assert SEAM_BANNER not in out


def test_gate_with_no_e2e_runs_steps_0_to_6_skips_step_7_and_says_so(tmp_path):
    code, out, trace = run_gate(tmp_path, ['--no-e2e'])
    assert code == 0, out
    assert _in_order(trace, STEPS_0_TO_6) is None, trace
    assert not [line for line in trace if line.startswith('NPX')]
    assert 'SKIPPED' in out
    assert BANNER in out


@pytest.mark.parametrize('step', STEPS_0_TO_6)
def test_a_failing_step_0_to_6_fails_the_gate_and_stops_there(tmp_path, step):
    """Every step is fail-guarded today (including the ruff version read, whose empty
    output is what fails). Softening any `|| fail` to `|| true` must be seen."""
    code, out, trace = run_gate(tmp_path, [], fail_command=step.partition(' ')[2].strip())
    assert code != 0, out
    assert BANNER not in out
    assert SEAM_BANNER not in out
    position = STEPS_0_TO_6.index(step)
    assert _in_order(trace, STEPS_0_TO_6[:position + 1]) is None, trace
    later = [line for line in trace if any(line.startswith(s) for s in STEPS_0_TO_6[position + 1:])]
    assert not later, f'ran after the failing step: {later}'
    assert not [line for line in trace if line.startswith('NPX')], 'step 7 ran after a failing step'


def test_gate_with_e2e_only_runs_none_of_steps_0_to_6(tmp_path):
    code, out, trace = run_gate(tmp_path, ['--e2e-only'])
    assert code == 0, out
    assert _in_order(trace, PLAYWRIGHT_RUNS) is None, trace
    ran = [line for line in trace if line.startswith('NPM') or line.startswith(('PYTHON -c', 'PYTHON -m ruff --version', 'PYTHON -m ruff check .', 'PYTHON -m pytest', 'PYTHON scripts/check_'))]
    assert not ran, ran


# ---- A clean-looking exit that never reached the end must not read as a pass ----

def _copy_with_injection(tmp_path, injected):
    """verify.sh copied beside a symlink to the summary script, with a line added just after the trap."""
    scripts = tmp_path / 'tree' / 'scripts'
    scripts.mkdir(parents=True)
    text = _verify_text()
    marker = '  trap on_exit EXIT\n'
    assert text.count(marker) == 1
    (scripts / 'verify.sh').write_text(text.replace(marker, marker + injected + '\n'), encoding='utf-8')
    (scripts / 'e2e_flaky_summary.py').symlink_to(REPO / 'scripts' / 'e2e_flaky_summary.py')
    return scripts / 'verify.sh'


@pytest.mark.parametrize('injected', ['echo "$NO_SUCH_VARIABLE"', 'exit 0'], ids=['unbound-variable', 'premature-exit-0'])
def test_a_gate_that_stops_early_with_status_0_is_a_failure(tmp_path, injected):
    """On macOS /bin/bash 3.2 an unbound variable aborts with exit 0 once an EXIT trap is set
    (measured); `exit 0` shows the same shape on any bash. Neither may read as a pass."""
    script = _copy_with_injection(tmp_path, injected)
    code, out, _ = run_gate(tmp_path, ['--e2e-only'], script=script)
    assert code != 0, out
    assert BANNER not in out
    assert SEAM_BANNER not in out


# ---- Every place that says the gate mirrors CI names the retry exception ----

MIRRORS = re.compile(r'mirrors? (what )?CI|green in CI', re.I)
# These say "mirrors CI" about pytest roots in the trap checker, not about browser retries.
MIRRORS_ABOUT_SOMETHING_ELSE = {'scripts/check_test_traps.py', 'tests/unit/test_check_test_traps.py',
                                'tests/unit/test_e2e_local_retry_gate.py'}


def _tracked_text_files():
    names = subprocess.run(['git', 'ls-files'], cwd=REPO, capture_output=True, text=True, check=True).stdout.split('\n')
    for name in names:
        if not name or name.startswith(('specs/', 'QA/', 'libs/', 'node_modules/')) or name in MIRRORS_ABOUT_SOMETHING_ELSE:
            continue
        try:
            yield name, (REPO / name).read_text(encoding='utf-8').splitlines()
        except (UnicodeDecodeError, OSError):
            continue


def _claim_context(lines, index):
    """The text a reader takes with the claim: a table row or a Makefile `##` help line stands
    alone; otherwise the paragraph, i.e. the contiguous non-blank lines around it."""
    if lines[index].lstrip().startswith('|') or '## ' in lines[index]:
        return lines[index]
    start, end = index, index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return ' '.join(lines[start:end + 1])


def mirror_claims_without_the_exception(files):
    missing = []
    for name, lines in files:
        for index, line in enumerate(lines):
            if MIRRORS.search(line) and not re.search(r'retr(y|ies)', _claim_context(lines, index), re.I):
                missing.append(f'{name}:{index + 1}')
    return missing


def test_every_claim_that_the_local_gate_mirrors_ci_names_the_retry_exception():
    assert mirror_claims_without_the_exception(_tracked_text_files()) == []


def test_the_mirror_claim_scan_can_fail_and_does_find_claims():
    found = [(n, l) for n, l in _tracked_text_files() if any(MIRRORS.search(x) for x in l)]
    assert len(found) >= 4, 'the scan matched almost nothing; its patterns have drifted'
    assert mirror_claims_without_the_exception([('x.md', ['make verify mirrors CI exactly.'])]) == ['x.md:1']
    assert mirror_claims_without_the_exception([('x.md', ['it mirrors CI, but a retry is listed'])]) == []
    # An unrelated "retries" in the next paragraph, a neighbouring table row, or the next help line is not the exception.
    unrelated = 'The downloader retries a failed fetch three times.'
    assert mirror_claims_without_the_exception([('x.md', ['make verify mirrors CI exactly.', '', unrelated])]) == ['x.md:1']
    assert mirror_claims_without_the_exception([('x.md', ['| `make verify` | mirrors CI |', '| `x` | ' + unrelated + ' |'])]) == ['x.md:1']
    assert mirror_claims_without_the_exception([('Makefile', ['verify: ## mirrors CI', 'x: ## ' + unrelated])]) == ['Makefile:1']
    assert mirror_claims_without_the_exception([('x.md', ['make verify mirrors CI exactly,', 'but a retry is listed.'])]) == []
