"""Guards for the repository's advanced CodeQL configuration."""

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO / ".github" / "workflows" / "codeql.yml"

EXPECTED_LANGUAGES = [
    {"language": "python", "check_name": "python"},
    {"language": "javascript-typescript", "check_name": "javascript"},
    {"language": "actions", "check_name": "actions"},
]


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_codeql_scans_every_repository_language_without_renaming_required_checks(workflow):
    analyze = workflow["jobs"]["analyze"]

    assert analyze["name"] == "Analyze (${{ matrix.check_name }})"
    assert analyze["strategy"]["fail-fast"] is False
    assert analyze["strategy"]["matrix"] == {"include": EXPECTED_LANGUAGES}


def test_codeql_matrix_drives_initialization_and_canonical_analysis_categories(workflow):
    analyze = workflow["jobs"]["analyze"]
    steps = {step["uses"]: step for step in analyze["steps"] if "uses" in step}

    assert steps["github/codeql-action/init@v4"]["with"]["languages"] == "${{ matrix.language }}"
    assert steps["github/codeql-action/analyze@v4"]["with"]["category"] == (
        "/language:${{ matrix.language }}"
    )
    assert analyze["permissions"] == {"contents": "read", "security-events": "write"}


def test_codeql_keeps_security_triggers_permissions_and_action_versions(workflow):
    assert workflow[True] == {
        "push": {"branches": ["master"]},
        "pull_request": {"branches": ["master"]},
        "workflow_dispatch": None,
        "schedule": [{"cron": "0 6 * * 1"}],
    }
    assert workflow["permissions"] == {"contents": "read", "security-events": "write"}
    assert [step["uses"] for step in workflow["jobs"]["analyze"]["steps"]] == [
        "actions/checkout@v7",
        "github/codeql-action/init@v4",
        "github/codeql-action/autobuild@v4",
        "github/codeql-action/analyze@v4",
    ]
