"""The change-surface gate must see the backend the UI actually calls (T19).

`UI_PATTERNS` matched the templates, the static assets and the harness, but
not the API handlers those pages invoke -- so a change to `media.list`'s
implementation could break every movie page while the browser suites were
skipped on the PR that did it.

The fix is not "add more patterns and hope". A hardcoded list of backend files
goes stale the first time the UI calls a new handler, which is the same drift
this whole gate exists to prevent. So the list is DERIVED here, from the UI's
own source, and the test fails when the pattern and the derivation disagree.

That keeps `needs_e2e.sh` fast and readable (a literal regex, no runtime
discovery) while making the literal impossible to leave behind.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / 'scripts' / 'needs_e2e.sh'
UI_DIR = REPO / 'couchpotato' / 'ui'

#: `callApiHandler, 'media.list'` and `callApiHandler('media.list'`
CALL_RE = re.compile(r"callApiHandler[,(]\s*'([a-z_.]+)'")


def api_names_the_ui_calls():
    names = set()
    for path in UI_DIR.rglob('*.py'):
        names |= set(CALL_RE.findall(path.read_text()))
    return names


def file_registering(name):
    """The module that registers `name` as an API view or event."""
    for pattern in ("addApiView('%s'" % name, "addEvent('%s'" % name):
        out = subprocess.run(
            ['grep', '-rl', pattern, '--include=*.py', 'couchpotato/'],
            cwd=str(REPO), capture_output=True, text=True).stdout.split()
        if out:
            return sorted(out)[0]
    return None


def ui_patterns():
    line = [l for l in SCRIPT.read_text().splitlines() if l.startswith('UI_PATTERNS=')]
    assert len(line) == 1, 'UI_PATTERNS is not a single assignment'
    return line[0]


def pattern_alternatives():
    """The alternatives of UI_PATTERNS, as literal path prefixes.

    Split on `|` and unescape, rather than scraping path-shaped substrings out
    of the whole line. The scraping version was VACUOUS: `couchpotato/api\\.py$`
    contains a bare `couchpotato/` once the `\\.` breaks the character run, and
    a `couchpotato/` prefix matches every file in the project -- so every
    coverage assertion passed no matter what the pattern said. Mutation
    testing caught it; reading it did not.
    """
    body = ui_patterns()
    inner = body[body.index("'") + 1:body.rindex("'")]
    inner = inner.lstrip('^(').rstrip(')')
    out = []
    for alt in inner.split('|'):
        alt = alt.strip().replace('\\.', '.').rstrip('$')
        if alt:
            out.append(alt)
    assert len(out) >= 10, 'only parsed %r out of UI_PATTERNS' % out
    return out


def test_the_ui_really_does_call_backend_handlers():
    """Precondition. If this ever returns nothing, the derivation below is
    vacuous and every assertion built on it passes for free."""
    names = api_names_the_ui_calls()
    assert len(names) >= 5, (
        'found only %r -- the extraction is broken, not the coverage' % names
    )


@pytest.mark.parametrize('name', sorted(api_names_the_ui_calls()))
def test_every_handler_the_ui_calls_is_covered_by_the_gate(name):
    path = file_registering(name)
    assert path, (
        "cannot locate the module registering '%s'; the derivation needs "
        'updating before it can guard anything' % name
    )
    covered = any(path == alt or path.startswith(alt)
                  for alt in pattern_alternatives())
    assert covered, (
        "%s serves the UI's '%s' but is not matched by UI_PATTERNS, so a "
        'change to it skips the browser suites' % (path, name)
    )


def test_the_api_dispatcher_itself_is_covered():
    """Every one of those calls goes through `couchpotato/api.py`. A change
    there breaks all of them at once."""
    body = ui_patterns()
    assert 'couchpotato/api\\.py$' in body or 'couchpotato/api.py' in body, (
        'the API dispatcher every UI call passes through is not in UI_PATTERNS'
    )
