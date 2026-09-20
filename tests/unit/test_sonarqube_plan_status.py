"""Keep the active SonarQube plan's checkbox and explicit state consistent."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PLAN = (
    Path(__file__).resolve().parents[2]
    / 'specs'
    / 'PLAN-2026-09-15-sonarqube-improvements.md'
)
CLOSED_STATES = {'completed', 'merged'}
OPEN_STATES = {'awaiting-ci', 'blocked', 'building', 'in-progress', 'queued'}
LIFECYCLE_WORDS = re.compile(
    r'\b(?:await(?:ing|s)?|pending|building|queued|blocked|in-progress|outstanding)\b',
    re.IGNORECASE,
)
PASSED_COLLECTION_TOTAL = re.compile(
    r'\bpassed(?::)?\s+[\d,]+\s+Python unit(?: tests?)?\b',
    re.IGNORECASE,
)
LIFECYCLE_MARKER = re.compile(
    r'^> \*\*Lifecycle: (active|proposed|queued|completed|superseded|historical)\*\*$',
    re.IGNORECASE | re.MULTILINE,
)


def _task_status_errors(text):
    implementation = text.split('## Implementation sequence', 1)[1].split(
        '## Conductor log', 1
    )[0]
    candidate_lines = re.findall(r'^\s*-\s*\S.*$', implementation, re.MULTILINE)
    task_blocks = re.findall(
        r'^- \[([ x])\] \*\*(T\d+)\b(.*?)(?=^- \[[ x]\]|\Z)',
        implementation,
        re.MULTILINE | re.DOTALL,
    )

    errors = []
    parsed_ids = [task_id for _, task_id, _ in task_blocks]
    if len(candidate_lines) != len(task_blocks):
        errors.append(
            f'task-line format drift: found {len(candidate_lines)} checklist lines, '
            f'parsed {len(task_blocks)} canonical tasks'
        )
    if len(parsed_ids) != len(set(parsed_ids)):
        errors.append(f'duplicate task IDs: {parsed_ids!r}')
    if not candidate_lines:
        errors.append('no task lines found; the plan format may have drifted')

    for mark, task_id, block in task_blocks:
        states = re.findall(r'\bstate:\s*([a-z-]+)', block, re.IGNORECASE)
        if len(states) != 1:
            errors.append(f'{task_id} has {len(states)} explicit states')
            continue
        state = states[0].lower()
        if state not in OPEN_STATES | CLOSED_STATES:
            errors.append(f'{task_id} has unknown state {states[0]!r}')
            continue
        is_closed = state in CLOSED_STATES
        if (mark == 'x') != is_closed:
            errors.append(f'{task_id} checkbox disagrees with state {states[0]!r}')
        description = re.sub(
            r'\bstate:\s*[a-z-]+(?:\s+#\d+)?', '', block, count=1, flags=re.IGNORECASE
        )
        lifecycle = LIFECYCLE_WORDS.search(description)
        if lifecycle:
            errors.append(
                f'{task_id} describes lifecycle outside state: {lifecycle.group(0)!r}'
            )
    return errors


def _plan_lifecycle_errors(text):
    """A plan with no open tasks must stop presenting itself as active guidance."""
    marker = LIFECYCLE_MARKER.search('\n'.join(text.splitlines()[:12]))
    if marker is None:
        return ['missing canonical lifecycle marker near the plan title']

    implementation = text.split('## Implementation sequence', 1)[1].split(
        '## Conductor log', 1
    )[0]
    task_marks = re.findall(
        r'^- \[([ x])\] \*\*T\d+\b', implementation, re.MULTILINE
    )
    if not task_marks:
        return ['no canonical task checkboxes found']

    lifecycle = marker.group(1).lower()
    has_open_tasks = ' ' in task_marks
    if not has_open_tasks and lifecycle != 'completed':
        return [f'finished plan has lifecycle {lifecycle!r}, not completed']
    if has_open_tasks and lifecycle == 'completed':
        return ['plan with open tasks has completed lifecycle']
    return []


def test_plan_checkboxes_agree_with_explicit_states():
    errors = _task_status_errors(PLAN.read_text(encoding='utf-8'))
    assert not errors, f'inconsistent task status: {errors}'


def test_plan_lifecycle_agrees_with_whether_tasks_remain_open():
    errors = _plan_lifecycle_errors(PLAN.read_text(encoding='utf-8'))
    assert not errors, f'inconsistent plan lifecycle: {errors}'


@pytest.mark.parametrize(
    ('lifecycle', 'mark', 'has_error'),
    [
        ('active', ' ', False),
        ('completed', 'x', False),
        ('active', 'x', True),
        ('completed', ' ', True),
    ],
)
def test_plan_lifecycle_check_covers_active_and_finished_states(
    lifecycle, mark, has_error
):
    text = (
        '# Plan\n\n'
        f'> **Lifecycle: {lifecycle}**\n\n'
        '## Implementation sequence\n\n'
        f'- [{mark}] **T1** example — state: completed\n\n'
        '## Conductor log\n'
    )
    assert bool(_plan_lifecycle_errors(text)) is has_error


def test_plan_does_not_report_collected_python_items_as_all_passed():
    text = PLAN.read_text(encoding='utf-8')
    assert not PASSED_COLLECTION_TOTAL.search(text)


@pytest.mark.parametrize(
    'claim',
    [
        'The full gate passed 4,320 Python unit tests.',
        'Verification passed: 4,320 Python unit tests.',
        'The gate passed 4320 Python unit.',
    ],
)
def test_python_verification_wording_rejects_passed_collection_totals(claim):
    assert PASSED_COLLECTION_TOTAL.search(claim)


@pytest.mark.parametrize(
    'claim',
    [
        'The gate covered 4,320 collected Python unit-test items.',
        'Python unit: 4,301 passed, 14 skipped, 5 xfailed.',
    ],
)
def test_python_verification_wording_accepts_precise_outcomes(claim):
    assert not PASSED_COLLECTION_TOTAL.search(claim)


def test_final_reliability_inventory_names_all_nine_surviving_findings():
    text = PLAN.read_text(encoding='utf-8')
    inventory = text.split(
        'T16 reviewed the complete nine-finding reliability inventory.', 1
    )[1].split('The exact scan reports no other SonarQube bugs.', 1)[0]
    rows = re.findall(
        r'^\s*\| `([^`]+)` `([^`]+)` \|', inventory, re.MULTILINE
    )

    assert len(rows) == 9
    assert set(rows) == {
        ('python:S8904', 'awesomehd.py:37'),
        ('python:S8904', 'bithdtv.py:83'),
        ('python:S8904', 'thepiratebay.py:71'),
        ('python:S5779', 'test_race_conditions.py:298'),
        ('typescript:S5845', 'category-editor.spec.ts:90'),
        ('Web:PageWithoutTitleCheck', 'base.html:3'),
        ('python:S5863', 'test_password_storage.py:67'),
        ('python:S1226', 'newznab.py:170'),
        ('python:S1226', 'torrentpotato.py:151'),
    }


@pytest.mark.parametrize(
    'task_line',
    [
        '- [x] **T1** incorrectly checked — state: building',
        '- [x] **T1** incorrectly checked — state: queued',
        '- [x] **T1** incorrectly checked — state: blocked',
        '- [x] **T1** incorrectly checked — state: awaiting-ci',
        '- [x] **T1** incorrectly checked — state: in-progress',
        '- [ ] **T1** incorrectly open — state: completed',
        '- [ ] **T1** incorrectly open — state: merged',
        '- [ ] **T1** unknown state — state: complete',
    ],
)
def test_status_check_rejects_checkbox_state_mismatches(task_line):
    text = f'## Implementation sequence\n\n{task_line}\n\n## Conductor log\n'
    assert _task_status_errors(text)


@pytest.mark.parametrize('state', ['building', 'queued', 'blocked', 'awaiting-ci', 'in-progress'])
def test_status_check_accepts_open_tasks_with_open_states(state):
    text = (
        f'## Implementation sequence\n\n- [ ] **T1** open — state: {state}\n\n'
        '## Conductor log\n'
    )
    assert not _task_status_errors(text)


def test_status_check_rejects_the_previous_stale_t1_prose():
    text = (
        '## Implementation sequence\n\n'
        '- [x] **T1** truthful scan — state: merged #354\n'
        '  (AC-PROD-1 awaits a post-commit clean master scan).\n\n'
        '## Conductor log\n'
    )
    assert _task_status_errors(text)


@pytest.mark.parametrize(
    'malformed',
    [
        '- [X] **T2** uppercase checkbox — state: merged',
        '  - [x] **T2** indented task — state: merged',
        '-  [x] **T2** altered spacing — state: merged',
        '-[x] **T2** missing spacing — state: merged',
        '- [x] **Task one** missing canonical ID — state: merged',
    ],
)
def test_status_check_rejects_one_malformed_task_among_valid_tasks(malformed):
    text = (
        '## Implementation sequence\n\n'
        '- [x] **T1** valid — state: merged\n'
        f'{malformed}\n\n'
        '## Conductor log\n'
    )
    assert _task_status_errors(text)


@pytest.mark.parametrize(
    'tasks',
    [
        '- [x] **T1** missing state',
        '- [x] **T1** duplicate state — state: merged; state: completed',
        '- [x] **T1** duplicate ID — state: merged\n'
        '- [x] **T1** duplicate ID again — state: completed',
    ],
)
def test_status_check_rejects_missing_duplicate_state_or_task_id(tasks):
    text = f'## Implementation sequence\n\n{tasks}\n\n## Conductor log\n'
    assert _task_status_errors(text)
