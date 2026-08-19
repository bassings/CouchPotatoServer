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

Deliberately a SET comparison, not a sequence one. File order and reading order
differ (T11/T15 are transposed) and that difference carries no meaning -- an
order-sensitive assertion would fail on a correct list, which is how guards get
switched off.
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

    def test_the_extraction_actually_found_something(self):
        """Both assertions above pass trivially if either regex matches
        nothing. Pin non-emptiness so a formatting change fails loudly rather
        than turning this file into decoration."""
        text = PLAN.read_text(encoding='utf-8')
        assert len(_open_tasks(text)) > 1, 'found <2 open tasks; the regex has drifted'
        assert len(_needs_list(text)) > 1, 'found <2 listed tasks; the regex has drifted'
