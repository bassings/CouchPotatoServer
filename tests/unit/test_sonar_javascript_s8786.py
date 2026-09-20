"""Ownership and recurrence contracts for the browser S8786 batch."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_TEMPLATES = (
    REPO_ROOT / "couchpotato/ui/templates/logs.html",
    REPO_ROOT / "couchpotato/ui/templates/partials/settings/scripts.html",
)
SHARED_MODULE = REPO_ROOT / "couchpotato/static/scripts/ui/log-parser.js"
BARREL = REPO_ROOT / "couchpotato/static/scripts/ui/index.js"
VULNERABLE_HEADER = (
    r"^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(ERROR|WARNING|INFO|DEBUG)\s+\[([^\]]*)\]\s*(.*)$"
)


def test_both_log_surfaces_delegate_to_the_one_shared_parser():
    for path in LOG_TEMPLATES:
        source = path.read_text(encoding="utf-8")
        assert "parseLogs(lines) {\n      return CP.ui.parseLogLines(lines);\n    }" in source, path
        assert VULNERABLE_HEADER not in source, path

    shared_source = SHARED_MODULE.read_text(encoding="utf-8")
    assert "export function parseLogLines" in shared_source
    assert VULNERABLE_HEADER not in shared_source
    assert "export * from './log-parser.js';" in BARREL.read_text(encoding="utf-8")


def test_the_raw_header_parser_has_no_third_workflow_copy():
    roots = (
        REPO_ROOT / "couchpotato/ui/templates",
        REPO_ROOT / "couchpotato/static/scripts/ui",
    )
    offenders = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".html", ".js", ".ts"}:
                continue
            if VULNERABLE_HEADER in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, "vulnerable raw-log parser restored at: " + ", ".join(offenders)
