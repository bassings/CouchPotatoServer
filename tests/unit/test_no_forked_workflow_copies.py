"""The repo must not carry its own copies of the multi-lens workflow scripts.

Replaces test_workflow_scripts_parse.py, whose subject was deleted on
2026-08-17. That test guarded repo-local `.claude/workflows/*.js` copies
against a parse error, and its own anti-vacuity check said to delete it with
them. The parse guard goes; the reason those copies were dangerous does not,
so it is inverted here into a guard on the rule that replaced them.

WHY A FORK IS THE HAZARD, NOT JUST A STALE FILE

A repo-local copy WINS over the installed one on name collision. That makes a
fork silent in both directions: it takes this repo's fixes out of reach of the
global harness, and it takes every later global fix out of reach of this repo,
with nothing anywhere reporting that it happened.

Measured, not hypothetical. The copies removed on 2026-08-17 were pinned at
2026-08-07 and 2026-08-08 and contained no run-ledger write at all, because
they predated the ledger entirely. Every plan-cycle and review-cycle run in
this repo between those dates and 2026-08-17 therefore produced no telemetry,
and the weekly delivery optimiser reported this repo as `uninstrumented` --
correctly, but with no way to say why. The previous forked copy had also
shipped a `//` comment inside an array literal that swallowed its own closing
bracket, which is the defect the deleted test existed to catch.

Tune the cycles through `.claude/harness-triggers.json`, which the installed
workflow reads. See AGENTS.md, "Multi-lens harness: path triggers and
precedence".
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO / '.claude' / 'workflows'
TRIGGERS = REPO / '.claude' / 'harness-triggers.json'

# The keys the installed review-cycle workflow reads from the override file.
TRIGGER_KEYS = ('ui', 'data', 'architecture', 'operability')


def test_the_repo_does_not_fork_the_harness_workflows():
    found = sorted(p.name for p in WORKFLOW_DIR.glob('*.js')) if WORKFLOW_DIR.is_dir() else []
    assert not found, (
        'repo-local harness workflow copies found in .claude/workflows/: %s\n\n'
        'A repo-local copy WINS over the installed one, so it silently shadows '
        'every later harness fix -- including the run-ledger write, whose '
        'absence made this repo report as uninstrumented for ten days with no '
        'warning.\n\n'
        'Tune triggers in .claude/harness-triggers.json instead of forking the '
        'workflow. If a change genuinely cannot be expressed there, it belongs '
        'upstream in the harness, not in a copy here.' % ', '.join(found)
    )


def test_the_trigger_override_is_present_and_readable():
    """Anti-vacuity: the test above passes trivially if triggers were lost too.

    Removing the forks without leaving the override behind would delete this
    repo's lens tuning rather than migrate it, and the test above would happily
    report success.
    """
    assert TRIGGERS.is_file(), (
        '%s is missing. Removing the forked workflows without it drops this '
        "repo's lens triggers back to the harness defaults, which do not know "
        'about couchpotato/ paths.' % TRIGGERS.relative_to(REPO)
    )
    rules = json.loads(TRIGGERS.read_text(encoding='utf-8'))
    for key in TRIGGER_KEYS:
        assert isinstance(rules.get(key), list) and rules[key], (
            'harness-triggers.json is missing a non-empty "%s" glob list; the '
            'installed workflow reads exactly these keys.' % key
        )


def test_the_triggers_still_cover_the_two_hard_won_paths():
    """Both entries cost a real review cycle to discover. Pin them.

    - couchpotato/api.py, NOT couchpotato/core/api.py: the latter does not
      exist, so while the glob named it the API boundary never triggered
      lens-architecture at all.
    - Scheduled behaviour is an operability concern wherever it lives: a change
      to the scheduled full-library cleanup in plugins/manage.py matched no
      operability glob, so the cycle skipped lens-operability for its own diff.
    """
    rules = json.loads(TRIGGERS.read_text(encoding='utf-8'))
    assert 'couchpotato/api.py' in rules['architecture']
    assert 'couchpotato/core/api.py' not in rules['architecture'], (
        'couchpotato/core/api.py does not exist; naming it is how the API '
        'boundary silently stopped triggering lens-architecture.'
    )
    for path in ('couchpotato/core/_base/scheduler.py',
                 'couchpotato/core/plugins/manage.py'):
        assert path in rules['operability'], (
            '%s must stay in the operability globs: scheduled behaviour is an '
            'operability concern and path globs alone missed it once.' % path
        )
