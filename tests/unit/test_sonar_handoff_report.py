"""Keep the point-in-time SonarQube dispositions complete."""

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "specs/REPORT-2026-10-08-sonarqube-dispositions.md"
SNAPSHOT = ROOT / "specs/SONAR-2026-10-08-local-issues.json"


def test_every_local_issue_has_its_own_disposition():
    snapshot = json.loads(SNAPSHOT.read_text())
    assert snapshot["revision"] == "775c6b05114820b7496965a988ddffacf99f6a1a"
    expected = {issue["sonar_issue_id"]: issue for issue in snapshot["issues"]}
    assert len(expected) == len(snapshot["issues"]) == 103

    section = REPORT.read_text().split("### Per-issue local dispositions\n", 1)[1]
    section = section.split("## Final measured state\n", 1)[0]
    actual = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        columns = line.strip("| ").split(" | ")
        assert len(columns) == 6
        key = columns[0].strip("`")
        assert key not in actual, f"duplicate disposition for {key}"
        actual[key] = columns

    assert set(actual) == set(expected), "every snapshot issue needs exactly one disposition"
    for key, (marked_key, rule, site, source, message, decision) in actual.items():
        issue = expected[key]
        assert marked_key == f"`{key}`"
        assert rule == f"`{issue['rule']}`"
        assert site == f"`{issue['path']}:{issue['line']}`"
        assert html.unescape(source.removeprefix("<code>").removesuffix("</code>")) == issue["source"]
        assert html.unescape(message) == issue["message"]
        assert decision.startswith("Hold: ")
        assert len(decision) > len("Hold: ")
