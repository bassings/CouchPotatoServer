#!/usr/bin/env python3
"""List the E2E tests that passed only on a retry, from Playwright's JSON results.

scripts/verify.sh retries a failed browser test once (owner decision
2026-11-21; CI stays strict and fails on any flaky test). A test that fails and
then passes would otherwise vanish into a green gate, so each Playwright
invocation also writes its JSON report and this script reads them all.

It REPORTS; Playwright's own exit code decides whether the gate passes, so this
always exits 0. The one thing it must not do is say "none flaky" when it could
not read the results, so an unreadable file is reported as UNKNOWN instead.
Playwright marks a flaky test `ok: true`, the same as a pass, so the test's own
`status == "flaky"` is the only reliable signal.

Usage: e2e_flaky_summary.py <playwright-report.json>...
Stdlib only. Prints repo-relative paths, never absolute ones.
"""
import json
import os
import sys

TITLE_SEP = ' › '


def _display_file(report, file):
    """Repo-relative path for a spec file, never an absolute one."""
    try:
        config = report['config']
        test_dir = config['projects'][0]['testDir']
        relative_dir = os.path.relpath(test_dir, config['rootDir'])
        if relative_dir.startswith('..'):
            return os.path.basename(file)
        return os.path.normpath(os.path.join(relative_dir, file)).replace(os.sep, '/')
    except (KeyError, IndexError, TypeError, ValueError):
        return os.path.basename(file)


def _walk(suite, parents):
    """Yield (describe titles, spec) for every spec under a suite."""
    for spec in suite.get('specs', []):
        yield parents, spec
    for child in suite.get('suites', []):
        yield from _walk(child, parents + [child.get('title', '')])


def find_flaky(report):
    """Tests Playwright classed as flaky: failed, then passed on a retry."""
    found = []
    for file_suite in report.get('suites', []):
        for parents, spec in _walk(file_suite, []):
            for test in spec.get('tests', []):
                if test.get('status') != 'flaky':
                    continue
                title = TITLE_SEP.join([p for p in parents if p] + [spec.get('title', '')])
                found.append({
                    'file': _display_file(report, spec.get('file', '')),
                    'line': spec.get('line', 0),
                    'title': title,
                    'project': test.get('projectName') or '',
                })
    return found


def _label(path):
    return os.path.splitext(os.path.basename(path))[0]


def summarise(paths):
    flaky = []
    unreadable = []
    for path in paths:
        try:
            with open(path, encoding='utf-8') as handle:
                flaky.extend(find_flaky(json.load(handle)))
        except (OSError, ValueError):
            unreadable.append(_label(path))
    lines = []
    if flaky:
        lines.append('FLAKY E2E TESTS: passed only on retry (CI would fail these):')
        for item in flaky:
            project = '[%s] ' % item['project'] if item['project'] else ''
            lines.append('  %s:%s  %s%s' % (item['file'], item['line'], project, item['title']))
    elif not unreadable:
        lines.append('No flaky E2E tests (nothing passed only on retry).')
    for label in unreadable:
        lines.append('UNKNOWN: could not read the "%s" results, so flakiness there cannot be stated.' % label)
    return '\n'.join(lines)


if __name__ == '__main__':
    print(summarise(sys.argv[1:]))
    sys.exit(0)
