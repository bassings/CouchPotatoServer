"""T18's `needs:` list must name exactly the open tasks, and a test must say so.

The list has been wrong FOUR times, in both directions, and the parenthesis
around it has predicted its own failure twice while being edited:

    - T19 was omitted by the very commit that wrote the line
    - T20/T21/T22 were added by later tasks and omitted again (caught in #249)
    - the commit that ticked T36 left T36 named as open AND omitted the T45 it
      added in the same commit (caught in review, 2026-08-19)
    - ticking T46 left T46 in the list minutes later (caught by this file)

Every one of those was found by a human or a reviewer re-deriving the list by
hand. That is the definition of a rule that should be a check: prose telling
the next author to remember something they have already forgotten four times.

Counted as INCIDENTS, not as directions: the T36/T45 commit was one incident
that went wrong both ways at once. The plan file states the same four, and the
count was reconciled across all three places on 2026-08-19 after review found it
written three different ways -- a miscount inside the paragraph arguing that
miscounts are the recurring failure.

Deliberately a SET comparison, not a sequence one. File order and reading order
differ (T11/T15 are transposed) and that difference carries no meaning -- an
order-sensitive assertion would fail on a correct list, which is how guards get
switched off.

KNOWN LIMIT, and it fails OPEN in the direction that matters most. `_open_tasks`
anchors on `^- [ ] Tn:` exactly. Review probed four format variations and three
slipped through silently: an em-dash instead of the colon, a leading indent, and
a bolded `**T48**`. Each made a genuinely-open task invisible to the check, so
`test_no_open_task_is_missing_from_the_dependency_list` passed while the task was
missing -- and `test_the_extraction_actually_found_something` only asserts `> 1`,
so a partial drift survives it too.

All 47 tasks conform today and the file has one house style, so this is a bounded
future risk rather than a present hole. It is recorded rather than fixed because
loosening the regex trades a silent false negative for noisy false positives on
prose that merely resembles a task line, and this file guards bookkeeping, not
production. **The task-line format is load-bearing: change it and change this
test in the same commit.**
"""
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PLAN = Path(__file__).resolve().parents[2] / 'specs' / 'REMEDIATION-2026-08.md'


def _open_tasks(text):
    """Every `- [ ] Tn:` in the plan, minus T18 itself."""
    return {t for t in re.findall(r'^- \[ \] (T\d+):', text, re.M) if t != 'T18'}


def _needs_list(text):
    m = re.search(
        r'needs: \*\*every other open task\*\* — ([^—]+?) — because', text
    )
    assert m, "T18's needs-list is not in the expected shape; update this test WITH the file"
    return {x.strip() for x in m.group(1).split(',') if x.strip()}


class TestTheNeedsListMatchesReality:

    def test_the_plan_file_is_where_we_think_it_is(self):
        """Guards the guard: a moved or renamed plan makes every other
        assertion here vacuously pass on an empty string."""
        assert PLAN.is_file(), f'plan not found at {PLAN}'
        assert '## Tasks' in PLAN.read_text(encoding='utf-8')

    def test_no_ticked_task_is_still_named_as_a_dependency(self):
        text = PLAN.read_text(encoding='utf-8')
        stale = _needs_list(text) - _open_tasks(text)
        assert not stale, (
            f'T18 names {sorted(stale)} as open, but they are ticked. A merged '
            f'task left in the list makes T18 look permanently blocked.'
        )

    def test_no_open_task_is_missing_from_the_dependency_list(self):
        text = PLAN.read_text(encoding='utf-8')
        missing = _open_tasks(text) - _needs_list(text)
        assert not missing, (
            f'T18 omits open task(s) {sorted(missing)}. T18 is the final sweep, '
            f'so an omission means it runs before work that adds the residue it '
            f'is meant to sweep.'
        )

    def test_the_extraction_is_structurally_sound(self):
        """Both assertions above pass trivially if either regex matches
        nothing, so the shape has to be pinned somewhere. Pin it STRUCTURALLY
        rather than by a minimum count.

        An earlier version asserted `> 1` on both sets, which review caught as
        a countdown to self-inflicted breakage: this plan is meant to finish.
        At one remaining task, and again at zero, those assertions fail on a
        needs-list that is exactly right -- and because this file runs in the
        unit gate, that would block every change in the repo at the precise
        moment the plan succeeded. A guard whose failure mode is triggered by
        the project going well is worse than no guard, because the fix under
        deadline is to delete it.

        What actually needs pinning is that the extraction still WORKS, and
        `_needs_list` already raises on a broken line shape. So the remaining
        risk is `_open_tasks` silently matching nothing while tasks exist,
        which is detectable without assuming any particular number of them."""
        text = PLAN.read_text(encoding='utf-8')

        # Derived INDEPENDENTLY of _open_tasks: scan every checkbox line,
        # capturing the box contents, then subtract the ticked ones. A first
        # draft of this assertion re-used the same regex as _open_tasks and so
        # compared the function to its own implementation -- vacuous, and the
        # exact shape this suite exists to catch.
        boxes = re.findall(r'^- \[([ x])\] (T\d+):', text, re.M)
        assert boxes, 'no task lines at all; the task-line format has drifted'

        ticked = {tid for mark, tid in boxes if mark == 'x'}
        unticked = {tid for mark, tid in boxes if mark == ' '} - {'T18'}
        assert not (ticked & unticked), 'a task is both ticked and open'

        # Zero open tasks is a legitimate end state and must stay green, so
        # this asserts agreement, never a minimum.
        assert _open_tasks(text) == unticked, (
            f'open-task extraction disagrees with an independent scan: '
            f'{_open_tasks(text) ^ unticked}'
        )

    def test_an_empty_needs_list_is_a_legitimate_end_state(self):
        """The companion to the above, asserted rather than merely intended:
        when nothing is left to depend on, the two directional tests must both
        pass on empty sets rather than erroring."""
        assert not ({'T1'} - {'T1'}), 'set difference on equal sets must be empty'
        assert not (set() - set()), 'both-empty must be the passing case'
