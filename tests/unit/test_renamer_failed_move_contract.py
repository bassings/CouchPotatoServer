"""Keep both older recovery contracts aligned with the fail-closed move."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CURRENT = 'specs/PLAN-2026-09-28-failed-move-fail-closed.md'


def test_prior_move_recovery_plan_marks_its_unsafe_success_contract_superseded():
    text = (ROOT / 'specs/PLAN-2026-09-28-renamer-move-recovery.md').read_text()
    failed_move = text.split('AC-DATA-2:', 1)[1].split('AC-REL-1:', 1)[0]

    assert CURRENT in text
    assert 'Superseded for complete-copy failures' in text
    assert 'A failed move never completes recovery by deleting the source' in failed_move
    assert 'matching copy may still complete the move recovery' not in failed_move


def test_remediation_contract_requires_failure_and_source_retention():
    text = (ROOT / 'specs/REMEDIATION-2026-08.md').read_text()
    failed_move = text.split('**AC-DATA-3 / AC-QA-7**', 1)[1].split('**AC-DATA-4', 1)[0]

    assert CURRENT in failed_move
    assert 'the transfer error propagates and the source is retained' in failed_move
    assert 'the source is unlinked and the recovery returns `True`' not in failed_move
