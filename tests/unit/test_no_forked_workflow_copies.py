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
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO / '.claude' / 'workflows'
TRIGGERS = REPO / '.claude' / 'harness-triggers.json'
AGENTS_MD = REPO / 'AGENTS.md'

# The keys the installed review-cycle workflow reads from the override file.
TRIGGER_KEYS = ('ui', 'data', 'architecture', 'operability')

# Maps the first cell of each AGENTS.md trigger-table row (matched by
# substring) to the harness-triggers.json key it must agree with.
TABLE_ROW_TO_KEY = {
    'lens-design': 'ui',
    'lens-data': 'data',
    'lens-architecture': 'architecture',
    'lens-operability': 'operability',
}


def _load_triggers():
    return json.loads(TRIGGERS.read_text(encoding='utf-8'))


def _table_globs_by_key():
    """Parse the backtick-quoted path globs out of each row of the trigger
    table in AGENTS.md's "Multi-lens harness" section, keyed by
    harness-triggers.json key.

    Only the `lens-product` row is prose-only (it has no glob list and no
    corresponding harness-triggers.json key) and is skipped deliberately.
    """
    text = AGENTS_MD.read_text(encoding='utf-8')
    table_by_key = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('|') or not line.endswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) != 2:
            continue
        label, globs_cell = cells
        matched_key = None
        for needle, key in TABLE_ROW_TO_KEY.items():
            if needle in label:
                matched_key = key
                break
        if matched_key is None:
            continue
        globs = re.findall(r'`([^`]+)`', globs_cell)
        if globs:
            table_by_key[matched_key] = set(globs)
    return table_by_key


def test_the_repo_does_not_fork_the_harness_workflows():
    """The rule is "this directory must not exist", not "no *.js directly
    inside it".

    A narrower ban is evadable: `.claude/workflows/review-cycle.mjs`,
    `.claude/workflows/lib/review-cycle.js` and
    `.claude/workflows/REVIEW-CYCLE.JS` would all dodge a `glob('*.js')`
    check while still shadowing the installed workflow on name collision (a
    case-insensitive filesystem resolves `REVIEW-CYCLE.JS` to the same file
    as `review-cycle.js`; a nested `lib/` nonetheless wins as a repo-local
    copy under some loader resolution orders). Codex's suggested fix --
    narrow the ban to filenames that collide with named harness workflows --
    was considered and rejected: this repo has no uniquely-named local
    workflow to spare, so a narrower rule reintroduces exactly the evasion
    above rather than closing it. Any content at all under `.claude/workflows/`
    is the hazard, regardless of extension, case or nesting.
    """
    found = []
    if WORKFLOW_DIR.is_dir():
        found = sorted(str(p.relative_to(WORKFLOW_DIR)) for p in WORKFLOW_DIR.rglob('*'))
    assert not found, (
        'repo-local content found under .claude/workflows/: %s\n\n'
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

    Removing the forks without leaving the override behind would drop this
    repo's lens tuning back to the harness defaults, which do not know about
    couchpotato/ paths, and the test above would happily report success.
    """
    assert TRIGGERS.is_file(), (
        '%s is missing. Removing the forked workflows without it drops this '
        "repo's lens triggers back to the harness defaults, which do not know "
        'about couchpotato/ paths.' % TRIGGERS.relative_to(REPO)
    )
    rules = _load_triggers()
    for key in TRIGGER_KEYS:
        assert isinstance(rules.get(key), list) and rules[key], (
            'harness-triggers.json is missing a non-empty "%s" glob list; the '
            'installed workflow reads exactly these keys.' % key
        )


def test_harness_triggers_json_matches_the_agents_md_table():
    """AGENTS.md documents the trigger globs as a table; harness-triggers.json
    is the config the installed workflow actually reads. They drifted once
    without anything noticing: the JSON carried three dependency-manifest
    globs (requirements.txt, requirements-dev.txt, pyproject.toml) under
    `architecture` that the table's prose never claimed and that duplicated
    the separate `new_dependency_entries` boolean already OR'd in by the
    workflow, while the file's own header claimed the globs were "carried
    over verbatim". Hand-picked pins over a handful of entries did not catch
    it (dropping unrelated entries from the JSON still left those pins
    green). This test instead asserts full set equality, in both directions,
    between the table and the JSON for every glob-bearing row, and names
    exactly which entries differ on failure.

    Two entries are pinned separately below because set equality proves they
    match, not why they matter -- both cost a real review cycle to discover:

    - couchpotato/api.py, NOT couchpotato/core/api.py: the latter does not
      exist, so while the glob named it the API boundary never triggered
      lens-architecture at all.
    - Scheduled behaviour is an operability concern wherever it lives: a
      change to the scheduled full-library cleanup in plugins/manage.py
      matched no operability glob, so the cycle skipped lens-operability for
      its own diff.
    """
    rules = _load_triggers()
    table = _table_globs_by_key()

    for key in TRIGGER_KEYS:
        json_globs = set(rules[key])
        table_globs = table.get(key, set())
        only_in_json = json_globs - table_globs
        only_in_table = table_globs - json_globs
        assert not only_in_json and not only_in_table, (
            'harness-triggers.json["%s"] and the AGENTS.md trigger table have '
            'drifted.\n'
            'In harness-triggers.json but not in the AGENTS.md table: %s\n'
            'In the AGENTS.md table but not in harness-triggers.json: %s\n'
            'Change both together; see AGENTS.md, "Multi-lens harness: path '
            'triggers and precedence".'
            % (key, sorted(only_in_json), sorted(only_in_table))
        )

    assert 'couchpotato/api.py' in rules['architecture']
    assert 'couchpotato/core/api.py' not in rules['architecture'], (
        'couchpotato/core/api.py does not exist; naming it is how the API '
        'boundary silently stopped triggering lens-architecture.'
    )
    for path in ('couchpotato/core/_base/scheduler.py',
                 'couchpotato/core/plugins/manage.py',
                 'couchpotato/core/plugins/renamer/main.py',
                 'couchpotato/core/plugins/automation.py'):
        assert path in rules['operability'], (
            '%s must stay in the operability globs: scheduled behaviour is an '
            'operability concern and path globs alone missed it once.' % path
        )
