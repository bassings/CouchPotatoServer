"""Mutation jobs must distinguish surviving mutants from broken runners."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/mutation.yml'


def python_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return [step['run'] for step in workflow['jobs']['python-mutation']['steps']
            if step.get('name') in {'Run mutmut', 'Generate mutation report', 'Generate HTML report'}]


def run_python_steps(tmp_path, **overrides):
    tool = tmp_path / 'mutmut'
    tool.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
command = sys.argv[1]
with Path('calls.jsonl').open('a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if command not in {'run', 'results', 'export-cicd-stats'}:
    sys.exit(64)
code = int(os.environ.get('FAIL_' + command.upper().replace('-', '_'), '0'))
if code:
    sys.exit(code)
if command == 'results':
    if sys.argv[2:] != ['--all', 'true']:
        sys.exit(64)
    print('example.mutant: survived')
if command == 'export-cicd-stats' and not os.environ.get('MISSING_REPORT'):
    Path('mutants').mkdir(exist_ok=True)
    Path('mutants/mutmut-cicd-stats.json').write_text('{"total":1,"survived":1}')
''')
    tool.chmod(0o755)
    env = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
           'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary.md'), 'MUTMUT_PATHS': '', **overrides}
    result = None
    for command in python_steps():
        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', command], cwd=tmp_path,
                                env=env, text=True, capture_output=True, timeout=10)
        if result.returncode:
            return result
    assert result is not None
    return result


@pytest.mark.parametrize('failure', ['FAIL_RUN', 'FAIL_RESULTS', 'FAIL_EXPORT_CICD_STATS', 'MISSING_REPORT'])
def test_python_runner_and_report_errors_fail_the_job(tmp_path, failure):
    result = run_python_steps(tmp_path, **{failure: '1'})
    assert result.returncode != 0, result.stdout + result.stderr


def test_survivors_are_reported_without_failing_the_job(tmp_path):
    result = run_python_steps(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = tmp_path / 'reports/mutation/python/mutmut-cicd-stats.json'
    assert json.loads(report.read_text()) == {'total': 1, 'survived': 1}
    assert 'example.mutant: survived' in (tmp_path / 'summary.md').read_text()


def test_dispatch_filters_remain_literal_arguments(tmp_path):
    filters = 'module.* $(touch injected) ; echo boom'
    result = run_python_steps(tmp_path, MUTMUT_PATHS=filters)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert calls[0] == ['run', *filters.split()]
    assert not (tmp_path / 'injected').exists()


@pytest.mark.parametrize('name', ['python-mutation', 'js-mutation'])
def test_workflow_metadata_does_not_hide_runner_failures(name):
    job = yaml.safe_load(WORKFLOW.read_text())['jobs'][name]
    assert not job.get('continue-on-error', False)
    assert all(not step.get('continue-on-error', False) for step in job['steps'])


@pytest.mark.parametrize('failure', ['FAIL_JS', 'MISSING_JSON', 'MISSING_HTML'])
def test_js_execution_and_missing_reports_fail_the_job(tmp_path, failure):
    tool = tmp_path / 'npm'
    tool.write_text(f'#!{sys.executable}\n' + '''
import os, sys
from pathlib import Path
assert sys.argv[1:] == ['run', 'test:mutation']
report = Path('reports/mutation')
report.mkdir(parents=True, exist_ok=True)
if not os.environ.get('MISSING_JSON'):
    (report / 'mutation.json').write_text('{}')
if not os.environ.get('MISSING_HTML'):
    (report / 'stryker.html').write_text('<html>report</html>')
sys.exit(int(os.environ.get('FAIL_JS', '0')))
''')
    tool.chmod(0o755)
    job = yaml.safe_load(WORKFLOW.read_text())['jobs']['js-mutation']
    command = next(step['run'] for step in job['steps'] if step.get('name') == 'Run Stryker')
    env = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'], failure: '1'}
    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', command], cwd=tmp_path,
                            env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode != 0, result.stdout + result.stderr
