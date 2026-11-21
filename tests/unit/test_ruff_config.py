"""Guard for the ruff rule selection in pyproject.toml.

PT018 (composite assertion) and PT012 (`pytest.raises` block with more than
one statement) are enforced everywhere, tests included. They are the nearest
ruff counterparts to the analyser's python:S9073 and python:S5778 (S5778 counts
invocations, PT012 counts statements, so they overlap rather than match). A rule
silently dropped stops gating with nothing to say so, which is the failure this
file exists to catch.

Two layers. The `tomllib` tests read the selection and give a clear message for
the obvious edits. They cannot see prefix ignores (`"PT"`), `exclude`,
`extend-ignore` or `extend-per-file-ignores`, so the behavioural test runs ruff
itself with the repo config on a probe at a tests/ path and asserts both rules
are reported.
"""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _lint_config():
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["tool"]["ruff"]["lint"]


@pytest.mark.parametrize("rule", ["S113", "PT018", "PT012"])
def test_rule_is_selected(rule):
    assert rule in _lint_config()["extend-select"]


@pytest.mark.parametrize("rule", ["PT018", "PT012"])
def test_rule_is_not_listed_in_ignore_or_per_file_ignores(rule):
    lint = _lint_config()
    assert rule not in lint.get("ignore", [])
    for path, ignored in lint.get("per-file-ignores", {}).items():
        assert rule not in ignored, f"{rule} is ignored for {path}"


PROBE = """\
import pytest


def test_composite(a, b):
    assert a and b


def test_raises_block():
    with pytest.raises(ValueError):
        x = 1
        int("z")
"""


def test_ruff_reports_both_rules_on_a_tests_path_with_the_repo_config():
    # --force-exclude makes an `exclude` entry apply to the stdin path too.
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "-",
            "--stdin-filename",
            "tests/unit/test_probe_for_ruff_config.py",
            "--force-exclude",
            "--output-format",
            "json",
        ],
        input=PROBE,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode in (0, 1), proc.stderr
    reported = {d["code"] for d in json.loads(proc.stdout)}
    assert {"PT018", "PT012"} <= reported
