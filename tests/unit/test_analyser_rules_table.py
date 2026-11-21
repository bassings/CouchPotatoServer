"""Tests for `.claude/analyser-rules.md`, the generated SonarQube rules table.

The `implementer` agent reads this file on every task and treats it as
reference data, never as instructions. That contract is only as strong as the
file's shape: the generator enforces the bounds, but a table edited by hand in
a PR never passes through the generator. So the shape is checked here, in the
gate, rather than left to review.

What is checked is structure, not meaning. Wording that merely *reads* like an
instruction is deliberately not detected: a regex for it would be a guard on a
stand-in. Instead the table is held to a shape with no room to hide anything:
printable ASCII only (no tag characters, bidi controls or escape sequences),
fixed width cells, a hard size ceiling, and nothing after the table.

`validate_table` returns a list of short problem codes so each hostile fixture
can assert exactly the one rule it breaks.
"""

import re
import subprocess
from pathlib import Path

import pytest
from tests.unit.conftest import sanitized_git_env

REPO_ROOT = Path(__file__).resolve().parents[2]
TABLE = REPO_ROOT / ".claude" / "analyser-rules.md"
TABLE_GIT_PATH = ".claude/analyser-rules.md"

MAX_BYTES = 8192
MAX_ROWS = 20
MAX_GUIDANCE = 160
TITLE = "# Analyser rules table"
STAMP_PREFIX = "derived: "
HEADER = "| rule | guidance | open | recent-new |"
SEPARATOR = "|---|---|---|---|"
RULE_KEY = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
COUNT = re.compile(r"[0-9]+")
PRINTABLE_ASCII = frozenset(range(0x20, 0x7F)) | {0x0A}


def validate_table(path: Path) -> list[str]:
    """Return problem codes for the table at `path`; empty means well formed."""
    if path.is_symlink():
        return ["symlink"]
    if not path.is_file():
        return ["not-regular-file"]

    raw = path.read_bytes()
    problems = []
    if len(raw) > MAX_BYTES:
        problems.append("size")
    if not set(raw) <= PRINTABLE_ASCII:
        # Anything else (tag characters, bidi controls, ESC, tabs, CR) is
        # rejected outright; parsing it further would only report noise.
        return [*problems, "charset"]

    lines = raw.decode("ascii").split("\n")
    if lines[0] != TITLE:
        problems.append("title")
    if len(lines) < 2 or not lines[1].startswith(STAMP_PREFIX):
        problems.append("derived")

    rest = [(number, line) for number, line in enumerate(lines[2:], start=3)]
    while rest and rest[0][1] == "":
        rest.pop(0)
    head = [line for _, line in rest[:2]]
    if head != [HEADER, SEPARATOR]:
        problems.append("header")
        return problems

    body = rest[2:]
    rows = []
    while body and body[0][1].startswith("|"):
        rows.append(body.pop(0)[1])
    if not 1 <= len(rows) <= MAX_ROWS:
        problems.append("rows")
    if any(line != "" for _, line in body):
        problems.append("trailing")

    problems.extend(_row_problems(rows))
    return problems


def _row_problems(rows: list[str]) -> list[str]:
    problems = []
    for row in rows:
        if not (row.startswith("|") and row.endswith("|")):
            problems.append("cells")
            continue
        cells = [cell.strip() for cell in row[1:-1].split("|")]
        if len(cells) != 4:
            problems.append("cells")
            continue
        rule, guidance, opened, recent = cells
        if not RULE_KEY.fullmatch(rule):
            problems.append("rule-key")
        if not guidance or len(guidance) > MAX_GUIDANCE:
            problems.append("guidance")
        if not (COUNT.fullmatch(opened) and COUNT.fullmatch(recent)):
            problems.append("count")
    return problems


def _table_text(rows=None, *, stamp=STAMP_PREFIX + "2026-01-01T00:00:00Z revision: abc", after=""):
    if rows is None:
        rows = ["| python:S9073 | Composite assertions should be split | 1 | 24 |"]
    lines = [TITLE]
    if stamp is not None:
        lines.append(stamp)
    lines += ["", HEADER, SEPARATOR, *rows]
    return "\n".join(lines) + "\n" + after


def _write(tmp_path, text):
    path = tmp_path / "analyser-rules.md"
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return path


# --------------------------------------------------------------------------- #
# The committed file
# --------------------------------------------------------------------------- #


def test_committed_table_is_tracked_by_git():
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", TABLE_GIT_PATH],
        cwd=REPO_ROOT,
        env=sanitized_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_committed_table_is_a_regular_file_not_a_symlink():
    assert not TABLE.is_symlink()
    assert TABLE.is_file()


def test_committed_table_is_well_formed():
    assert validate_table(TABLE) == []


# --------------------------------------------------------------------------- #
# Hostile fixtures: one rule broken each, through the same function
# --------------------------------------------------------------------------- #


def test_fixture_baseline_is_accepted(tmp_path):
    assert validate_table(_write(tmp_path, _table_text())) == []


