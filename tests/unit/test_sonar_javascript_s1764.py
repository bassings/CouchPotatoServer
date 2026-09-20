"""Recurrence guard for Sonar's repeated-expression parser findings."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PARSER = REPO_ROOT / "couchpotato/static/scripts/ui/log-parser.js"


def test_digit_primitive_has_one_owner() -> None:
    source = PARSER.read_text()

    assert source.count("takeDigit()") == 1, (
        "consume fixed-width digit fields through one helper; repeated direct "
        "cursor-advancing calls are reported as identical logical operands"
    )
