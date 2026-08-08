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


def test_ci_matrix_tests_exactly_the_dockerfile_version():
    """CI tests the production interpreter, and ONLY it.

    Strengthened from membership to equality when the matrix was locked to a
    single version (2026-08-09). Membership was the right check while five
    legs ran; with one leg it would be satisfied by a matrix that had drifted
    to `['3.12', '3.14']` and quietly reintroduced 15.6 runner-minutes a push.

    Equality also makes the pairing explicit in the other direction: bumping
    the Dockerfile without bumping CI fails here, so production can never ship
    an interpreter no test has run. Re-broadening the matrix is then a
    deliberate act that has to change this test and say why.
    """
    dockerfile_version = dockerfile_versions()[0]
    matrix_versions = ci_matrix_python_versions()
    assert matrix_versions == [dockerfile_version], (
        f"Dockerfile ships Python {dockerfile_version} but ci.yml's test "
        f"matrix is {matrix_versions}. CI must test exactly the interpreter "
        f"production runs: set `strategy.matrix.python-version` to "
        f"['{dockerfile_version}'] in {CI_WORKFLOW}. If you are deliberately "
        f"re-broadening the matrix, update this test and record why -- the "
        f"four extra legs were dropped because 59 consecutive CI runs showed "
        f"no leg ever failing and no two legs ever disagreeing."
    )


def test_every_ci_job_uses_the_dockerfile_python():
    """Not just the `test` matrix -- EVERY setup-python in ci.yml.

    This is the guard that would have caught the drift it was written for.
    When the matrix was narrowed to the production interpreter, five jobs were
    still pinned to 3.12 by a separate `python-version:` field, including
    `ui-e2e-tests` and `accessibility` -- which START THE APPLICATION. So the
    two browser gates were exercising an interpreter the project had just
    declared unsupported, while the matrix guard passed because it only looked
    at the matrix.

    Checking one place and calling it "CI tests what production ships" is the
    failure here; the claim is only as strong as its weakest job.
    """
    dockerfile_version = dockerfile_versions()[0]
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    wrong = []
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            if not str(step.get("uses", "")).startswith("actions/setup-python"):
                continue
            version = str((step.get("with") or {}).get("python-version", ""))
            if version.startswith("${{"):
                continue  # driven by the matrix, covered by the test above
            if version != dockerfile_version:
                wrong.append(f"{job_name}={version}")

    assert not wrong, (
        f"Dockerfile ships Python {dockerfile_version} but these ci.yml jobs "
        f"pin a different interpreter: {sorted(wrong)}. Jobs that start the "
        f"application (ui-e2e-tests, accessibility) must run the production "
        f"interpreter or the gate is testing something nobody ships."
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


def test_the_ruff_pin_agrees_across_requirements_dev_and_both_ci_jobs():
    """The ruff pin is duplicated three ways; nothing compared them.

    AC-SIMP-9 deliberately chose duplication over a mechanism that removes it
    (sourcing the lint job from requirements-dev.txt would install pytest,
    mutmut and coverage into a lint job for no benefit). That choice is fine.
    What was missing is a check that the three copies agree.

    Without it: bump requirements-dev.txt to 0.17.0 and forget ci.yml, and
    `verify.sh` goes green locally on 0.17.0 while both CI jobs lint on 0.16.0.
    That is the same silent-drift class T1.5 exists to close, reopened one file
    over, with no signal in either direction.

    This is the same shape as the Dockerfile/CI/test-local.sh agreement above,
    and adds no workflow, no job and no script.
    """
    req = (REPO_ROOT / 'requirements-dev.txt').read_text(encoding='utf-8')
    pinned = re.findall(r'^ruff==(\S+)\s*$', req, re.MULTILINE)
    assert len(pinned) == 1, (
        'requirements-dev.txt must carry exactly one exact ruff pin '
        '(ruff==X.Y.Z), found: %s' % pinned
    )

    ci = (REPO_ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
    installed = re.findall(r"pip install\s+['\"]ruff==(\S+?)['\"]", ci)
    assert len(installed) == 2, (
        'expected both the lint and security-lint jobs to install a quoted, '
        'exactly-pinned ruff; found %s' % installed
    )

    assert set(installed) == set(pinned), (
        'ruff pin drift: requirements-dev.txt has %s, ci.yml installs %s. '
        'verify.sh checks the installed version against requirements-dev.txt '
        'only, so this divergence is invisible locally and lints CI on a '
        'different version than the gate you ran.' % (pinned, sorted(set(installed)))
    )


def test_the_cve_removal_step_is_not_pinned_to_a_python_minor_version():
    """`rm -rf` exits 0 on a missing path, so a hardcoded minor version makes
    the pip-removal step a silent no-op the day the base image is bumped.

    That step exists to remove pip and its vendored setuptools/msgpack, which
    Trivy flags as two fixable HIGHs (CVE-2025-47273, GHSA-6v7p-g79w-8964).
    Written as `/usr/local/lib/python3.14/site-packages/...`, a bump to 3.15
    leaves every path unmatched, the RUN succeeds, and the vulnerable pip walks
    back into the shipped image with nothing going red -- the guard disarms
    itself on an edit made somewhere else entirely.

    Checked as "no version-specific site-packages path", not as "matches the
    current FROM", deliberately: keeping the two in step is a rule someone has
    to remember, and the glob needs no remembering at all.
    """
    text = DOCKERFILE.read_text(encoding="utf-8")

    removal_lines = [
        line for line in text.splitlines()
        if "site-packages" in line and not line.lstrip().startswith("#")
    ]
    assert removal_lines, (
        "no site-packages path found in the Dockerfile -- the CVE-removal step "
        "has moved or been deleted, and this guard is no longer watching it"
    )

    pinned = [line.strip() for line in removal_lines
              if re.search(r"python3\.\d+/site-packages", line)]
    assert not pinned, (
        "these Dockerfile paths hardcode a Python minor version, so they stop "
        "matching (and silently remove nothing) when the base image is "
        "bumped: %s" % pinned
    )
