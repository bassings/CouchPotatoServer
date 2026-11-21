"""scripts/e2e_flaky_summary.py lists tests that passed only on a retry.

The local gate retries a failed browser test once and must not let a test that
only passed on retry disappear: the owner decision (2026-11-21) is that local
retries, CI stays strict, and every retry-pass is listed. The list comes from
Playwright's own JSON results, so these fixtures follow the shape Playwright
1.65 really writes: a flaky test is `ok: true`, exactly like a pass, and is
distinguishable only by `status == "flaky"`. The `config` block was taken from
a real `--list --reporter=json` run of this repo with the absolute prefix
replaced by a fake one of the same shape: `rootDir` is the resolved testDir,
`configFile` is the repo's playwright.config.ts, and a spec's `file` is
relative to `rootDir`.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'scripts' / 'e2e_flaky_summary.py'

_spec = importlib.util.spec_from_file_location('e2e_flaky_summary', SCRIPT)
summary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(summary)


def _test(status, results, project='chromium'):
    return {'projectName': project, 'status': status,
            'results': [{'status': r} for r in results]}


def _spec_entry(title, line, ok, test, file='settings.spec.ts'):
    return {'title': title, 'file': file, 'line': line, 'ok': ok, 'tests': [test]}


def make_report():
    """One passed, one failed twice, one flaky, one skipped; the flaky and the
    failed ones sit inside a describe so the title carries its group."""
    return {
        'config': {'configFile': '/private/abs/repo/playwright.config.ts',
                   'rootDir': '/private/abs/repo/tests/e2e',
                   'projects': [{'name': 'chromium', 'testDir': '/private/abs/repo/tests/e2e'}]},
        'suites': [{
            'title': 'settings.spec.ts', 'file': 'settings.spec.ts', 'line': 0,
            'specs': [
                _spec_entry('passes', 2, True, _test('expected', ['passed'])),
            ],
            'suites': [{
                'title': 'Undo by keyboard', 'file': 'settings.spec.ts', 'line': 3,
                'specs': [
                    _spec_entry('always fails', 4, False,
                                _test('unexpected', ['failed', 'failed'])),
                    _spec_entry('flaky one', 5, True,
                                _test('flaky', ['failed', 'passed'])),
                    _spec_entry('skipped one', 6, True,
                                _test('skipped', ['skipped'])),
                ],
            }],
        }],
    }


def test_lists_exactly_the_flaky_test():
    found = summary.find_flaky(make_report())
    assert [(f.line, f.title) for f in found] == [(5, 'Undo by keyboard › flaky one')]


def test_a_test_that_failed_twice_is_not_listed_as_flaky():
    titles = [f.title for f in summary.find_flaky(make_report())]
    assert 'Undo by keyboard › always fails' not in titles


def test_passed_and_skipped_tests_are_not_listed():
    titles = ' '.join(f.title for f in summary.find_flaky(make_report()))
    assert 'passes' not in titles
    assert 'skipped' not in titles


def test_a_flaky_test_is_found_by_its_status_not_by_ok_or_result_count():
    """`ok` is true for a flaky test, as it is for a pass. A parser keyed on
    `ok == False` would list nothing here."""
    report = make_report()
    flaky = report['suites'][0]['suites'][0]['specs'][1]
    assert flaky['ok'] is True
    assert [f.line for f in summary.find_flaky(report)] == [5]


def test_file_path_is_repo_relative_and_never_absolute():
    """Resolved against the config file's directory, so the path can be pasted
    into `npx playwright test`. The fake prefix must not appear."""
    found = summary.find_flaky(make_report())
    assert '/private/abs' not in found[0].file
    assert found[0].file == 'tests/e2e/settings.spec.ts'


def test_nothing_flaky_is_reported_as_none_not_as_silence(tmp_path):
    report = make_report()
    report['suites'][0]['suites'][0]['specs'][1]['tests'][0]['status'] = 'expected'
    path = tmp_path / 'chromium.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    text = summary.summarise([str(path)])
    assert 'No flaky' in text


def test_the_listing_names_file_line_title_and_project(tmp_path):
    path = tmp_path / 'chromium.json'
    path.write_text(json.dumps(make_report()), encoding='utf-8')
    text = summary.summarise([str(path)])
    assert 'tests/e2e/settings.spec.ts:5' in text
    assert 'Undo by keyboard › flaky one' in text
    assert 'chromium' in text


def test_flaky_tests_are_collected_across_several_invocations(tmp_path):
    other = make_report()
    other['suites'][0]['file'] = 'wizard.spec.ts'
    spec = other['suites'][0]['suites'][0]['specs'][1]
    spec['file'] = 'wizard.spec.ts'
    spec['line'] = 77
    spec['tests'][0]['projectName'] = 'mobile-chrome'
    first = tmp_path / 'chromium.json'
    second = tmp_path / 'mobile-chrome.json'
    first.write_text(json.dumps(make_report()), encoding='utf-8')
    second.write_text(json.dumps(other), encoding='utf-8')
    text = summary.summarise([str(first), str(second)])
    assert 'settings.spec.ts:5' in text
    assert 'wizard.spec.ts:77' in text


def test_a_flaky_report_and_an_unreadable_one_are_both_reported(tmp_path):
    good = tmp_path / 'chromium.json'
    good.write_text(json.dumps(make_report()), encoding='utf-8')
    text = summary.summarise([str(good), str(tmp_path / 'accessibility.json')])
    assert 'settings.spec.ts:5' in text
    assert 'UNKNOWN: could not read the "accessibility" results' in text


def test_a_missing_results_file_is_reported_as_unknown_not_as_none(tmp_path):
    """No file means the gate cannot say nothing was flaky. Saying 'none' would
    be a false all-clear."""
    text = summary.summarise([str(tmp_path / 'absent.json')])
    assert 'UNKNOWN' in text
    assert 'No flaky' not in text


def test_a_malformed_results_file_is_reported_as_unknown(tmp_path):
    bad = tmp_path / 'chromium.json'
    bad.write_text('{not json', encoding='utf-8')
    text = summary.summarise([str(bad)])
    assert 'UNKNOWN' in text


def test_a_report_without_a_config_file_falls_back_to_the_basename():
    report = make_report()
    del report['config']['configFile']
    found = summary.find_flaky(report)
    assert found[0].file == 'settings.spec.ts'


def test_a_test_dir_outside_the_repo_falls_back_to_the_basename():
    report = make_report()
    report['config']['configFile'] = '/elsewhere/other/playwright.config.ts'
    assert summary.find_flaky(report)[0].file == 'settings.spec.ts'


@pytest.mark.parametrize('payload', ['null', '[]', '3', '"text"', '{"suites": null}', '{"suites": [1]}'])
def test_valid_json_that_is_not_a_report_is_unknown_and_does_not_raise(tmp_path, payload):
    """The script always exits 0: JSON that parses but is not a report is unreadable."""
    path = tmp_path / 'chromium.json'
    path.write_text(payload, encoding='utf-8')
    text = summary.summarise([str(path)])
    assert 'UNKNOWN' in text
    assert 'No flaky' not in text


def test_the_unknown_warning_does_not_leak_the_directory(tmp_path):
    text = summary.summarise([str(tmp_path / 'absent.json')])
    assert str(tmp_path) not in text


def test_cli_exits_zero_even_when_results_are_unreadable(tmp_path):
    """It reports; Playwright's exit code decides pass or fail."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / 'absent.json')],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert 'UNKNOWN' in result.stdout


def test_cli_prints_the_flaky_list(tmp_path):
    path = tmp_path / 'chromium.json'
    path.write_text(json.dumps(make_report()), encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert 'settings.spec.ts:5' in result.stdout