def test_symlink_is_rejected(tmp_path):
    real = _write(tmp_path, _table_text())
    link = tmp_path / "link.md"
    link.symlink_to(real)
    assert validate_table(link) == ["symlink"]


def test_missing_file_is_rejected(tmp_path):
    assert validate_table(tmp_path / "absent.md") == ["not-regular-file"]


def test_one_byte_over_the_size_ceiling_is_rejected(tmp_path):
    text = _table_text()
    padded = text + "\n" * (MAX_BYTES + 1 - len(text))
    assert len(padded.encode()) == MAX_BYTES + 1
    assert validate_table(_write(tmp_path, padded)) == ["size"]


def test_exactly_the_size_ceiling_is_accepted(tmp_path):
    text = _table_text()
    padded = text + "\n" * (MAX_BYTES - len(text))
    assert len(padded.encode()) == MAX_BYTES
    assert validate_table(_write(tmp_path, padded)) == []


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param("\U000e0041", id="tag-character"),
        pytest.param("‮", id="bidi-control"),
        pytest.param("\x1b[2J", id="escape"),
        pytest.param("\t", id="tab"),
        pytest.param("\r", id="carriage-return"),
        pytest.param("é", id="non-ascii-letter"),
    ],
)
def test_non_printable_or_non_ascii_content_is_rejected(tmp_path, hostile):
    row = f"| python:S9073 | Composite assertions{hostile} should be split | 1 | 24 |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == ["charset"]


def test_nul_byte_is_rejected(tmp_path):
    raw = _table_text().encode() + b"\x00"
    assert validate_table(_write(tmp_path, raw)) == ["charset"]


def test_twenty_one_rows_are_rejected(tmp_path):
    rows = [f"| python:S{n} | Some rule | 0 | 0 |" for n in range(MAX_ROWS + 1)]
    assert validate_table(_write(tmp_path, _table_text(rows))) == ["rows"]


def test_twenty_rows_are_accepted(tmp_path):
    rows = [f"| python:S{n} | Some rule | 0 | 0 |" for n in range(MAX_ROWS)]
    assert validate_table(_write(tmp_path, _table_text(rows))) == []


def test_zero_rows_are_rejected(tmp_path):
    assert validate_table(_write(tmp_path, _table_text([]))) == ["rows"]


def test_five_cell_row_is_rejected(tmp_path):
    row = "| python:S9073 | Composite assertions should be split | 1 | 24 | extra |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == ["cells"]


def test_rule_key_with_a_space_is_rejected(tmp_path):
    row = "| python:S 9073 | Composite assertions should be split | 1 | 24 |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == ["rule-key"]


def test_rule_key_over_64_characters_is_rejected(tmp_path):
    row = f"| {'a' * 65} | Composite assertions should be split | 1 | 24 |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == ["rule-key"]


def test_guidance_of_161_characters_is_rejected(tmp_path):
    row = f"| python:S9073 | {'g' * (MAX_GUIDANCE + 1)} | 1 | 24 |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == ["guidance"]


def test_guidance_of_160_characters_is_accepted(tmp_path):
    row = f"| python:S9073 | {'g' * MAX_GUIDANCE} | 1 | 24 |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == []


def test_empty_guidance_is_rejected(tmp_path):
    row = "| python:S9073 |  | 1 | 24 |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == ["guidance"]


@pytest.mark.parametrize("bad", ["abc", "1.5", "-1", ""])
def test_non_integer_count_is_rejected(tmp_path, bad):
    row = f"| python:S9073 | Composite assertions should be split | {bad} | 24 |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == ["count"]


def test_non_integer_recent_new_count_is_rejected(tmp_path):
    row = "| python:S9073 | Composite assertions should be split | 1 | many |"
    assert validate_table(_write(tmp_path, _table_text([row]))) == ["count"]


def test_missing_derived_line_is_rejected(tmp_path):
    assert validate_table(_write(tmp_path, _table_text(stamp=None))) == ["derived"]


def test_wrong_title_is_rejected(tmp_path):
    text = _table_text().replace(TITLE, "# Something else", 1)
    assert validate_table(_write(tmp_path, text)) == ["title"]


def test_altered_header_row_is_rejected(tmp_path):
    text = _table_text().replace("| guidance |", "| advice |", 1)
    assert validate_table(_write(tmp_path, text)) == ["header"]


def test_free_text_between_stamp_and_header_is_rejected(tmp_path):
    text = _table_text().replace(HEADER, "A paragraph of prose.\n\n" + HEADER, 1)
    assert validate_table(_write(tmp_path, text)) == ["header"]


def test_free_text_paragraph_after_the_table_is_rejected(tmp_path):
    text = _table_text(after="\nSome extra paragraph of free text.\n")
    assert validate_table(_write(tmp_path, text)) == ["trailing"]


def test_blank_lines_after_the_table_are_accepted(tmp_path):
    assert validate_table(_write(tmp_path, _table_text(after="\n\n"))) == []
