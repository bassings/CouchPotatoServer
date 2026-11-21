"""Guard for the ruff rule selection in pyproject.toml.

PT018 (composite assertion, the analyser's python:S9073) and PT012
(`pytest.raises` block with more than one statement, python:S5778) are enforced
everywhere, tests included. A rule silently dropped from `extend-select` stops
gating with nothing to say so, which is the failure this file exists to catch.
The selection is read with `tomllib`, not grepped, so a rule named only in a
comment cannot satisfy it.
"""

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _lint_config():
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["tool"]["ruff"]["lint"]


@pytest.mark.parametrize("rule", ["S113", "PT018", "PT012"])
def test_rule_is_selected(rule):
    assert rule in _lint_config()["extend-select"]


@pytest.mark.parametrize("rule", ["PT018", "PT012"])
def test_rule_is_not_ignored_anywhere(rule):
    lint = _lint_config()
    assert rule not in lint.get("ignore", [])
    for path, ignored in lint.get("per-file-ignores", {}).items():
        assert rule not in ignored, f"{rule} is ignored for {path}"
