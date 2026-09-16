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


def test_plan_checkboxes_agree_with_explicit_states():
    errors = _task_status_errors(PLAN.read_text(encoding='utf-8'))
    assert not errors, f'inconsistent task status: {errors}'


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
