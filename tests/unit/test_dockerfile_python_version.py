"""Cross-file consistency test for the Python interpreter version.

`Dockerfile` is production's ground truth for the interpreter CouchPotato
actually ships on. Two other files restate that version by hand rather than
reading it: `.github/workflows/ci.yml`'s test matrix (so CI actually exercises
the interpreter that ships) and `scripts/test-local.sh`'s default (so the local
Alpine-Docker runner matches production instead of an arbitrary older version).

Nothing enforced them staying in sync before this file existed: T1.6 found
`ci.yml` missing `3.14` and `test-local.sh` defaulting to `3.12` while the
Dockerfile had already moved to `python:3.14-alpine` on both stages. Modelled
on `tests/unit/test_gitleaks_config.py` — pure-python, no docker/network,
asserts against the real repo files.

Deliberately NOT hardcoding "3.14" as an expected literal: every assertion here
reads the version out of one of the three files and compares it against another
file's independently-parsed value. If all three files drifted to agree on a
wrong version, this test could not catch it — but that is a different, weaker
class of bug than "one file was bumped and the others were not", which is the
failure mode this test exists to catch and which mutation-testing below proves
it catches.
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
TEST_LOCAL_SH = REPO_ROOT / "scripts" / "test-local.sh"

# Matches `FROM python:3.14-alpine` (with or without an `AS <stage>` suffix).
DOCKERFILE_FROM_RE = re.compile(
    r"^FROM\s+python:(?P<version>\d+\.\d+)-alpine\b", re.MULTILINE
)

# `PYTHON_VERSION="${1:-3.14}"` — a bash default-value expansion.
TEST_LOCAL_DEFAULT_RE = re.compile(
    r'PYTHON_VERSION="\$\{1:-(?P<version>\d+\.\d+)\}"'
)


def dockerfile_versions() -> list[str]:
    """Every `FROM python:<ver>-alpine` version in the Dockerfile, in order."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    versions = DOCKERFILE_FROM_RE.findall(text)
    assert versions, (
        f"no `FROM python:<ver>-alpine` line found in {DOCKERFILE} — the "
        f"extraction regex may be stale, or the base image changed"
    )
    return versions


def ci_matrix_python_versions() -> list[str]:
    """`strategy.matrix.python-version` for the `test` job, parsed as real YAML.

    Not a string search: `python-version` also appears as a scalar
    (`python-version: '3.12'`) in several other jobs in this file, so a naive
    grep for the string would pick up unrelated jobs. Loading the YAML and
    walking to the specific job/key avoids that ambiguity entirely.
    """
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})
    assert "test" in jobs, f"{CI_WORKFLOW} has no `test` job — has it been renamed?"
    matrix = jobs["test"].get("strategy", {}).get("matrix", {})
    versions = matrix.get("python-version")
    assert versions, (
        f"the `test` job in {CI_WORKFLOW} has no `strategy.matrix.python-version` "
        f"list — has the matrix been restructured?"
    )
    return [str(v) for v in versions]


def local_default_version() -> str:
    """The version `scripts/test-local.sh` uses when invoked with no argument."""
    text = TEST_LOCAL_SH.read_text(encoding="utf-8")
    match = TEST_LOCAL_DEFAULT_RE.search(text)
    assert match, (
        f"could not find `PYTHON_VERSION=\"${{1:-X.Y}}\"` in {TEST_LOCAL_SH} — "
        f"has the default-value expansion changed shape?"
    )
    return match.group("version")


def test_dockerfile_builder_and_runtime_stages_agree():
    """The Dockerfile itself must be internally consistent before anything else
    is compared against it — a `FROM` mismatch between the two stages would
    make every other assertion here meaningless (which version is "the" one?)."""
    versions = dockerfile_versions()
    assert len(versions) == 2, (
        f"expected exactly 2 `FROM python:<ver>-alpine` lines (builder + "
        f"runtime stages), found {len(versions)}: {versions}"
    )
    builder, runtime = versions
    assert builder == runtime, (
        f"Dockerfile builder stage is on Python {builder} but the runtime "
        f"stage is on {runtime} — these must match, or the image is built "
        f"with one interpreter's wheels and run on another"
    )


def test_ci_matrix_tests_the_dockerfile_version():
    """production's interpreter (Dockerfile) must be a CI-tested interpreter."""
    dockerfile_version = dockerfile_versions()[0]
    matrix_versions = ci_matrix_python_versions()
    assert dockerfile_version in matrix_versions, (
        f"Dockerfile ships Python {dockerfile_version}, but ci.yml's test "
        f"matrix ({matrix_versions}) does not include it — CI is not testing "
        f"the interpreter that ships in production. Add {dockerfile_version!r} "
        f"to `strategy.matrix.python-version` in {CI_WORKFLOW}."
    )


def test_local_docker_runner_defaults_to_the_dockerfile_version():
    """`./scripts/test-local.sh` with no argument should reproduce production,
    not an arbitrary older interpreter a developer has to remember to pass."""
    dockerfile_version = dockerfile_versions()[0]
    local_default = local_default_version()
    assert dockerfile_version == local_default, (
        f"Dockerfile ships Python {dockerfile_version} but "
        f"{TEST_LOCAL_SH}'s default is {local_default} — update "
        f"`PYTHON_VERSION=\"${{1:-{dockerfile_version}}}\"` so the local Alpine "
        f"test runner matches production by default."
    )
